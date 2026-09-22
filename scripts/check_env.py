"""
Environment check: run this first on any new machine.

    .venv/bin/python scripts/check_env.py

It confirms that:
  1. every Python library we depend on imports, and prints its version;
  2. the Tesseract OCR program is installed and can read a test image;
  3. the local embedding model downloads (first run only) and produces vectors;
  4. which settings in `.env` are filled in. It prints SET / MISSING only,
     never the values, so secrets never end up on screen or in a log.
"""

import importlib.metadata as md
import platform
import sys
from pathlib import Path

# Make `app` importable when this script is run directly from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import PROJECT_ROOT, settings  # noqa: E402

# Pip package names whose installed version we want to report.
PACKAGES = [
    "pymupdf", "pytesseract", "pillow", "python-docx",
    "sentence-transformers", "torch", "chromadb", "rank-bm25", "rapidfuzz",
    "groq", "google-genai", "fastapi", "uvicorn", "python-telegram-bot",
    "python-dotenv", "pyyaml", "rich", "reportlab", "pytest",
]

# Settings that have to be filled in `.env`, and what each one is for. Only the
# key for the provider in use is required; the other is an optional fallback.
REQUIRED_ENV = {
    "GROQ_API_KEY": "answering, when LLM_PROVIDER=groq",
    "GROQ_MODEL": "answering, when LLM_PROVIDER=groq",
    "GEMINI_API_KEY": "answering, when LLM_PROVIDER=gemini",
    "TELEGRAM_BOT_TOKEN": "the Telegram bot",
    "TELEGRAM_ALLOWED_CHAT_IDS": "who may use the Telegram bot",
}

problems = 0  # counts hard failures so the script can exit non-zero


def section(title: str) -> None:
    print(f"\n== {title} ==")


# --- 1. Python and libraries -------------------------------------------------
section("Python")
print(f"python {platform.python_version()}  ({sys.executable})")

section("Libraries")
for pkg in PACKAGES:
    try:
        print(f"{pkg:<24}{md.version(pkg)}")
    except md.PackageNotFoundError:
        print(f"{pkg:<24}NOT INSTALLED")
        problems += 1

# --- 2. Tesseract OCR --------------------------------------------------------
section("OCR (Tesseract)")
try:
    import pytesseract
    from PIL import Image, ImageDraw, ImageFont

    print(f"tesseract {pytesseract.get_tesseract_version()}")

    # Draw a line of text into a white image, then ask Tesseract to read it back.
    # If the words come back, OCR works end to end.
    img = Image.new("RGB", (900, 120), "white")
    font = ImageFont.load_default(size=48)
    ImageDraw.Draw(img).text((20, 30), "Late returns cost extra", fill="black", font=font)
    read_back = pytesseract.image_to_string(img).strip()
    ok = "Late returns" in read_back
    print(f"OCR test read: {read_back!r} -> {'OK' if ok else 'FAILED'}")
    problems += 0 if ok else 1
except Exception as exc:  # any failure here means OCR isn't usable
    print(f"OCR FAILED: {exc}")
    problems += 1

# --- 3. Embedding model ------------------------------------------------------
section("Embedding model")
try:
    from sentence_transformers import SentenceTransformer

    # First run downloads the model (~130 MB) into the Hugging Face cache;
    # after that it loads from disk and works offline.
    model = SentenceTransformer(settings.embedding_model)
    vectors = model.encode(["How much is the late return fee?"], normalize_embeddings=True)
    print(f"{settings.embedding_model}: loaded, vector size {vectors.shape[1]} -> OK")
except Exception as exc:
    print(f"Embedding model FAILED: {exc}")
    problems += 1

# --- 4. .env settings (names only, never values) -----------------------------
section(".env settings")
env_file = PROJECT_ROOT / ".env"
print(f".env file: {'found' if env_file.exists() else 'not created yet (copy .env.example)'}")
values = {
    "GROQ_API_KEY": settings.groq_api_key,
    "GROQ_MODEL": settings.groq_model,
    "GEMINI_API_KEY": settings.gemini_api_key,
    "TELEGRAM_BOT_TOKEN": settings.telegram_bot_token,
    "TELEGRAM_ALLOWED_CHAT_IDS": settings.telegram_allowed_chat_ids,
}
print(f"answers come from: {settings.llm_provider}")
for name, needed_for in REQUIRED_ENV.items():
    status = "SET" if values[name] else "MISSING"
    # A missing key only matters if it belongs to the provider actually in use.
    in_use = settings.llm_provider in needed_for or "Telegram" in needed_for
    flag = "" if values[name] or not in_use else "   <-- needed"
    print(f"{name:<28}{status:<9}for {needed_for}{flag}")

# Missing .env values are expected this early, so they don't count as failures.
section("Result")
print("All checks passed." if problems == 0 else f"{problems} problem(s) found.")
sys.exit(1 if problems else 0)
