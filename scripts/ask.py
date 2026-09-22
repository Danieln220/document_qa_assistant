"""
Ask a question from the command line.

    .venv/bin/python scripts/ask.py "how much do we charge for a late return?"
    .venv/bin/python scripts/ask.py            # then type questions, one per line

The same `answer()` function powers the web chat and the Telegram bot, so what
you see here is what they will show.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console  # noqa: E402

from app.answer import Answer, answer  # noqa: E402

console = Console()


def show(result: Answer) -> None:
    if result.answered:
        console.print(f"\n[bold green]Answer[/bold green]  [dim]({result.seconds:.1f}s, {result.model})[/dim]")
        console.print(result.text)
        console.print("\n[bold]Sources[/bold]")
        for c in result.citations:
            flags = []
            if c.needed_ocr:
                flags.append("read by OCR")
            if not c.exact:
                flags.append("close match")
            note = f"  [dim]({', '.join(flags)})[/dim]" if flags else ""
            console.print(f"  [cyan]{c.source_file}[/cyan], {c.location}{note}")
            console.print(f'    "{c.quote}"')
    else:
        console.print(f"\n[bold yellow]No answer[/bold yellow]  [dim]({result.reason}, "
                      f"best match {result.best_score:.2f}, {result.seconds:.1f}s)[/dim]")
        console.print(result.text)
    console.print()


def main() -> int:
    if len(sys.argv) > 1:
        show(answer(" ".join(sys.argv[1:])))
        return 0

    console.print("Type a question, or press Ctrl-C to quit.")
    try:
        while True:
            question = console.input("\n[bold]> [/bold]").strip()
            if question:
                show(answer(question))
    except (KeyboardInterrupt, EOFError):
        console.print("\nBye.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
