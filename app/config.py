"""
All settings for the assistant, in one place.

Values come from the `.env` file in the project root (see `.env.example`).
Every other module imports `settings` from here instead of reading
environment variables itself, so there is exactly one place to look when
something needs changing for a new client.
"""

from dataclasses import dataclass, field
from pathlib import Path
import os

from dotenv import load_dotenv

# Project root = the folder that contains `app/`. Resolved from this file's
# location so scripts work no matter which directory you run them from.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load `.env` into the process environment. `override=False` means a value
# already set in the real environment wins, which is handy on servers/Docker.
load_dotenv(PROJECT_ROOT / ".env", override=False)

# Chroma sends anonymous usage stats by default. A client's document assistant
# should not phone home, so switch it off before chromadb is ever imported.
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")


def _env(name: str, default: str = "") -> str:
    """Read one setting, trimming stray spaces people paste into .env files."""
    return os.getenv(name, default).strip()


def _env_int_list(name: str) -> list[int]:
    """Read a comma-separated list of numbers, e.g. '12345,67890' -> [12345, 67890]."""
    raw = _env(name)
    return [int(part) for part in raw.split(",") if part.strip()]


@dataclass(frozen=True)
class Settings:
    # --- Company shown in the UI and in refusal messages ---
    company_name: str = field(default_factory=lambda: _env("COMPANY_NAME", "Ridgeline Equipment Rentals"))

    # --- Where things live on disk ---
    documents_dir: Path = field(default_factory=lambda: PROJECT_ROOT / _env("DOCUMENTS_DIR", "documents"))
    index_dir: Path = field(default_factory=lambda: PROJECT_ROOT / _env("INDEX_DIR", "index"))

    # --- Local embedding model (downloaded once, then runs offline) ---
    embedding_model: str = field(default_factory=lambda: _env("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"))

    # --- Answer generation ---
    # Which provider answers questions: "groq" (the default: 200,000 tokens a
    # day, fast and steady) or "gemini" (fallback: only 20 requests a day per
    # model, and often busy). Measured limits: docs/costs-and-limits.md.
    llm_provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "groq").lower())

    gemini_api_key: str = field(default_factory=lambda: _env("GEMINI_API_KEY"))
    gemini_model: str = field(default_factory=lambda: _env("GEMINI_MODEL", "gemini-3.6-flash"))

    groq_api_key: str = field(default_factory=lambda: _env("GROQ_API_KEY"))
    # Chosen at milestone M5 from Groq's live model list; kept in .env so a
    # retired model can be swapped without touching code.
    groq_model: str = field(default_factory=lambda: _env("GROQ_MODEL"))
    # How much internal reasoning the model does before answering. "low" is the
    # default because it is noticeably faster on screen and, on this grounded
    # task, just as accurate: the thinking that matters is quoting correctly.
    groq_reasoning_effort: str = field(default_factory=lambda: _env("GROQ_REASONING_EFFORT", "low"))

    # --- Retrieval tuning ---
    # How many chunks the LLM gets to read for each question. Four keeps a
    # question near 2,000 tokens, which matters on Groq's free tier: it allows
    # 8,000 tokens per minute, so this is roughly four questions a minute.
    top_k: int = field(default_factory=lambda: int(_env("TOP_K", "4")))
    # Gate 1: if the best search match scores below this, refuse without
    # calling the LLM. Tuned against the eval set at milestone M6.
    relevance_threshold: float = field(default_factory=lambda: float(_env("RELEVANCE_THRESHOLD", "0.5")))

    # --- The owner's screen ---
    # Every question is recorded locally so the owner can see what staff ask and,
    # more usefully, which questions the documents could not answer. Set to
    # false for a client who would rather nothing were logged.
    log_questions: bool = field(default_factory=lambda: _env("LOG_QUESTIONS", "true").lower() != "false")
    # If set, the owner's page asks for this password. Leave empty on a laptop;
    # set it before the assistant is reachable by anyone else.
    admin_password: str = field(default_factory=lambda: _env("ADMIN_PASSWORD"))
    # Largest document that may be uploaded through the browser, in megabytes.
    max_upload_mb: int = field(default_factory=lambda: int(_env("MAX_UPLOAD_MB", "40")))

    # --- Telegram ---
    telegram_bot_token: str = field(default_factory=lambda: _env("TELEGRAM_BOT_TOKEN"))
    # Only these chat IDs may use the bot, so strangers can't query company documents.
    telegram_allowed_chat_ids: list[int] = field(default_factory=lambda: _env_int_list("TELEGRAM_ALLOWED_CHAT_IDS"))


# The single shared instance every module imports.
settings = Settings()
