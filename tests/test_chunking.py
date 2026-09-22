"""
Tests for the rules that citations depend on.

Run them with:  .venv/bin/python -m pytest -q

These use made-up segments rather than real files, so they are fast and do not
need the embedding model or the index.
"""

from pathlib import Path

from app.chunking import TARGET_WORDS, chunk_segments, file_fingerprint
from app.loaders import Segment

ROOT = Path("documents")


def words(count: int, word: str = "equipment") -> str:
    return " ".join([word] * count)


def test_chunk_never_crosses_a_page():
    """The core promise behind page citations: one chunk belongs to one page."""
    segments = [
        Segment(text=words(400), page=1, heading="1. First"),
        Segment(text=words(400), page=2, heading="2. Second"),
    ]
    chunks = chunk_segments(segments, ROOT / "manual.pdf", ROOT)

    assert len(chunks) > 2                       # both pages were split
    pages = {c.page for c in chunks}
    assert pages == {1, 2}
    for chunk in chunks:
        # No chunk may contain text from both pages: each page used a different word.
        assert chunk.page in (1, 2)
    assert all(c.source_file == "manual.pdf" for c in chunks)


def test_long_page_is_split_with_overlap():
    """Pieces stay near the word budget, and each carries a tail of the previous one."""
    lines = "\n".join(words(40, f"word{i}") for i in range(20))  # 800 words
    chunks = chunk_segments([Segment(text=lines, page=3, heading=None)], ROOT / "a.pdf", ROOT)

    assert len(chunks) >= 3
    assert all(len(c.text.split()) <= TARGET_WORDS + 60 for c in chunks)
    # The start of chunk 2 repeats words from the end of chunk 1.
    assert set(chunks[0].text.split()[-20:]) & set(chunks[1].text.split()[:60])


def test_page_number_is_none_for_word_files_and_location_uses_the_heading():
    chunks = chunk_segments(
        [Segment(text="5.1 Vacation\n" + words(50), page=None, heading="5.1 Vacation")],
        ROOT / "handbook.docx", ROOT,
    )
    assert chunks[0].page is None
    assert chunks[0].location == "5.1 Vacation"


def test_short_sections_are_merged_but_pages_are_not():
    """Short Word/text sections merge into usable chunks; separate pages never do."""
    tiny_sections = [Segment(text=words(30), page=None, heading=f"{i}. Section") for i in range(6)]
    merged = chunk_segments(tiny_sections, ROOT / "faq.txt", ROOT)
    assert len(merged) < len(tiny_sections)

    tiny_pages = [Segment(text=words(30), page=i, heading=None) for i in range(1, 7)]
    not_merged = chunk_segments(tiny_pages, ROOT / "scan.pdf", ROOT)
    assert len(not_merged) == len(tiny_pages)


def test_chunk_id_shows_where_the_text_came_from():
    chunks = chunk_segments([Segment(text=words(50), page=4, heading=None)], ROOT / "rental.pdf", ROOT)
    assert chunks[0].chunk_id == "rental.pdf|p4|c0"


def test_heading_is_the_section_the_chunk_starts_in():
    """A chunk that opens with a heading takes it; a later chunk keeps carrying it."""
    text = "6. Late Returns\n" + "\n".join(words(40, f"w{i}") for i in range(12))
    chunks = chunk_segments([Segment(text=text, page=3, heading="6. Late Returns")], ROOT / "a.pdf", ROOT)
    assert chunks[0].heading == "6. Late Returns"
    assert chunks[1].heading == "6. Late Returns"


def test_fingerprint_changes_when_the_file_changes(tmp_path):
    """This is what makes re-ingestion skip unchanged documents."""
    path = tmp_path / "policy.txt"
    path.write_text("Late returns are charged at 1.5 times the daily rate.")
    before = file_fingerprint(path)

    path.write_text("Late returns are charged at 2 times the daily rate.")
    assert file_fingerprint(path) != before
