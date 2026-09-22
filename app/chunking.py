"""
Cutting documents into chunks.

A chunk is the unit that gets embedded, searched, and quoted in a citation. Two
rules drive the design:

1. **A chunk never crosses a page.** Each chunk comes from exactly one segment
   (one PDF page, or one heading section of a DOCX/TXT). That is what makes the
   page number on a citation exactly right, every time.
2. **A chunk is a few paragraphs, not a fixed number of characters.** Chunks are
   built from whole lines up to a word budget, with a small overlap, so sentences
   are not cut in half and an answer is rarely split across two chunks.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.loaders import Segment, find_heading

TARGET_WORDS = 300   # roughly 2 paragraphs of a policy document
OVERLAP_WORDS = 50   # repeated tail, so a fact on a chunk boundary is not lost
MIN_WORDS = 25       # anything shorter is merged into the previous chunk instead


@dataclass
class Chunk:
    """One searchable passage, with everything a citation needs."""

    chunk_id: str             # e.g. "Rental_Agreement.pdf|p4|c2"
    text: str                 # the exact text, used for quoting and for citation checks
    source_file: str          # file name, shown to the user
    source_type: str          # "pdf" | "docx" | "txt"
    page: int | None          # page number for PDFs, None otherwise
    heading: str | None       # nearest heading, shown when there is no page number
    needed_ocr: bool = False  # True when this text was read by OCR
    folder: str = ""          # sub-folder inside documents/ (used later for access control)
    embed_text: str = field(default="", repr=False)  # what the embedding model sees

    @property
    def location(self) -> str:
        """Human-readable position, used in citations: 'page 4' or 'Section 5.1 Vacation'."""
        if self.page is not None:
            return f"page {self.page}"
        return self.heading or "start of document"


def chunk_segments(segments: list[Segment], path: Path, documents_root: Path) -> list[Chunk]:
    """Turn one document's segments into chunks, with metadata filled in."""
    source_type = path.suffix.lower().lstrip(".")
    folder = str(path.parent.relative_to(documents_root))
    folder = "" if folder == "." else folder
    chunks: list[Chunk] = []

    # The heading a chunk belongs to is the last heading seen *before* it, which
    # carries across page breaks. Without this, every chunk on a page would be
    # labelled with the last heading on that page, even text above it.
    current_heading: str | None = None

    for segment_index, segment in enumerate(_merge_short_segments(segments)):
        if segment.heading and segment.page is None:
            current_heading = segment.heading  # DOCX/TXT sections carry their own heading
        for piece_index, piece in enumerate(_split_segment(segment.text)):
            # A chunk that opens with a heading belongs to that heading; one that
            # starts mid-section keeps the heading it started under.
            chunk_heading = find_heading(piece, first_lines=2) or current_heading
            current_heading = find_heading(piece) or current_heading

            # The ID carries the location, so a chunk is easy to trace by eye in
            # logs and in the LLM's output.
            where = f"p{segment.page}" if segment.page is not None else f"s{segment_index}"
            chunk_id = f"{path.name}|{where}|c{piece_index}"
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    text=piece,
                    source_file=path.name,
                    source_type=source_type,
                    page=segment.page,
                    heading=chunk_heading,
                    needed_ocr=segment.needed_ocr,
                    folder=folder,
                    # The embedded text gets the file name and heading added in
                    # front. A short chunk like "$45 per tooth" means little on
                    # its own; with "Returns and Damages Policy - 6. Standard
                    # Damage Charges" in front, it matches the right questions.
                    embed_text=_embed_text(path.name, chunk_heading, piece),
                )
            )
    return chunks


def _merge_short_segments(segments: list[Segment]) -> list[Segment]:
    """
    Join neighbouring page-less sections until they reach the word budget.

    A Word or text document often has many short sections ("8.3 Phones" is two
    sentences). One chunk per section would fill the index with stubs that match
    nothing and waste the LLM's context. Merging is only done where there are no
    page numbers, so it can never make a page citation wrong; the merged chunk
    keeps the heading of the first section it contains.
    """
    merged: list[Segment] = []
    for segment in segments:
        previous = merged[-1] if merged else None
        can_merge = (
            previous is not None
            and previous.page is None            # never merge across PDF pages
            and segment.page is None
            and previous.needed_ocr == segment.needed_ocr
            and len(previous.text.split()) + len(segment.text.split()) <= TARGET_WORDS
        )
        if can_merge:
            previous.text = previous.text + "\n" + segment.text
        else:
            # Copy, so the caller's segments are not modified in place.
            merged.append(Segment(
                text=segment.text, page=segment.page,
                heading=segment.heading, needed_ocr=segment.needed_ocr,
            ))
    return merged


def _split_segment(text: str) -> list[str]:
    """
    Split one segment into pieces of about TARGET_WORDS words, breaking on line
    boundaries (which are paragraph boundaries after the loader's cleanup), and
    repeating the last OVERLAP_WORDS words at the start of the next piece.
    """
    lines: list[str] = []
    for line in text.splitlines():
        if line.strip():
            # A single line longer than the whole budget (one huge paragraph, or
            # a page the PDF reader returned as one line) cannot be placed as a
            # unit, so it is broken into sentences first.
            lines.extend(_split_long_line(line) if len(line.split()) > TARGET_WORDS else [line])
    if not lines:
        return []

    pieces: list[str] = []
    current: list[str] = []
    current_words = 0

    for line in lines:
        words = len(line.split())
        # Close the current piece when adding this line would overshoot the
        # budget, unless the piece is still too small to stand alone.
        if current and current_words + words > TARGET_WORDS and current_words >= MIN_WORDS:
            pieces.append("\n".join(current))
            tail = _tail_words("\n".join(current), OVERLAP_WORDS)
            current = [tail] if tail else []
            current_words = len(tail.split())
        current.append(line)
        current_words += words

    if current:
        piece = "\n".join(current)
        # A very short trailing piece is glued onto the previous one rather than
        # left as a stub that matches nothing.
        if pieces and len(piece.split()) < MIN_WORDS:
            pieces[-1] = pieces[-1] + "\n" + piece
        else:
            pieces.append(piece)
    return pieces


def _split_long_line(line: str) -> list[str]:
    """
    Break one over-long line into sentences, grouped up to the word budget.

    Text with no sentence endings at all (a table dumped onto one line, for
    example) falls back to a plain word count, so nothing can produce a chunk
    too large to embed.
    """
    sentences = re.split(r"(?<=[.!?])\s+", line)
    grouped: list[str] = []
    current: list[str] = []
    for sentence in sentences:
        if current and len(" ".join(current).split()) + len(sentence.split()) > TARGET_WORDS:
            grouped.append(" ".join(current))
            current = []
        current.append(sentence)
    if current:
        grouped.append(" ".join(current))

    output: list[str] = []
    for piece in grouped:
        piece_words = piece.split()
        if len(piece_words) <= TARGET_WORDS:
            output.append(piece)
        else:
            output += [" ".join(piece_words[i:i + TARGET_WORDS])
                       for i in range(0, len(piece_words), TARGET_WORDS)]
    return output


def _tail_words(text: str, count: int) -> str:
    """Return the last `count` words of a piece, used as the overlap."""
    words = text.split()
    return " ".join(words[-count:]) if len(words) > count else text


def _embed_text(file_name: str, heading: str | None, text: str) -> str:
    """Give the embedding model the document title and heading as context."""
    title = Path(file_name).stem.replace("_", " ")
    head = f" - {heading}" if heading else ""
    return f"{title}{head}\n{text}"


def file_fingerprint(path: Path) -> str:
    """
    SHA-256 of the file's bytes. Ingestion compares this with the stored value to
    decide whether a document is new, changed, or unchanged, so re-running is cheap.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()
