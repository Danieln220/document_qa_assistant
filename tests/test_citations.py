"""
Tests for Gate 3, the citation check.

This is the guard that turns "the model promised to quote the documents" into
"the quote was found in the document". These tests use made-up passages and
never call the LLM, so they run instantly.
"""

from app.answer import verify_citations
from app.retrieval import SearchResult

PASSAGE_TEXT = (
    "6. Late Returns\n"
    "6.2 Grace period. Equipment returned no more than 59 minutes after the end of the Rental "
    "Period is treated as returned on time.\n"
    "6.3 Late charge. Equipment returned after the grace period is charged a late charge of 1.5 "
    "times the Daily Rate for each Rental Day, or part of a Rental Day, that the Equipment is late."
)


def make_passage(text: str = PASSAGE_TEXT, page: int | None = 3) -> SearchResult:
    return SearchResult(
        chunk_id="rental.pdf|p3|c1", text=text, source_file="rental.pdf", source_path="rental.pdf",
        page=page, heading="6. Late Returns", needed_ocr=False,
        vector_score=0.8, keyword_score=5.0, fused_score=0.03, matched_by="both",
    )


def test_a_real_quote_is_kept():
    kept = verify_citations(
        [{"source_id": "S1", "quote": "charged a late charge of 1.5 times the Daily Rate"}],
        [make_passage()],
    )
    assert len(kept) == 1
    assert kept[0].exact is True
    assert kept[0].page == 3
    assert kept[0].source_file == "rental.pdf"


def test_an_invented_quote_is_dropped():
    """The whole point: a sentence that is not in the document cannot be shown as a source."""
    kept = verify_citations(
        [{"source_id": "S1", "quote": "Late returns are charged at triple the daily rate plus a $200 penalty."}],
        [make_passage()],
    )
    assert kept == []


def test_a_quote_from_a_passage_that_was_never_supplied_is_dropped():
    kept = verify_citations([{"source_id": "S7", "quote": "6.2 Grace period."}], [make_passage()])
    assert kept == []


def test_small_differences_are_tolerated_but_the_document_wording_is_shown():
    """OCR slips and dropped punctuation should not cause a false refusal."""
    kept = verify_citations(
        [{"source_id": "S1", "quote": "charged a late charge of 15 times the Daily Rate for each Rental Day"}],
        [make_passage()],
    )
    assert len(kept) == 1
    assert kept[0].exact is False
    # What the user sees comes from the document, not from the model.
    assert "1.5 times the Daily Rate" in kept[0].quote


def test_the_same_line_is_not_cited_twice():
    quote = {"source_id": "S1", "quote": "charged a late charge of 1.5 times the Daily Rate"}
    assert len(verify_citations([quote, dict(quote)], [make_passage()])) == 1


def test_section_is_taken_from_the_heading_above_the_quote():
    """For files without pages, the citation must point at the right section."""
    text = "5.1 Vacation\nVacation accrues each pay period.\n5.2 Sick leave\nFull-time employees receive 6 paid sick days per calendar year."
    kept = verify_citations(
        [{"source_id": "S1", "quote": "receive 6 paid sick days per calendar year"}],
        [make_passage(text=text, page=None)],
    )
    assert kept[0].section == "5.2 Sick leave"
    assert kept[0].location == "5.2 Sick leave"


def test_an_empty_or_tiny_quote_is_dropped():
    assert verify_citations([{"source_id": "S1", "quote": ""}], [make_passage()]) == []
    assert verify_citations([{"source_id": "S1", "quote": "late"}], [make_passage()]) == []
