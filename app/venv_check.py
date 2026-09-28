"""
A friendly message when a script is run with the wrong Python.

Every script here needs the project's virtual environment. Run one with the
system Python and you get `ModuleNotFoundError: No module named 'rich'`, which
says nothing about the real problem or the fix.

This module uses only the standard library, so it can be imported before
anything that would fail.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"


def ensure_venv() -> None:
    """Stop with an explanation if this is not the project's Python."""
    # `sys.prefix` points at the virtual environment when one is in use.
    if Path(sys.prefix).resolve() == (PROJECT_ROOT / ".venv").resolve():
        return

    script = Path(sys.argv[0]).name if sys.argv else "the script"
    print(f"This needs the project's Python, not {sys.executable}.\n")

    if VENV_PYTHON.exists():
        print("Run it like this:\n")
        print(f"    .venv/bin/python {sys.argv[0] if sys.argv else script}\n")
    else:
        print("The environment is not set up yet. From the project folder:\n")
        print("    python3.12 -m venv .venv")
        print("    .venv/bin/python -m pip install -r requirements.txt\n")

    sys.exit(1)
