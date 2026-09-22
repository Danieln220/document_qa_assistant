"""
Tests for the keyword side of search.

These run without the index or the embedding model: they check the tokenizer,
which is what decides whether an exact code like "EX-35" can be matched at all.
"""

from app.retrieval import _tokenize


def test_equipment_codes_stay_in_one_piece():
    """Splitting "EX-35" into "ex" and "35" would make every model code match every other."""
    assert "ex-35" in _tokenize("The EX-35 mini excavator")
    assert "a92.22" in _tokenize("annual inspection under ANSI A92.22")
    assert "rer-ops-014" in _tokenize("Document RER-OPS-014, Revision 4")
    assert "24/7" in _tokenize("call the 24/7 breakdown line")


def test_tokens_are_lowercased_so_case_does_not_matter():
    assert _tokenize("Late Returns") == _tokenize("late returns")


def test_punctuation_and_symbols_are_dropped():
    tokens = _tokenize("a cleaning fee of $150 applies (per item).")
    assert "150" in tokens
    assert "$150" not in tokens
    assert "(per" not in tokens
