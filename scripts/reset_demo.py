"""
Put the demo back to a clean state, ready to record again.

    .venv/bin/python scripts/reset_demo.py
    .venv/bin/python scripts/reset_demo.py --check    # say what would change, do nothing

What it does:
  1. Rebuilds the five Ridgeline documents from their text sources, so anything
     edited or deleted during a take comes back exactly as it was.
  2. Deletes the search index.
  3. Re-indexes from scratch.
  4. Checks the demo's own questions still work, so a take is never ruined by
     something that quietly broke.

It never touches `.env`, and it never deletes anything a client would own.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console  # noqa: E402

from app.config import PROJECT_ROOT, settings  # noqa: E402

console = Console()

# The demo's own beats. If any of these stop working, the recording is not worth
# starting, so the reset checks them rather than trusting they still hold.
DEMO_CHECKS = [
    ("A customer brought the mini excavator back two days late. What do we charge?",
     "answer", ["1,155", "35"]),
    ("How often do we change the hydraulic oil on the EX-35?",
     "answer", ["1,000"]),
    ("How much do we charge for a cracked cab window?",
     "answer", ["380"]),
    ("How many weeks of paid parental leave do employees get?",
     "refusal", []),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset the demo to a clean state.")
    parser.add_argument("--check", action="store_true", help="show what would happen, change nothing")
    parser.add_argument("--skip-questions", action="store_true",
                        help="don't ask the demo questions afterwards (saves free-tier tokens)")
    args = parser.parse_args()

    index_dir = settings.index_dir
    documents = sorted(settings.documents_dir.glob("*"))

    if args.check:
        console.print("[bold]Would do:[/bold]")
        console.print(f"  1. rebuild {len(list((PROJECT_ROOT / 'sample_data' / 'source').glob('*.md')))} "
                      f"demo documents into {settings.documents_dir}")
        console.print(f"  2. delete {index_dir} ({'exists' if index_dir.exists() else 'not there'})")
        console.print("  3. re-index everything")
        console.print(f"  4. ask {len(DEMO_CHECKS)} demo questions to confirm they still work")
        console.print(f"\nCurrently {len(documents)} files in documents/")
        return 0

    # --- 1. documents ------------------------------------------------------
    console.print("[bold]1. Rebuilding the demo documents[/bold]")
    _run([sys.executable, "scripts/generate_demo_docs.py"])

    # Anything else a take left behind (a file dragged in to show ingestion)
    # is removed, so the folder matches the script exactly.
    expected = {
        "Ridgeline_Rental_Agreement_2026.pdf", "Returns_and_Damages_Policy_scanned.pdf",
        "Fleet_Maintenance_Manual.pdf", "Employee_Handbook_2026.docx", "Branch_FAQ_and_Hours.txt",
    }
    for extra in settings.documents_dir.iterdir():
        if extra.name not in expected and not extra.name.startswith("."):
            console.print(f"   removing leftover file: [yellow]{extra.name}[/yellow]")
            extra.unlink() if extra.is_file() else shutil.rmtree(extra)

    # --- 2 & 3. index ------------------------------------------------------
    console.print("\n[bold]2. Deleting the index[/bold]")
    if index_dir.exists():
        shutil.rmtree(index_dir)
        console.print(f"   removed {index_dir}")
    else:
        console.print("   nothing to remove")

    console.print("\n[bold]3. Indexing from scratch[/bold]")
    _run([sys.executable, "scripts/ingest.py"])

    # --- 4. the demo's own questions --------------------------------------
    if args.skip_questions:
        console.print("\n[dim]Skipping the demo questions (--skip-questions).[/dim]")
        console.print("\n[bold green]Ready to record.[/bold green]")
        return 0

    console.print("\n[bold]4. Checking the demo questions[/bold]")
    from app.answer import answer  # imported here so --check stays instant

    failures = 0
    for question, expected_kind, must_contain in DEMO_CHECKS:
        result = answer(question)
        if expected_kind == "refusal":
            ok = not result.answered
            detail = "refused" if ok else f"ANSWERED (should refuse): {result.text[:60]}"
        else:
            missing = [m for m in must_contain if m not in result.text]
            ok = result.answered and not missing
            detail = (f"answered, {len(result.citations)} source(s)" if ok
                      else f"missing {missing}" if result.answered else f"refused ({result.reason})")
        failures += 0 if ok else 1
        console.print(f"   [{'green' if ok else 'red'}]{'OK ' if ok else 'BAD'}[/] {question[:58]:<60} {detail}")

    if failures:
        console.print(f"\n[bold red]{failures} demo question(s) did not behave as scripted.[/bold red]")
        console.print("Check DEMO.md before recording; the script expects these answers.")
        return 1

    console.print("\n[bold green]Ready to record.[/bold green] "
                  "Start the web chat with: .venv/bin/uvicorn app.web:api --port 8000")
    return 0


def _run(command: list[str]) -> None:
    """Run one of the project's own scripts, showing only its last lines."""
    finished = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True)
    for line in finished.stdout.strip().splitlines()[-6:]:
        console.print(f"   {line}")
    if finished.returncode != 0:
        console.print(f"[red]{finished.stderr.strip()[-400:]}[/red]")
        raise SystemExit(finished.returncode)


if __name__ == "__main__":
    sys.exit(main())
