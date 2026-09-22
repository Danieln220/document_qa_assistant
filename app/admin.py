"""
The owner's screen: manage documents, and see what staff asked.

The point of this page is that the owner never has to ask anyone for help with
the two things that recur:

  * a policy changed, so the new file must go in and the old one must go out;
  * "is it actually useful?", answered by the list of questions it could not
    answer, which is really a list of gaps in their documents.

Everything here is deliberately small. Uploading a file writes it into the
documents folder and re-indexes; deleting removes the file and its passages.
There is no separate database of documents, because the folder *is* the truth.
"""

from __future__ import annotations

import re
import secrets
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app import history
from app.config import PROJECT_ROOT, settings
from app.index import index_stats, ingest
from app.loaders import SUPPORTED_SUFFIXES

router = APIRouter()
security = HTTPBasic(auto_error=False)

# Anything outside these characters is stripped from an uploaded file name, so a
# name can never contain a path, a quote, or something a browser would misread.
SAFE_NAME = re.compile(r"[^A-Za-z0-9 ._()-]+")


def safe_name(filename: str | None) -> str:
    """
    Turn whatever the browser sent into a plain file name.

    Two steps, both needed: `Path(...).name` drops any directory part, so
    "../../.env" becomes ".env"; then anything outside a small set of characters
    is replaced, so a name can never carry a quote, a semicolon or a separator
    into the documents folder.
    """
    bare = Path(filename or "").name
    return SAFE_NAME.sub("_", bare).strip() or "document"


def require_owner(credentials: HTTPBasicCredentials | None = Depends(security)) -> None:
    """
    Ask for the password, if one is configured.

    No password set means the page is open, which is right on a personal machine
    and wrong anywhere else; the README and the handover both say so. The
    comparison is constant-time, so a wrong password cannot be guessed by timing.
    """
    if not settings.admin_password:
        return
    supplied = credentials.password if credentials else ""
    if not secrets.compare_digest(supplied, settings.admin_password):
        raise HTTPException(
            status_code=401,
            detail="Not authorised",
            headers={"WWW-Authenticate": 'Basic realm="Owner"'},
        )


@router.get("/admin")
def admin_page(_: None = Depends(require_owner)) -> FileResponse:
    return FileResponse(PROJECT_ROOT / "static" / "admin.html")


@router.get("/api/admin/overview")
def overview(_: None = Depends(require_owner)) -> dict:
    """Everything the page shows on load: the documents, and the question summary."""
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
        "logging": settings.log_questions,
        "max_upload_mb": settings.max_upload_mb,
        "summary": history.summary(days=30),
    }


@router.get("/api/admin/questions")
def questions(only_unanswered: bool = False, limit: int = 100,
              _: None = Depends(require_owner)) -> dict:
    return {"questions": history.recent(limit=min(limit, 500), only_unanswered=only_unanswered)}


@router.post("/api/admin/documents")
async def upload_document(file: UploadFile = File(...), _: None = Depends(require_owner)) -> dict:
    """
    Add a document from the browser, then index it.

    The name is cleaned and the type checked before anything is written, because
    this endpoint puts a file on disk on someone else's say-so.
    """
    name = safe_name(file.filename)
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"{suffix or 'That file type'} is not supported. "
                   f"Use PDF, Word (.docx) or text (.txt).",
        )

    content = await file.read()
    limit = settings.max_upload_mb * 1024 * 1024
    if len(content) > limit:
        raise HTTPException(status_code=400,
                            detail=f"That file is larger than {settings.max_upload_mb} MB.")
    if not content:
        raise HTTPException(status_code=400, detail="That file is empty.")

    target = settings.documents_dir / name
    replaced = target.exists()
    target.write_bytes(content)

    # Only the new file is processed: everything else keeps its fingerprint.
    results = ingest()
    mine = next((r for r in results if r.name == name), None)
    if mine and mine.action == "failed":
        target.unlink(missing_ok=True)
        ingest()
        raise HTTPException(status_code=400, detail=f"That file could not be read: {mine.note}")

    return {
        "name": name,
        "replaced": replaced,
        "pages": mine.pages if mine else 0,
        "passages": mine.chunks if mine else 0,
    }


@router.delete("/api/admin/documents/{path:path}")
def delete_document(path: str, _: None = Depends(require_owner)) -> dict:
    """Remove a document and its passages, so it can never be quoted again."""
    root = settings.documents_dir.resolve()
    target = (root / path).resolve()
    if not str(target).startswith(str(root)) or not target.is_file():
        raise HTTPException(status_code=404, detail="That document is not there.")

    target.unlink()
    ingest()  # notices the file is gone and deletes its passages
    return {"name": target.name, "removed": True}


@router.post("/api/admin/reindex")
def reindex(force: bool = False, _: None = Depends(require_owner)) -> dict:
    """Re-check the folder. `force` re-reads every document, not only changed ones."""
    results = ingest(force=force)
    counts: dict[str, int] = {}
    for result in results:
        counts[result.action] = counts.get(result.action, 0) + 1
    return {"counts": counts, "passages": index_stats()["chunks"]}
