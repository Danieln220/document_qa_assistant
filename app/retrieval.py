"""
Finding the passages that answer a question.

Two searches run over the same chunks and their results are merged:

* **Vector search** matches meaning. "How much do we charge for a late return?"
  finds a passage about "late charges of 1.5 times the Daily Rate" even though
  the words differ.
* **Keyword search (BM25)** matches exact strings. Business documents are full
  of codes and clause numbers - "EX-35", "SC-26", "Section 9.3" - and meaning-based
  search is weak at those, because one model code looks much like another.

The two rankings are combined with Reciprocal Rank Fusion: each result scores
1/(60+rank) in each list, and the scores are added. It needs no tuning and does
not care that cosine similarity and BM25 scores are on different scales, which
is exactly why it is the usual choice for hybrid search.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from app.config import settings
from app.index import all_chunks, embed_query, get_collection

# How many candidates each search contributes before merging. Bigger than the
# final top_k, so a passage that only one of the two searches ranks highly still
# gets a chance to win after fusion.
CANDIDATES = 20

# The constant in Reciprocal Rank Fusion. 60 is the value from the original
# paper and the common default: large enough that the top few ranks score
# similarly, so one search cannot dominate the other.
RRF_K = 60

# Tokens keep internal hyphens, slashes and dots, so "EX-35", "A92.22" and
# "24/7" survive as single tokens instead of being split into noise.
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-/.]*")


@dataclass
class SearchResult:
    """One passage found for a question, with everything needed to cite it."""

    chunk_id: str
    text: str
    source_file: str
    source_path: str
    page: int | None
    heading: str
    needed_ocr: bool
    vector_score: float   # cosine similarity, 0 to 1; higher is closer in meaning
    keyword_score: float  # BM25 score; only comparable within one query
    fused_score: float    # Reciprocal Rank Fusion score, used for the final order
    matched_by: str       # "vector", "keyword" or "both"

    @property
    def location(self) -> str:
        """Where the passage sits: 'page 4', or the heading for files without pages."""
        if self.page is not None:
            return f"page {self.page}"
        return self.heading or "start of document"


# The BM25 index is built from the stored chunks and kept in memory. It is cheap
# to build (tens of milliseconds for a few thousand chunks) but not free, so it
# is rebuilt only when the number of chunks changes, i.e. after an ingest.
_bm25_cache: tuple[int, BM25Okapi, list[dict]] | None = None


def _tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def _get_bm25() -> tuple[BM25Okapi, list[dict]]:
    """Build (or reuse) the keyword index over every stored chunk."""
    global _bm25_cache
    count = get_collection().count()
    if _bm25_cache is None or _bm25_cache[0] != count:
        chunks = all_chunks()
        # The file name and heading are searched too, so "handbook" or "5.1
        # Vacation" in a question can match even when the body text does not
        # repeat those words.
        corpus = [
            _tokenize(f"{c['source_file']} {c.get('heading', '')} {c['text']}")
            for c in chunks
        ]
        _bm25_cache = (count, BM25Okapi(corpus) if corpus else None, chunks)
    return _bm25_cache[1], _bm25_cache[2]


def search(question: str, top_k: int | None = None) -> list[SearchResult]:
    """
    Return the best passages for a question, best first.

    The list is empty only when the index itself is empty. Deciding whether the
    results are *good enough* to answer from is the caller's job (see the
    relevance gate in `app/answer.py`).
    """
    top_k = top_k or settings.top_k
    collection = get_collection()
    if collection.count() == 0:
        return []

    # --- Vector search -----------------------------------------------------
    found = collection.query(
        query_embeddings=[embed_query(question)],
        n_results=min(CANDIDATES, collection.count()),
        include=["documents", "metadatas", "distances"],
    )
    vector_hits: dict[str, dict] = {}
    for rank, (chunk_id, text, metadata, distance) in enumerate(zip(
        found["ids"][0], found["documents"][0], found["metadatas"][0], found["distances"][0]
    )):
        vector_hits[chunk_id] = {
            "rank": rank,
            "text": text,
            "metadata": metadata,
            # Chroma returns cosine *distance*; similarity is 1 - distance.
            "score": 1.0 - float(distance),
        }

    # --- Keyword search ----------------------------------------------------
    bm25, chunks = _get_bm25()
    keyword_hits: dict[str, dict] = {}
    if bm25 is not None:
        scores = bm25.get_scores(_tokenize(question))
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:CANDIDATES]
        for rank, index in enumerate(ranked):
            if scores[index] <= 0:
                continue  # no shared terms at all: not a hit
            chunk = chunks[index]
            keyword_hits[chunk["chunk_id"]] = {
                "rank": rank,
                "text": chunk["text"],
                "metadata": chunk,
                "score": float(scores[index]),
            }

    # --- Merge with Reciprocal Rank Fusion ---------------------------------
    results: list[SearchResult] = []
    for chunk_id in set(vector_hits) | set(keyword_hits):
        vector = vector_hits.get(chunk_id)
        keyword = keyword_hits.get(chunk_id)
        source = vector or keyword
        metadata = source["metadata"]
        fused = 0.0
        if vector:
            fused += 1.0 / (RRF_K + vector["rank"] + 1)
        if keyword:
            fused += 1.0 / (RRF_K + keyword["rank"] + 1)

        page = metadata.get("page", -1)
        results.append(SearchResult(
            chunk_id=chunk_id,
            text=source["text"],
            source_file=metadata.get("source_file", ""),
            source_path=metadata.get("source_path", ""),
            page=None if page == -1 else int(page),
            heading=metadata.get("heading", "") or "",
            needed_ocr=bool(metadata.get("needed_ocr", False)),
            vector_score=vector["score"] if vector else 0.0,
            keyword_score=keyword["score"] if keyword else 0.0,
            fused_score=fused,
            matched_by="both" if vector and keyword else ("vector" if vector else "keyword"),
        ))

    results.sort(key=lambda r: r.fused_score, reverse=True)
    return results[:top_k]


def best_vector_score(results: list[SearchResult]) -> float:
    """
    The closest match in meaning among the results.

    This is the number the refusal gate uses: when even the best passage is far
    from the question, the assistant should say it doesn't know rather than ask
    the LLM to make something of it.
    """
    return max((r.vector_score for r in results), default=0.0)
