"""
The search index: embeddings, storage, and incremental ingestion.

Storage is Chroma, kept on disk under `index/`, plus a small `manifest.json`
recording a fingerprint (SHA-256) for every document that has been indexed.

Ingestion compares fingerprints, so re-running it is cheap and safe:

    new file      -> read, chunk, embed, add
    changed file  -> delete its old chunks, then add the new ones
    deleted file  -> delete its chunks
    unchanged     -> skipped entirely

That matters in practice: a client drops one new policy into the folder and
gets it searchable in seconds, without rebuilding everything.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import chromadb

from app.chunking import Chunk, chunk_segments, file_fingerprint
from app.config import settings
from app.loaders import SUPPORTED_SUFFIXES, load_document

COLLECTION_NAME = "documents"

# Loaded on first use and then reused. Loading takes a second or two, so it is
# not done at import time (the CLI prints its header first, which feels faster).
_model = None


def get_model():
    """Load the local embedding model once per process."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(settings.embedding_model)
    return _model


def embed_passages(texts: list[str]) -> list[list[float]]:
    """Embed document chunks. Vectors are normalised, so cosine similarity is a dot product."""
    return get_model().encode(texts, normalize_embeddings=True, batch_size=32).tolist()


def embed_query(text: str) -> list[float]:
    """
    Embed a question. BGE models are trained to work best when the question
    carries this short instruction prefix, which lifts retrieval accuracy at no cost.
    """
    prefix = "Represent this sentence for searching relevant passages: "
    return get_model().encode(prefix + text, normalize_embeddings=True).tolist()


def get_collection():
    """Open (or create) the on-disk Chroma collection."""
    client = chromadb.PersistentClient(path=str(settings.index_dir / "chroma"))
    # Cosine distance matches the normalised vectors produced above.
    return client.get_or_create_collection(name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"})


# ---------------------------------------------------------------------------
# Manifest: what has been indexed, and from which version of each file
# ---------------------------------------------------------------------------

def _manifest_path() -> Path:
    return settings.index_dir / "manifest.json"


def read_manifest() -> dict[str, dict]:
    path = _manifest_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_manifest(manifest: dict[str, dict]) -> None:
    settings.index_dir.mkdir(parents=True, exist_ok=True)
    _manifest_path().write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

@dataclass
class FileResult:
    """What happened to one document during ingestion, for the report at the end."""

    name: str
    action: str            # "added" | "updated" | "unchanged" | "removed" | "failed"
    chunks: int = 0
    pages: int = 0
    ocr_pages: int = 0
    note: str = ""


def ingest(force: bool = False) -> list[FileResult]:
    """
    Bring the index in line with the documents folder.

    `force=True` re-reads every document even when its fingerprint is unchanged,
    which is what you want after changing the chunking rules.
    """
    documents_root = settings.documents_dir
    documents_root.mkdir(parents=True, exist_ok=True)
    collection = get_collection()
    manifest = read_manifest()
    results: list[FileResult] = []

    # Every supported file in the folder and its sub-folders.
    found = {
        str(p.relative_to(documents_root)): p
        for p in sorted(documents_root.rglob("*"))
        if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES and not p.name.startswith(".")
    }

    # 1. Files that are gone: remove their chunks and their manifest entry.
    for known in list(manifest):
        if known not in found:
            collection.delete(where={"source_path": known})
            manifest.pop(known)
            results.append(FileResult(name=known, action="removed"))

    # 2. New, changed, or unchanged files.
    for relative_name, path in found.items():
        fingerprint = file_fingerprint(path)
        previous = manifest.get(relative_name)
        if previous and previous["fingerprint"] == fingerprint and not force:
            results.append(FileResult(name=relative_name, action="unchanged", chunks=previous["chunks"]))
            continue

        action = "updated" if previous else "added"
        try:
            segments = load_document(path)
            chunks = chunk_segments(segments, path, documents_root)
            if not chunks:
                raise ValueError("no readable text found")

            # Replace, never append: the old chunks go first, so a shrinking
            # document cannot leave stale passages behind to be quoted later.
            collection.delete(where={"source_path": relative_name})
            _add_chunks(collection, chunks, relative_name)

            manifest[relative_name] = {
                "fingerprint": fingerprint,
                "chunks": len(chunks),
                "pages": len({c.page for c in chunks if c.page is not None}),
                "source_type": chunks[0].source_type,
            }
            results.append(FileResult(
                name=relative_name,
                action=action,
                chunks=len(chunks),
                pages=manifest[relative_name]["pages"],
                ocr_pages=len({c.page for c in chunks if c.needed_ocr}),
            ))
        except Exception as exc:  # one bad file must not stop the whole run
            results.append(FileResult(name=relative_name, action="failed", note=str(exc)))

    write_manifest(manifest)
    return results


def _add_chunks(collection, chunks: list[Chunk], relative_name: str) -> None:
    """Embed the chunks and write them to Chroma with their citation metadata."""
    embeddings = embed_passages([c.embed_text for c in chunks])
    collection.add(
        ids=[c.chunk_id for c in chunks],
        documents=[c.text for c in chunks],
        embeddings=embeddings,
        # Chroma metadata values must be simple types, so `page` uses -1 rather
        # than None for documents without pages.
        metadatas=[{
            "source_file": c.source_file,
            "source_path": relative_name,
            "source_type": c.source_type,
            "page": c.page if c.page is not None else -1,
            "heading": c.heading or "",
            "needed_ocr": c.needed_ocr,
            "folder": c.folder,
        } for c in chunks],
    )


def all_chunks() -> list[dict]:
    """
    Every stored chunk with its text and metadata. Used to build the keyword
    (BM25) index at query time, and by the tests.
    """
    stored = get_collection().get(include=["documents", "metadatas"])
    return [
        {"chunk_id": chunk_id, "text": text, **metadata}
        for chunk_id, text, metadata in zip(stored["ids"], stored["documents"], stored["metadatas"])
    ]


def index_stats() -> dict:
    """Small summary used by the CLI and, later, by the web interface."""
    manifest = read_manifest()
    return {
        "documents": len(manifest),
        "chunks": get_collection().count(),
        "files": manifest,
    }
