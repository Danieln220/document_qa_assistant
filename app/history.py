"""
A record of what staff asked.

Two reasons this exists, and the second is the valuable one:

1. The owner can see the assistant is being used, and for what.
2. **Every refused question is a gap in the documents.** "What's our parental
   leave policy?" asked eleven times is not an AI problem; it is a missing page
   in the handbook. That list is worth more to a business than the answers.

Stored in a small SQLite file next to the index. Nothing leaves the machine, and
logging can be switched off entirely with LOG_QUESTIONS=false in `.env`.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from app.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    asked_at   TEXT    NOT NULL,
    question   TEXT    NOT NULL,
    answered   INTEGER NOT NULL,   -- 1 answered, 0 refused
    reason     TEXT    NOT NULL,   -- why it refused, empty when answered
    sources    TEXT    NOT NULL,   -- documents cited, comma separated
    channel    TEXT    NOT NULL,   -- "web" or "telegram"
    seconds    REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS questions_asked_at ON questions (asked_at);
"""


def _database_path() -> Path:
    settings.index_dir.mkdir(parents=True, exist_ok=True)
    return settings.index_dir / "questions.db"


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(_database_path())
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    return connection


def record(question: str, answered: bool, reason: str, sources: list[str],
           channel: str, seconds: float) -> None:
    """
    Save one question. Never raises: a logging problem must not stop an answer
    from reaching the person who asked.
    """
    if not settings.log_questions:
        return
    try:
        with closing(_connect()) as connection, connection:
            connection.execute(
                "INSERT INTO questions (asked_at, question, answered, reason, sources, channel, seconds)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (datetime.now().isoformat(timespec="seconds"), question.strip(), int(answered),
                 reason or "", ", ".join(sources), channel, round(seconds, 2)),
            )
    except Exception as exc:
        print(f"[history] could not record the question: {exc}")


def recent(limit: int = 100, only_unanswered: bool = False) -> list[dict]:
    """The most recent questions, newest first."""
    where = "WHERE answered = 0" if only_unanswered else ""
    try:
        with closing(_connect()) as connection:
            rows = connection.execute(
                f"SELECT * FROM questions {where} ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(row) for row in rows]
    except Exception as exc:
        print(f"[history] could not read the log: {exc}")
        return []


def summary(days: int = 30) -> dict:
    """
    Counts for the owner's screen, plus the gap list: the questions the documents
    could not answer, most recent first.
    """
    since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    try:
        with closing(_connect()) as connection:
            total = connection.execute(
                "SELECT COUNT(*) FROM questions WHERE asked_at >= ?", (since,)).fetchone()[0]
            unanswered = connection.execute(
                "SELECT COUNT(*) FROM questions WHERE asked_at >= ? AND answered = 0", (since,)).fetchone()[0]
            # Same question asked repeatedly is the strongest signal of a gap,
            # so identical wording is grouped and counted.
            gaps = connection.execute(
                "SELECT question, COUNT(*) AS times, MAX(asked_at) AS last_asked"
                " FROM questions WHERE asked_at >= ? AND answered = 0"
                " GROUP BY LOWER(TRIM(question)) ORDER BY times DESC, last_asked DESC LIMIT 20",
                (since,)).fetchall()
            return {
                "days": days,
                "total": total,
                "answered": total - unanswered,
                "unanswered": unanswered,
                "gaps": [dict(row) for row in gaps],
            }
    except Exception as exc:
        print(f"[history] could not summarise: {exc}")
        return {"days": days, "total": 0, "answered": 0, "unanswered": 0, "gaps": []}
