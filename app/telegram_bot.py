"""
The same assistant, in Telegram.

    .venv/bin/python -m app.telegram_bot

Staff in the yard have a phone, not a laptop, so the bot answers exactly the
questions the web chat answers, with the same citations and the same refusals.
It calls the same `answer()` function, so the two can never drift apart.

It uses long polling: the bot asks Telegram for new messages rather than
Telegram calling us. That means no public address, no tunnel and no open port,
which is what makes it run from a laptop during a demo, and from a client's own
machine afterwards.

Access is limited to the chat IDs in TELEGRAM_ALLOWED_CHAT_IDS. Company
documents are not something a stranger who finds the bot should be able to read.
To add someone: they message the bot, their ID appears in this program's log,
and it goes in `.env`.
"""

from __future__ import annotations

import asyncio
import html
import re

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import Conflict
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from app.answer import Answer, answer
from app.config import settings

# Telegram rejects messages over 4096 characters, so long answers are trimmed
# with room left for the closing note.
MAX_MESSAGE_CHARS = 3900

# Greetings and thanks are conversation, not questions about the documents.
# Searching for "hello" finds nothing and produces a blunt refusal, which looks
# broken rather than careful, so they are answered directly instead.
SMALL_TALK = {
    "hi", "hii", "hey", "hello", "helo", "yo", "good morning", "good afternoon",
    "good evening", "morning", "afternoon", "evening", "start", "test", "testing",
}
THANKS = {"thanks", "thank you", "thx", "ta", "cheers", "ok", "okay", "got it", "great"}

WELCOME = (
    "<b>{company}</b>\n"
    "Ask me anything from the company documents: rental terms, damage charges, "
    "service intervals, branch hours, staff policy.\n\n"
    "Every answer shows the document and page it came from. If the answer isn't "
    "in the documents, I'll say so rather than guess.\n\n"
    "Try: <i>What do we charge for a late return?</i>"
)


def is_allowed(chat_id: int, allowed: list[int] | None = None) -> bool:
    """
    May this chat use the bot?

    An empty allowlist means "not configured yet": the bot then refuses everyone
    and prints the ID to add, which is safer than being open to anyone who finds it.
    `allowed` can be passed in by the tests; normally it comes from `.env`.
    """
    if allowed is None:
        allowed = settings.telegram_allowed_chat_ids
    return chat_id in allowed


async def start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not await _guard(update, chat_id):
        return
    await update.message.reply_text(
        WELCOME.format(company=settings.company_name), parse_mode=ParseMode.HTML
    )


async def handle_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Answer one message."""
    chat_id = update.effective_chat.id
    if not await _guard(update, chat_id):
        return

    question = (update.message.text or "").strip()
    if not question:
        return

    # Answer conversation as conversation. Only real questions reach the documents.
    plain = question.lower().strip(" !.?,")
    if plain in SMALL_TALK:
        await update.message.reply_text(
            WELCOME.format(company=settings.company_name), parse_mode=ParseMode.HTML
        )
        return
    if plain in THANKS:
        await update.message.reply_text("Any time. Ask me whenever you need something checked.")
        return

    # "typing..." in the chat while the documents are searched, so the wait
    # doesn't look like the bot ignoring them.
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # `answer()` is ordinary blocking code (search, then an API call). Running it
    # in a thread keeps the bot responsive to other chats meanwhile.
    result = await asyncio.to_thread(answer, question)

    await update.message.reply_text(
        format_answer(result), parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )
    print(f"[telegram] chat {chat_id}: {'answered' if result.answered else result.reason} "
          f"in {result.seconds:.1f}s - {question[:60]}")


def pretty_name(file_name: str) -> str:
    """
    "Ridgeline_Rental_Agreement_2026.pdf" -> "Ridgeline Rental Agreement 2026".

    Staff recognise the document by its name, not its file name, and a phone
    screen is too narrow to waste on underscores and extensions. The same
    tidy-up happens in the web chat.
    """
    name = re.sub(r"\.[^.]+$", "", file_name)
    name = re.sub(r"[_-]+", " ", name)
    return re.sub(r"\s*scanned\s*$", "", name, flags=re.I).strip()


def _escape(text: str) -> str:
    """
    Escape only what Telegram's HTML mode needs: & < >.

    Apostrophes and quotation marks are left alone, because documents are full
    of them and escaping them makes the message harder to read.
    """
    return html.escape(text, quote=False)


def format_answer(result: Answer) -> str:
    """
    Lay the answer out for a phone screen.

    Telegram has no cards, so each source becomes a short block: the document and
    where it sits, then the quoted line. Everything is HTML-escaped, because a
    document may legitimately contain characters like < that would otherwise
    break the message.
    """
    if not result.answered:
        return f"🔸 {_escape(result.text)}"

    parts = [_escape(result.text), ""]
    for citation in result.citations:
        flags = " <i>(read by OCR)</i>" if citation.needed_ocr else ""
        parts.append(
            f"📄 <b>{_escape(pretty_name(citation.source_file))}</b> - "
            f"{_escape(citation.location)}{flags}\n"
            f"<blockquote>{_escape(citation.quote)}</blockquote>"
        )

    message = "\n".join(parts)
    if len(message) > MAX_MESSAGE_CHARS:
        message = message[:MAX_MESSAGE_CHARS].rsplit("\n", 1)[0] + "\n<i>(shortened)</i>"
    return message


async def _guard(update: Update, chat_id: int) -> bool:
    """Turn away chats that are not on the allowlist, and log the ID to add."""
    if is_allowed(chat_id):
        return True
    name = update.effective_user.full_name if update.effective_user else "unknown"
    print(f"[telegram] refused chat {chat_id} ({name}). "
          f"To allow it, add {chat_id} to TELEGRAM_ALLOWED_CHAT_IDS in .env and restart.")
    await update.message.reply_text(
        "This assistant is limited to approved staff. Ask your manager to add you."
    )
    return False


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Turn library errors into one readable line instead of a stack trace.

    The common one is Conflict: Telegram allows a token to be polled by one
    program at a time, so a second copy (an old terminal, or a copy of the
    project) silently steals the messages. Saying so plainly saves a long hunt.
    """
    error = context.error
    if isinstance(error, Conflict):
        print("[telegram] Another copy of this bot is already running with the same token.")
        print("[telegram] Stop it first (Ctrl-C in its terminal, or: pkill -f app.telegram_bot).")
        context.application.stop_running()
        return
    print(f"[telegram] {type(error).__name__}: {error}")


def main() -> None:
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set in .env (get one from @BotFather).")

    application = Application.builder().token(settings.telegram_bot_token).build()
    application.add_handler(CommandHandler(["start", "help"], start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_question))
    application.add_error_handler(on_error)

    allowed = settings.telegram_allowed_chat_ids
    print(f"{settings.company_name} assistant is running on Telegram.")
    print(f"Allowed chats: {allowed if allowed else 'NONE YET - message the bot and its ID will appear here'}")
    print("Press Ctrl-C to stop.")
    application.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
