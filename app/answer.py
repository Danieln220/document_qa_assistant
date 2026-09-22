"""
Answering a question, with the guards that stop invention.

`answer()` is the single entry point used by the web chat, the Telegram bot and
the eval runner, so all three behave identically.

Three guards, in order:

  Gate 1  Nothing relevant was found. If even the closest passage is below the
          relevance threshold, refuse without calling the LLM at all. Cheap,
          instant, and it catches questions about things the client has no
          documents for.

  Gate 2  The model itself says the answer isn't there ("answerable": false).

  Gate 3  Citation check. Every quote the model returns is looked up in the real
          passage text. Quotes that cannot be found are dropped; if nothing
          verifiable is left, the answer becomes a refusal.

Gate 3 is the important one. The model is asked to behave, but it is also checked.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from app.config import settings
from app.llm import chat_json, describe_model
from app.loaders import HEADING_RE
from app.prompts import SYSTEM_PROMPT, build_user_prompt, refusal_text
from app.retrieval import SearchResult, best_vector_score, search

# A quote must match the source at least this well to be shown. OCR text has
# small errors ("l" for "1"), and models sometimes drop a comma, so an exact
# match is too strict; below this, it is not the same sentence.
QUOTE_MATCH_THRESHOLD = 85.0

# Longest quote shown in a citation. Anything longer is the model dumping the
# passage instead of pointing at the line that matters.
MAX_QUOTE_CHARS = 400


@dataclass
class Citation:
    """One checked quote, ready to show to a person."""

    source_file: str
    source_path: str    # path inside documents/, used to open the file in the browser
    page: int | None
    section: str        # heading nearest to the quote, used when there is no page
    quote: str          # the text AS IT APPEARS in the document, not as the model typed it
    chunk_id: str
    needed_ocr: bool
    exact: bool         # True when the model's quote matched the source character for character

    @property
    def location(self) -> str:
        if self.page is not None:
            return f"page {self.page}"
        return self.section or "start of document"


@dataclass
class Answer:
    """The result of one question."""

    question: str
    answered: bool              # False means the assistant refused
    text: str                   # the answer, or the refusal message
    citations: list[Citation] = field(default_factory=list)
    reason: str = ""            # why it refused: no_relevant_passages | model_said_no | no_verifiable_quotes | error
    passages_used: int = 0
    best_score: float = 0.0
    model: str = ""
    seconds: float = 0.0


def answer(question: str, top_k: int | None = None) -> Answer:
    """Answer one question from the indexed documents, or refuse."""
    started = time.time()
    question = question.strip()
    if not question:
        return Answer(question=question, answered=False, text="Please type a question.", reason="empty_question")

    passages = search(question, top_k=top_k)
    best = best_vector_score(passages)

    # --- Gate 1: nothing close enough was found --------------------------------
    if not passages or best < settings.relevance_threshold:
        return Answer(
            question=question,
            answered=False,
            text=refusal_text(settings.company_name),
            reason="no_relevant_passages",
            passages_used=len(passages),
            best_score=best,
            seconds=time.time() - started,
        )

    try:
        reply = _ask_model(question, passages)
    except Exception as exc:
        # The user never sees a stack trace; the terminal log keeps the detail.
        print(f"[answer] model call failed: {exc}")
        return Answer(
            question=question,
            answered=False,
            text="Sorry, the assistant is temporarily unavailable. Please try again in a moment.",
            reason="error",
            passages_used=len(passages),
            best_score=best,
            seconds=time.time() - started,
        )

    # --- Gate 2: the model says the answer is not in the passages --------------
    if not reply.get("answerable"):
        return Answer(
            question=question,
            answered=False,
            text=refusal_text(settings.company_name, str(reply.get("missing", "")).strip()),
            reason="model_said_no",
            passages_used=len(passages),
            best_score=best,
            model=describe_model(),
            seconds=time.time() - started,
        )

    # --- Gate 3: check every quote against the real passage --------------------
    citations = verify_citations(reply.get("citations", []), passages)
    if not citations:
        return Answer(
            question=question,
            answered=False,
            text=refusal_text(settings.company_name),
            reason="no_verifiable_quotes",
            passages_used=len(passages),
            best_score=best,
            model=describe_model(),
            seconds=time.time() - started,
        )

    return Answer(
        question=question,
        answered=True,
        text=str(reply.get("answer", "")).strip(),
        citations=citations,
        passages_used=len(passages),
        best_score=best,
        model=describe_model(),
        seconds=time.time() - started,
    )


# ---------------------------------------------------------------------------
# The model call
# ---------------------------------------------------------------------------

def _ask_model(question: str, passages: list[SearchResult]) -> dict:
    """
    Ask the model for a grounded answer as JSON.

    The provider (Gemini or Groq), JSON mode, rate-limit waiting and the retry
    for a malformed reply all live in `app/llm.py`, so this stays about the
    assistant's own logic.
    """
    reply = chat_json(
        system=SYSTEM_PROMPT.format(company=settings.company_name),
        user=build_user_prompt(question, passages),
    )
    if "answerable" not in reply:
        raise ValueError('the model\'s reply had no "answerable" field')
    return reply


# ---------------------------------------------------------------------------
# Gate 3: citation checking
# ---------------------------------------------------------------------------

def verify_citations(raw_citations: list, passages: list[SearchResult]) -> list[Citation]:
    """
    Keep only the quotes that really appear in the passages they cite.

    A quote is accepted when it matches the passage text exactly (ignoring
    spacing), or closely enough to be the same sentence. In the close case the
    text stored is the version FROM THE DOCUMENT, not the model's wording, so
    what the user sees always matches what is written in their file.
    """
    by_id = {f"S{i}": p for i, p in enumerate(passages, start=1)}
    citations: list[Citation] = []
    seen: set[tuple[str, str]] = set()

    for item in raw_citations or []:
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("source_id", "")).strip().upper()
        quote = str(item.get("quote", "")).strip()
        passage = by_id.get(source_id)
        if passage is None or len(quote) < 10:
            continue  # cites a passage that wasn't given, or quotes almost nothing

        found = _locate_quote(quote, passage.text)
        if found is None:
            continue  # the quote is not in that passage: drop it
        source_quote, exact = found

        key = (passage.chunk_id, source_quote[:60])
        if key in seen:
            continue  # the same line cited twice
        seen.add(key)

        citations.append(Citation(
            source_file=passage.source_file,
            source_path=passage.source_path,
            page=passage.page,
            section=_section_for_quote(passage, source_quote),
            quote=source_quote[:MAX_QUOTE_CHARS],
            chunk_id=passage.chunk_id,
            needed_ocr=passage.needed_ocr,
            exact=exact,
        ))
    return citations


def _locate_quote(quote: str, passage_text: str) -> tuple[str, bool] | None:
    """
    Find the model's quote inside the passage.

    Returns the matching text as it appears in the document and whether the
    match was exact, or None when the quote cannot be found at all.
    """
    flat_quote = " ".join(quote.split())
    flat_passage = " ".join(passage_text.split())

    position = flat_passage.find(flat_quote)
    if position >= 0:
        return flat_passage[position:position + len(flat_quote)], True

    # Not character-identical: allow for OCR slips and dropped punctuation, but
    # only when the best matching stretch of the passage is close enough.
    alignment = fuzz.partial_ratio_alignment(flat_quote, flat_passage)
    if alignment is None or alignment.score < QUOTE_MATCH_THRESHOLD:
        return None
    return flat_passage[alignment.dest_start:alignment.dest_end].strip(), False


def _section_for_quote(passage: SearchResult, quote: str) -> str:
    """
    The heading directly above the quote.

    A chunk can span more than one short section, so the chunk's own heading can
    be a section too early. Looking for the last heading line above the quote
    makes citations in Word and text files point at the right place.
    """
    position = passage.text.find(quote[:40])
    if position < 0:
        return passage.heading
    heading = None
    for line in passage.text[:position].splitlines():
        stripped = line.strip()
        if HEADING_RE.match(stripped):
            heading = stripped
    return heading or passage.heading
