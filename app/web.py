"""
The web chat: a small FastAPI app serving one page and three endpoints.

    .venv/bin/uvicorn app.web:api --port 8000
    open http://localhost:8000

It is deliberately thin. All the thinking happens in `answer()`, so the web
chat, the Telegram bot and the evaluation set behave identically; this file only
turns that result into JSON and serves the documents so a citation can be opened.

Nothing here ever shows a stack trace: an unexpected failure becomes a short,
plain message, because a demo (and a client's staff) should never see Python.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import history
from app.admin import router as admin_router
from app.answer import Answer, answer
from app.config import PROJECT_ROOT, settings
from app.index import index_stats
from app.llm import describe_model

STATIC_DIR = PROJECT_ROOT / "static"

# `docs_url=None` switches off FastAPI's built-in API pages: this is a product
# for staff, not a developer console.
api = FastAPI(title="Document Q&A Assistant", docs_url=None, redoc_url=None)


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=500)


@api.get("/")
def home() -> FileResponse:
    """The chat page itself."""
    return FileResponse(STATIC_DIR / "index.html")


@api.get("/api/status")
def status() -> dict:
    """
    What the assistant can see: the indexed documents, shown in the sidebar.

    Listing the documents is not decoration. The first question a user has is
    "does it even have my handbook?", and this answers it before they ask.
    """
    stats = index_stats()
    documents = [
        {
            "name": Path(path).name,
            "path": path,
            "url": f"/files/{quote(path)}",
            "type": details.get("source_type", "").upper(),
            "pages": details.get("pages", 0),
            "passages": details.get("chunks", 0),
        }
        for path, details in sorted(stats["files"].items())
    ]
    return {
        "company": settings.company_name,
        "documents": documents,
        "passages": stats["chunks"],
        "model": describe_model(),
    }


@api.post("/api/ask")
def ask(payload: Question) -> JSONResponse:
    """Answer one question. Always returns 200 with a readable result."""
    try:
        result = answer(payload.question)
        # Recorded for the owner's screen: what was asked, and whether the
        # documents could answer it.
        history.record(
            question=payload.question,
            answered=result.answered,
            reason=result.reason,
            sources=[c.source_file for c in result.citations],
            channel="web",
            seconds=result.seconds,
        )
    except Exception as exc:  # last line of defence; the detail stays in the log
        print(f"[web] unexpected failure: {exc}")
        return JSONResponse({
            "answered": False,
            "text": "Something went wrong at our end. Please try that question again.",
            "reason": "error",
            "citations": [],
        })
    return JSONResponse(_as_json(result))


def _as_json(result: Answer) -> dict:
    """Shape one answer for the page, including a link that opens each source."""
    return {
        "answered": result.answered,
        "text": result.text,
        "reason": result.reason,
        "seconds": round(result.seconds, 1),
        "model": result.model,
        "citations": [
            {
                "file": c.source_file,
                "location": c.location,
                "quote": c.quote,
                "ocr": c.needed_ocr,
                "exact": c.exact,
                # PDFs open at the cited page; other formats open at the top.
                "url": f"/files/{quote(c.source_path)}" + (f"#page={c.page}" if c.page else ""),
            }
            for c in result.citations
        ],
    }


@api.get("/files/{path:path}")
def document_file(path: str) -> FileResponse:
    """
    Serve one of the client's documents so a citation can be checked.

    Only files inside the documents folder are served. The path is resolved and
    compared with that folder, so "../../.env" cannot escape it.
    """
    root = settings.documents_dir.resolve()
    target = (root / path).resolve()
    if not str(target).startswith(str(root)) or not target.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    # `inline` so the browser's own PDF viewer opens it at the #page anchor
    # instead of downloading the file.
    return FileResponse(target, headers={"Content-Disposition": f'inline; filename="{target.name}"'})


# The owner's screen lives in its own module; its routes are added before the
# static mount so /admin resolves to the page rather than a file.
api.include_router(admin_router)

api.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
