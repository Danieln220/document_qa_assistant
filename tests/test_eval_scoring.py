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


# ---------------------------------------------------------------------------
# --no-judge must not look like a run where every answer was wrong
# ---------------------------------------------------------------------------

def test_ungraded_answers_are_not_counted_as_incorrect():
    """
    With --no-judge nothing grades the answers, so correctness is unknown, not zero.

    Counting ungraded answers against the score printed "0/15 correct" for a run
    in which every answer was in fact right - a broken-looking number for a
    working assistant, which is how this was first reported.
    """
    rows = [row(grade="ungraded") for _ in range(15)]
    rows += [row(answerable=False, answered=False, grade="correct") for _ in range(5)]
    stats = run_eval.summarise(rows)

    assert stats["graded"] == 0          # nothing was judged
    assert stats["correct"] == 0
    assert stats["incorrect"] == 0       # and nothing counted against it
    assert stats["complete"] is True     # an unjudged run is not a broken run
    assert stats["false_refusals"] == 0


def test_ungraded_answers_do_not_dilute_a_partial_judge_run():
    """Correctness is reported over what was actually graded, not over all answerable."""
    rows = [row(grade="correct"), row(grade="ungraded"), row(grade="ungraded")]
    stats = run_eval.summarise(rows)
    assert stats["graded"] == 1
    assert stats["correct"] == 1


# ---------------------------------------------------------------------------
# --threshold-scan must survive a subset that has only one kind of question
# ---------------------------------------------------------------------------

def test_threshold_scan_survives_answerable_only_subset():
    """`--only <answerable ids> --threshold-scan` used to die with IndexError."""
    run_eval.threshold_scan([row(best_score=0.72)])


def test_threshold_scan_survives_unanswerable_only_subset():
    run_eval.threshold_scan([row(answerable=False, answered=False, best_score=0.55)])


def test_threshold_scan_survives_empty_rows():
    run_eval.threshold_scan([])


# ---------------------------------------------------------------------------
# An untested category must not read as a failure
# ---------------------------------------------------------------------------

def test_an_empty_category_says_not_tested_rather_than_zero_percent():
    """
    A run limited to answerable questions once reported
    "unanswerable correctly refused: 0/1 (0%)" - a failing-looking number for
    something that was never asked. The guard against dividing by zero had
    invented the denominator.
    """
    assert run_eval.score_line(0, 0) == "not tested"
    assert run_eval.score_line(3, 5) == "3/5 (60%)"
    assert run_eval.score_line(5, 5) == "5/5 (100%)"
