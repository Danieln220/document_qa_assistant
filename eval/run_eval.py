"""
Run the evaluation set and print the scorecard.

    .venv/bin/python eval/run_eval.py                # full run, saves a report
    .venv/bin/python eval/run_eval.py --no-judge     # skip the LLM judge (faster, fewer tokens)
    .venv/bin/python eval/run_eval.py --only late-return,sick-days
    .venv/bin/python eval/run_eval.py --threshold-scan   # what different refusal thresholds would do

Four numbers are measured:

  Retrieval hit rate   Did the search find the document that holds the answer?
                       If this is low, no prompt can save the answer.
  Answer correctness   Does the answer actually say what the document says?
                       Graded by a second LLM call against the expected answer.
  Correct refusals     Of the questions the documents cannot answer, how many did
                       the assistant refuse? This is the trust number.
  False refusals       Answerable questions it refused anyway. The cost of being
                       careful, and the number to watch when tightening the gates.

A full run makes about 35 model calls and takes a few minutes: the assistant
waits out rate limits and busy providers rather than failing. Questions that
never reach the model are reported separately and excluded from every score -
a run with errors is marked incomplete rather than quietly scored.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.table import Table  # noqa: E402

from app.answer import answer  # noqa: E402
from app.config import settings  # noqa: E402
from app.llm import chat_json, describe_model  # noqa: E402
from app.retrieval import search  # noqa: E402

console = Console()
QUESTIONS_PATH = Path(__file__).parent / "questions.yaml"
RESULTS_DIR = Path(__file__).parent / "results"

JUDGE_PROMPT = """You are grading a document assistant's answer against the expected answer.

QUESTION: {question}
EXPECTED: {expected}
ASSISTANT SAID: {actual}

Grade how well the assistant's answer matches the expected one on the facts that matter
(figures, rules, conditions). Ignore wording, length and politeness. A missing figure or a
wrong number is "incorrect". Getting the main fact right but omitting a secondary one is "partial".

Reply with JSON only: {{"grade": "correct" | "partial" | "incorrect", "why": "one short sentence"}}"""


def judge(question: str, expected: str, actual: str) -> dict:
    """Ask the model to grade one answer. Kept short and cheap on purpose."""
    try:
        return chat_json(
            system="You grade answers strictly and reply with JSON only.",
            user=JUDGE_PROMPT.format(question=question, expected=expected, actual=actual),
            max_tokens=300,
        )
    except Exception as exc:
        return {"grade": "error", "why": str(exc)[:80]}


def preflight() -> str:
    """
    Check the provider will actually answer before asking 20 questions.

    A full run takes 10 to 25 minutes, so discovering on question 6 that the
    daily budget is gone wastes the wait and produces an incomplete report.
    One tiny call up front turns that into an instant, clear message.
    Returns an empty string when all is well, or the reason to stop.
    """
    try:
        chat_json(system="Reply with JSON only.", user='Reply with {"ok": true}', max_tokens=50)
        return ""
    except Exception as exc:
        text = str(exc)
        if "tokens per day" in text or "PerDay" in text or "RESOURCE_EXHAUSTED" in text:
            return ("the provider's daily free quota is used up. Wait for it to refill, or switch "
                    "LLM_PROVIDER in .env (see docs/costs-and-limits.md).")
        return f"the provider is not answering: {text[:160]}"


def run(questions: list[dict], use_judge: bool) -> list[dict]:
    """Ask every question and collect what happened."""
    rows: list[dict] = []

    for index, item in enumerate(questions, start=1):
        console.print(f"[dim]{index}/{len(questions)}[/dim] {item['question']}")
        result = answer(item["question"])

        # Retrieval is checked separately from the answer: a question can be
        # refused even though the right passage was found, and the two failures
        # need different fixes.
        retrieved = {p.source_file for p in search(item["question"])}
        expected_sources = set(item.get("sources") or [])
        retrieval_hit = bool(expected_sources & retrieved) if expected_sources else None
        cited = {c.source_file for c in result.citations}
        citation_ok = bool(expected_sources & cited) if (expected_sources and cited) else None

        row = {
            "id": item["id"],
            "question": item["question"],
            "answerable": item["answerable"],
            "expected": item["expected"].strip(),
            "answered": result.answered,
            "text": result.text,
            "reason": result.reason,
            "best_score": result.best_score,
            "seconds": result.seconds,
            "citations": [f"{c.source_file} ({c.location})" for c in result.citations],
            "retrieval_hit": retrieval_hit,
            "citation_ok": citation_ok,
            "grade": None,
            "why": "",
        }

        # An API failure is NOT a refusal. Counting it as one would make a broken
        # run look either careful (unanswerable questions "refused") or careless
        # (answerable ones "falsely refused"). It is excluded from the scores and
        # the run is reported as incomplete.
        if result.reason == "error":
            row["grade"] = "error"
            row["why"] = "the model could not be reached"
        elif item["answerable"]:
            if not result.answered:
                row["grade"] = "refused"       # a genuine false refusal
                row["why"] = result.reason
            elif use_judge:
                verdict = judge(item["question"], item["expected"], result.text)
                row["grade"] = verdict.get("grade", "error")
                row["why"] = verdict.get("why", "")
            else:
                # --no-judge: the answer arrived but nothing graded it. That is
                # unknown correctness, not zero, so it gets its own grade and is
                # scored over the judged questions only (see summarise).
                row["grade"] = "ungraded"
                row["why"] = "judging skipped (--no-judge)"
        else:
            # For unanswerable questions, refusing IS the correct behaviour.
            row["grade"] = "correct"
            row["why"] = "refused as expected"

        rows.append(row)
    return rows


def summarise(rows: list[dict]) -> dict:
    # Questions that failed to reach the model are set aside entirely: a score
    # calculated over them would be a guess dressed up as a measurement.
    errors = [r for r in rows if r["grade"] == "error"]
    usable = [r for r in rows if r["grade"] != "error"]
    answerable = [r for r in usable if r["answerable"]]
    unanswerable = [r for r in usable if not r["answerable"]]
    graded = [r for r in answerable if r["grade"] in ("correct", "partial", "incorrect")]
    return {
        "total": len(rows),
        "errors": len(errors),
        "complete": not errors,
        "answerable": len(answerable),
        "unanswerable": len(unanswerable),
        # Correctness is a fraction of what the judge actually saw. With
        # --no-judge this is 0 and the correctness line is suppressed rather
        # than printed as 0/15, which reads as "every answer was wrong".
        "graded": len(graded),
        "retrieval_hits": sum(1 for r in answerable if r["retrieval_hit"]),
        "correct": sum(1 for r in graded if r["grade"] == "correct"),
        "partial": sum(1 for r in graded if r["grade"] == "partial"),
        "incorrect": sum(1 for r in graded if r["grade"] == "incorrect"),
        "false_refusals": sum(1 for r in answerable if r["grade"] == "refused"),
        "correct_refusals": sum(1 for r in unanswerable if not r["answered"]),
        "invented": sum(1 for r in unanswerable if r["answered"]),
        "citations_on_target": sum(1 for r in answerable if r["citation_ok"]),
        "cited_anything": sum(1 for r in answerable if r["citations"]),
    }


def print_report(rows: list[dict], stats: dict, elapsed: float) -> None:
    table = Table(title="Evaluation results", title_justify="left")
    table.add_column("Question")
    table.add_column("Type")
    table.add_column("Found doc")
    table.add_column("Result")
    table.add_column("Score", justify="right")
    marks = {"correct": "[green]correct[/green]", "partial": "[yellow]partial[/yellow]",
             "incorrect": "[red]incorrect[/red]", "refused": "[red]refused (false)[/red]",
             "error": "[red]not reached[/red]", "ungraded": "[dim]answered, not graded[/dim]"}
    for r in rows:
        found = "-" if r["retrieval_hit"] is None else ("yes" if r["retrieval_hit"] else "[red]no[/red]")
        table.add_row(
            r["id"],
            "answerable" if r["answerable"] else "must refuse",
            found,
            marks.get(r["grade"], r["grade"] or "-"),
            f"{r['best_score']:.2f}",
        )
    console.print(table)

    if not stats["complete"]:
        console.print(f"\n[bold red]INCOMPLETE RUN: {stats['errors']} of {stats['total']} questions never "
                      f"reached the model.[/bold red] They are excluded below, so these numbers describe "
                      f"only the questions that ran. Re-run when the provider is available.")

    a, u = stats["answerable"], stats["unanswerable"]
    if not a and not u:
        console.print("\n[yellow]Nothing to score: no question reached the model.[/yellow]")
        return

    # A run limited to some questions (--only) legitimately has an empty
    # category. Those lines read "not tested" rather than a 0% that looks
    # like a failure.
    graded = stats["graded"]
    correctness = (f"{stats['correct']}/{graded} correct, {stats['partial']} partial, "
                   f"{stats['incorrect']} incorrect") if graded else \
        "[dim]not measured - the judge was skipped (--no-judge)[/dim]"
    console.print(f"""
[bold]Scorecard[/bold]
  Retrieval hit rate    {score_line(stats['retrieval_hits'], a):<14} the right document was found
  Answer correctness    {correctness}
  Correct refusals      {score_line(stats['correct_refusals'], u):<14} questions the documents cannot answer
  Invented answers      {str(stats['invented']) + '/' + str(u) if u else 'not tested':<14} answered something that is not in the documents
  False refusals        {str(stats['false_refusals']) + '/' + str(a) if a else 'not tested':<14} answerable questions it refused anyway
  Citations on target   {str(stats['citations_on_target']) + '/' + str(a) if a else 'not tested':<14} cited the expected document
  Run time              {elapsed:.0f}s for {stats['total']} questions"""
                  + (f"\n  Not reached           {stats['errors']} (excluded from every number above)"
                     if stats["errors"] else ""))


def score_line(count: int, total: int) -> str:
    """
    "3/5 (60%)", or "not tested" when the category had no questions.

    Without this, a run limited to answerable questions reported
    "unanswerable correctly refused: 0/1 (0%)" - a failing-looking number for
    something that was never asked.
    """
    if total <= 0:
        return "not tested"
    return f"{count}/{total} ({count / total:.0%})"


def save_report(rows: list[dict], stats: dict, elapsed: float) -> Path:
    """Write a Markdown report, handy to show on a sales call."""
    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    path = RESULTS_DIR / f"eval_{stamp}.md"
    a = stats["answerable"]
    u = stats["unanswerable"]

    lines = [
        f"# Evaluation run {stamp}",
        "",
        "" if stats["complete"] else
        f"> **Incomplete run.** {stats['errors']} of {stats['total']} questions never reached the "
        f"model (provider unavailable or out of quota) and are excluded from the numbers below.\n",
        f"Model `{describe_model()}` | passages per question: {settings.top_k} | "
        f"refusal threshold: {settings.relevance_threshold} | run time {elapsed:.0f}s",
        "",
        "| Measure | Result |",
        "|---|---|",
        f"| Retrieval hit rate | {score_line(stats['retrieval_hits'], a)} |",
        f"| Answers correct | {stats['correct']}/{stats['graded']} (plus {stats['partial']} partial) |"
        if stats["graded"] else "| Answers correct | not measured (judge skipped) |",
        f"| Unanswerable questions correctly refused | {score_line(stats['correct_refusals'], u)} |",
        f"| Invented answers | {stats['invented']}/{u} |" if u else "| Invented answers | not tested |",
        f"| False refusals | {stats['false_refusals']}/{a} |" if a else "| False refusals | not tested |",
        "",
        "## Question by question",
        "",
    ]
    for r in rows:
        lines += [
            f"### {r['id']} - {'answerable' if r['answerable'] else 'must refuse'} - **{r['grade']}**",
            "",
            f"*Q:* {r['question']}",
            "",
            f"*Expected:* {r['expected']}",
            "",
            f"*Assistant:* {r['text']}",
            "",
        ]
        if r["citations"]:
            lines += ["*Cited:* " + "; ".join(r["citations"]), ""]
        if r["why"]:
            lines += [f"*Grader:* {r['why']}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def threshold_scan(rows: list[dict]) -> None:
    """
    Show what different values of RELEVANCE_THRESHOLD would have done.

    Gate 1 refuses before the LLM runs when the best match is below the
    threshold. Raising it blocks more unanswerable questions early, but starts
    blocking real ones too. This table is how the setting gets chosen.
    """
    table = Table(title="What each refusal threshold would do", title_justify="left")
    table.add_column("Threshold", justify="right")
    table.add_column("Unanswerable blocked early", justify="right")
    table.add_column("Answerable wrongly blocked", justify="right")
    for threshold in [round(0.30 + 0.05 * i, 2) for i in range(11)]:
        blocked_bad = sum(1 for r in rows if not r["answerable"] and r["best_score"] < threshold)
        blocked_good = sum(1 for r in rows if r["answerable"] and r["best_score"] < threshold)
        table.add_row(f"{threshold:.2f}", f"{blocked_bad}",
                      f"[red]{blocked_good}[/red]" if blocked_good else "0")
    console.print(table)
    # --only can select questions of one kind, so either list may be empty.
    # The range line is a footnote to the table above; a missing half is worth
    # a word, never worth losing the run's report to an IndexError.
    scores_bad = sorted(r["best_score"] for r in rows if not r["answerable"])
    scores_good = sorted(r["best_score"] for r in rows if r["answerable"])

    def span(scores: list[float], label: str) -> str:
        if not scores:
            return f"{label}: none in this run"
        return f"{label}: {scores[0]:.2f} to {scores[-1]:.2f}"

    console.print(f"Best-match scores - {span(scores_good, 'answerable')}, "
                  f"{span(scores_bad, 'unanswerable')}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the evaluation set.")
    parser.add_argument("--no-judge", action="store_true", help="skip the LLM grading step")
    parser.add_argument("--only", default="", help="comma-separated question ids to run")
    parser.add_argument("--threshold-scan", action="store_true", help="also show the threshold table")
    args = parser.parse_args()

    questions = yaml.safe_load(QUESTIONS_PATH.read_text(encoding="utf-8"))["questions"]
    if args.only:
        wanted = {q.strip() for q in args.only.split(",")}
        questions = [q for q in questions if q["id"] in wanted]

    console.print(f"Model [bold]{describe_model()}[/bold], {settings.top_k} passages per question, "
                  f"refusal threshold {settings.relevance_threshold}")

    problem = preflight()
    if problem:
        console.print(f"\n[bold red]Not starting:[/bold red] {problem}")
        return 2
    console.print("[dim]Provider responding. This takes 10-25 minutes on a free tier.[/dim]\n")

    started = time.time()
    rows = run(questions, use_judge=not args.no_judge)
    elapsed = time.time() - started

    stats = summarise(rows)
    console.print()
    print_report(rows, stats, elapsed)
    if args.threshold_scan:
        console.print()
        threshold_scan(rows)
    path = save_report(rows, stats, elapsed)
    console.print(f"\nFull report saved to [bold]{path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path}[/bold]")

    # Non-zero exit when an answer was invented, or when the run did not finish:
    # in both cases the scorecard must not be quoted as a result.
    return 1 if (stats["invented"] or not stats["complete"]) else 0


if __name__ == "__main__":
    sys.exit(main())
