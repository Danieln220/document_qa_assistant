"""
Tests for how the evaluation scores a run.

The rule under test: a question that never reached the model is NOT a refusal.
Counting it as one made a completely broken run look like 100% correct refusals,
which is the worst kind of wrong number - a flattering one.
"""

import importlib.util
from pathlib import Path

# eval/ is a folder of scripts rather than a package, so load the file directly.
spec = importlib.util.spec_from_file_location(
    "run_eval", Path(__file__).resolve().parent.parent / "eval" / "run_eval.py"
)
run_eval = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_eval)


def row(**kwargs) -> dict:
    base = {"answerable": True, "answered": True, "grade": "correct", "retrieval_hit": True,
            "citation_ok": True, "citations": ["a.pdf (page 1)"], "best_score": 0.7}
    return {**base, **kwargs}


def test_unreached_questions_are_excluded_not_counted_as_refusals():
    rows = [
        row(),
        row(answerable=False, answered=False, grade="correct"),
        row(answered=False, grade="error"),                      # API failure
        row(answerable=False, answered=False, grade="error"),    # API failure
    ]
    stats = run_eval.summarise(rows)

    assert stats["errors"] == 2
    assert stats["complete"] is False
    # The failed ones must not inflate either side of the scorecard.
    assert stats["correct_refusals"] == 1     # not 2
    assert stats["false_refusals"] == 0       # not 1
    assert stats["answerable"] == 1 and stats["unanswerable"] == 1


def test_a_clean_run_is_marked_complete():
    stats = run_eval.summarise([row(), row(answerable=False, answered=False, grade="correct")])
    assert stats["complete"] is True
    assert stats["errors"] == 0


def test_a_genuine_false_refusal_is_still_counted():
    """Refusing a question the documents CAN answer must show up as a cost."""
    stats = run_eval.summarise([row(answered=False, grade="refused")])
    assert stats["false_refusals"] == 1
    assert stats["complete"] is True


def test_an_invented_answer_is_counted():
    """Answering a question the documents cannot answer is the failure that matters most."""
    stats = run_eval.summarise([row(answerable=False, answered=True, grade="incorrect")])
    assert stats["invented"] == 1
