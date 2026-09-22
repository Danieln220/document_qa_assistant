"""
Index the documents folder.

    .venv/bin/python scripts/ingest.py           # only what changed
    .venv/bin/python scripts/ingest.py --force   # re-read everything
    .venv/bin/python scripts/ingest.py --show 3  # also print 3 example chunks

Run it after adding, replacing or deleting a document. It is safe to run at any
time: unchanged documents are skipped, so a second run takes about a second.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console  # noqa: E402
from rich.table import Table  # noqa: E402

from app.config import settings  # noqa: E402
from app.index import all_chunks, index_stats, ingest  # noqa: E402

console = Console()


def main() -> int:
    parser = argparse.ArgumentParser(description="Index the documents folder.")
    parser.add_argument("--force", action="store_true", help="re-read every document, even unchanged ones")
    parser.add_argument("--show", type=int, default=0, metavar="N", help="print N example chunks afterwards")
    args = parser.parse_args()

    console.print(f"Documents: [bold]{settings.documents_dir}[/bold]")
    console.print(f"Index:     [bold]{settings.index_dir}[/bold]\n")

    started = time.time()
    results = ingest(force=args.force)
    elapsed = time.time() - started

    table = Table(title="Ingestion result", title_justify="left")
    table.add_column("Document")
    table.add_column("Action")
    table.add_column("Pages", justify="right")
    table.add_column("OCR pages", justify="right")
    table.add_column("Chunks", justify="right")
    colours = {"added": "green", "updated": "yellow", "unchanged": "dim", "removed": "red", "failed": "bold red"}
    for r in results:
        table.add_row(
            r.name,
            f"[{colours.get(r.action, 'white')}]{r.action}[/]" + (f" ({r.note})" if r.note else ""),
            str(r.pages or "-"),
            str(r.ocr_pages or "-"),
            str(r.chunks or "-"),
        )
    console.print(table)

    counts = {a: sum(1 for r in results if r.action == a) for a in
              ("added", "updated", "unchanged", "removed", "failed")}
    stats = index_stats()
    console.print(
        f"\n{counts['added']} added, {counts['updated']} updated, {counts['unchanged']} unchanged, "
        f"{counts['removed']} removed, {counts['failed']} failed "
        f"in {elapsed:.1f}s"
    )
    console.print(f"Index now holds [bold]{stats['chunks']}[/bold] chunks from "
                  f"[bold]{stats['documents']}[/bold] documents.")

    if args.show:
        console.print("\n[bold]Example chunks[/bold]")
        for chunk in all_chunks()[: args.show]:
            page = chunk["page"]
            where = f"page {page}" if page != -1 else (chunk["heading"] or "start of document")
            console.print(
                f"\n[cyan]{chunk['chunk_id']}[/cyan]  "
                f"({chunk['source_file']}, {where}, OCR={chunk['needed_ocr']})\n"
                f"{chunk['text'][:400]}{'...' if len(chunk['text']) > 400 else ''}"
            )

    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
