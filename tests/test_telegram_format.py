"""
Tests for the Telegram bot's own logic: who may use it, and how a message reads.

No network and no bot token needed - these check the two things that would
embarrass us in front of a client: a stranger getting answers from company
documents, and a document's own characters breaking the message.
"""

import app.telegram_bot as bot
from app.answer import Answer, Citation


def citation(**kwargs) -> Citation:
    base = dict(source_file="Returns_and_Damages_Policy_scanned.pdf", source_path="policy.pdf",
                page=2, section="3. Late Returns", quote="a late return administration fee of $35",
                chunk_id="policy.pdf|p2|c0", needed_ocr=True, exact=True)
    return Citation(**{**base, **kwargs})


def test_only_listed_chats_are_allowed():
    assert bot.is_allowed(12345, allowed=[12345]) is True
    assert bot.is_allowed(99999, allowed=[12345]) is False


def test_an_empty_allowlist_lets_nobody_in():
    """Not configured must mean closed, not open to whoever finds the bot."""
    assert bot.is_allowed(12345, allowed=[]) is False


def test_an_answer_shows_its_sources():
    message = bot.format_answer(Answer(
        question="late return?", answered=True,
        text="The late charge is $1,155 plus a $35 fee.", citations=[citation()],
    ))
    assert "$1,155" in message
    # The file name is tidied for a phone screen: no underscores, no extension.
    assert "Returns and Damages Policy" in message
    assert "_scanned.pdf" not in message
    assert "page 2" in message
    assert "read by OCR" in message          # the scan is flagged, as in the web chat
    assert "$35" in message


def test_a_refusal_is_short_and_has_no_sources():
    message = bot.format_answer(Answer(
        question="parental leave?", answered=False,
        text="I couldn't find an answer to that in the documents.", reason="model_said_no",
    ))
    assert "couldn't find" in message
    assert "📄" not in message


def test_document_characters_cannot_break_the_message():
    """A quote containing < or & must not corrupt Telegram's HTML formatting."""
    message = bot.format_answer(Answer(
        question="q", answered=True, text="Rates apply to loads <2 tonnes & over.",
        citations=[citation(quote="loads <2 tonnes & over")],
    ))
    assert "&lt;2 tonnes &amp; over" in message
    assert "<2 tonnes" not in message


def test_a_very_long_answer_is_shortened_to_fit():
    message = bot.format_answer(Answer(
        question="q", answered=True, text="x" * 200,
        citations=[citation(quote="y" * 900) for _ in range(8)],
    ))
    assert len(message) <= bot.MAX_MESSAGE_CHARS + 40
    assert "(shortened)" in message


def test_greetings_and_thanks_are_not_treated_as_questions():
    """"hello" should get a welcome, not a refusal about the documents."""
    for word in ("hi", "Hello!", "good morning", "TESTING"):
        assert word.lower().strip(" !.?,") in bot.SMALL_TALK
    for word in ("thanks", "Thank you", "cheers"):
        assert word.lower().strip(" !.?,") in bot.THANKS


def test_a_real_question_is_not_mistaken_for_small_talk():
    for question in ("what do we charge for a late return?", "hello, what are the branch hours?"):
        plain = question.lower().strip(" !.?,")
        assert plain not in bot.SMALL_TALK and plain not in bot.THANKS
