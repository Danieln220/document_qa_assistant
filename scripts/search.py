"""
Try the search on its own, without the LLM.

    .venv/bin/python scripts/search.py "how much is the late return fee?"
    .venv/bin/python scripts/search.py "EX-35 hydraulic oil" --k 3 --full

Useful when an answer looks wrong: it shows whether the right passage was found
at all (a retrieval problem) or was found but answered badly (a prompt problem).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console  # noqa: E402
from rich.table import Table  # noqa: E402

from app.retrieval import best_vector_score, search  # noqa: E402

console = Console()


def main() -> int:
    parser = argparse.ArgumentParser(description="Search the indexed documents.")
    parser.add_argument("question", help="what to search for")
    parser.add_argument("--k", type=int, default=6, help="how many passages to show")
    parser.add_argument("--full", action="store_true", help="print the whole passage, not a snippet")
    args = parser.parse_args()

    results = search(args.question, top_k=args.k)
    if not results:
        console.print("[red]Nothing found. Is the index empty? Run scripts/ingest.py first.[/red]")
        return 1

    table = Table(title=f'Results for: "{args.question}"', title_justify="left")
    table.add_column("#", justify="right")
    table.add_column("Document")
    table.add_column("Where")
    table.add_column("Matched by")
    table.add_column("Meaning", justify="right")
    table.add_column("Keyword", justify="right")
    for i, r in enumerate(results, start=1):
        table.add_row(
            str(i),
            r.source_file + (" [dim](OCR)[/dim]" if r.needed_ocr else ""),
            r.location,
            r.matched_by,
            f"{r.vector_score:.2f}",
            f"{r.keyword_score:.1f}",
        )
    console.print(table)
    console.print(f"Best match on meaning: [bold]{best_vector_score(results):.2f}[/bold] "
                  f"(the refusal gate compares this with RELEVANCE_THRESHOLD)\n")

    for i, r in enumerate(results, start=1):
        text = r.text if args.full else r.text[:300] + ("..." if len(r.text) > 300 else "")
        console.print(f"[cyan]{i}. {r.chunk_id}[/cyan]  ({r.location})")
        console.print(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
