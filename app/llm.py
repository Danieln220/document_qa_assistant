"""
The language model, behind one small door.

Everything that talks to an LLM goes through `chat_json()`. Two providers are
supported and chosen with `LLM_PROVIDER` in `.env`:

  groq    The default. 200,000 tokens a day on the free tier, about 100
          questions or two evaluation runs, and answers in a second or two.
  gemini  The fallback. Its free tier allows only 20 requests a day per model,
          which is not enough for an evaluation run, but is enough to finish a
          demo if Groq's daily budget runs out. Each model has its own 20.

Both return the same thing: a parsed JSON object. Rate limits are waited out
rather than thrown at the user, and a reply that is not valid JSON is retried
once with the error fed back to the model.

Swapping provider changes nothing else in the system: search, the gates and the
citation checking are untouched.
"""

from __future__ import annotations

import json
import re
import time

from app.config import settings

# How many times to wait out a rate limit or an overloaded provider before
# giving up, and the longest single wait. Past this, telling the user to try again is kinder than leaving
# them watching a spinner.
RETRY_ATTEMPTS = 4
MAX_RATE_LIMIT_WAIT = 30.0

# A busy provider (503) clears in seconds, so those waits start short and grow:
# 2s, 4s, 8s. A quota refusal (429) is different - the provider says how long.
BUSY_FIRST_WAIT = 2.0


class LLMError(RuntimeError):
    """Raised when the model cannot be reached or refuses to return usable JSON."""


def chat_json(system: str, user: str, max_tokens: int = 1200) -> dict:
    """
    Ask the model a question and get a JSON object back.

    Temperature is always 0: the same question should give the same answer, which
    matters both for demos and for the evaluation set being repeatable.
    """
    conversation = [user]  # grows if the model needs to be asked to fix its reply

    for attempt in (1, 2):
        raw = _send(system, conversation, max_tokens)
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError("expected a JSON object")
            return parsed
        except (json.JSONDecodeError, ValueError) as exc:
            if attempt == 2:
                raise LLMError(f"model did not return valid JSON: {exc}") from exc
            conversation += [raw, f"That reply was not valid ({exc}). Reply again with JSON only."]
    raise LLMError("unreachable")


def _send(system: str, conversation: list[str], max_tokens: int) -> str:
    """One call to whichever provider is configured, with rate-limit waiting."""
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            if settings.llm_provider == "groq":
                return _send_groq(system, conversation, max_tokens)
            return _send_gemini(system, conversation, max_tokens)
        except Exception as exc:
            if not _is_retryable(exc) or attempt == RETRY_ATTEMPTS:
                raise
            wait = _seconds_to_wait(exc, attempt)
            print(f"[llm] {'provider busy' if _is_busy(exc) else 'rate limited'}, "
                  f"waiting {wait:.0f}s (attempt {attempt})")
            time.sleep(wait)
    raise LLMError("unreachable")


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

def _send_gemini(system: str, conversation: list[str], max_tokens: int) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.gemini_api_key)
    # Odd entries are the model's own replies, so the roles alternate.
    contents = [
        types.Content(role="user" if i % 2 == 0 else "model", parts=[types.Part(text=text)])
        for i, text in enumerate(conversation)
    ]
    config = types.GenerateContentConfig(
        system_instruction=system,
        temperature=0,
        # Gemini counts its internal "thinking" against this budget, so the
        # limit is generous: a truncated reply is broken JSON, not a short answer.
        max_output_tokens=max_tokens * 2,
        response_mime_type="application/json",  # Gemini's JSON mode
    )
    # Thinking is turned off where the model supports it. This task is grounded
    # extraction - find the line, quote it - so deliberation adds seconds and
    # tokens without improving the answer. Older models reject the setting, so
    # it is applied only when accepted.
    try:
        config.thinking_config = types.ThinkingConfig(thinking_budget=0)
        return (client.models.generate_content(
            model=settings.gemini_model, contents=contents, config=config).text or "")
    except Exception as exc:
        if "thinking" not in str(exc).lower():
            raise
        config.thinking_config = None
        return (client.models.generate_content(
            model=settings.gemini_model, contents=contents, config=config).text or "")


def _send_groq(system: str, conversation: list[str], max_tokens: int) -> str:
    from groq import Groq

    client = Groq(api_key=settings.groq_api_key)
    messages = [{"role": "system", "content": system}]
    messages += [
        {"role": "user" if i % 2 == 0 else "assistant", "content": text}
        for i, text in enumerate(conversation)
    ]
    completion = client.chat.completions.create(
        model=settings.groq_model,
        messages=messages,
        temperature=0,
        response_format={"type": "json_object"},
        max_completion_tokens=max_tokens,
        reasoning_effort=settings.groq_reasoning_effort,
    )
    return completion.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Rate limits
# ---------------------------------------------------------------------------

def _is_retryable(exc: Exception) -> bool:
    """
    True for failures worth waiting out: rate limits (429) and the provider
    being briefly overloaded (503). Both clear on their own; anything else
    (a bad key, a retired model) would fail again just as fast.
    """
    if exc.__class__.__name__ in ("RateLimitError", "ResourceExhausted", "ServerError"):
        return True
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    text = str(exc)
    return code in (429, 503) or "429" in text or "503" in text \
        or "RESOURCE_EXHAUSTED" in text or "UNAVAILABLE" in text


def _is_busy(exc: Exception) -> bool:
    """The provider is overloaded right now (503), rather than out of quota."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    return code == 503 or "503" in str(exc) or "UNAVAILABLE" in str(exc)


def _seconds_to_wait(exc: Exception, attempt: int = 1) -> float:
    """
    How long to wait before trying again.

    "Busy" means the free tier was briefly deprioritised; a couple of seconds is
    usually enough, so waiting 20 would waste the user's time. A quota refusal
    is answered with the delay the provider itself quotes.
    """
    if _is_busy(exc):
        return min(BUSY_FIRST_WAIT * (2 ** (attempt - 1)), 8.0)

    headers = getattr(getattr(exc, "response", None), "headers", {}) or {}
    for key in ("retry-after", "x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
        found = re.search(r"([\d.]+)\s*(ms|s|m)?", str(headers.get(key, "")))
        if found:
            value, unit = float(found.group(1)), found.group(2) or "s"
            seconds = value / 1000 if unit == "ms" else value * 60 if unit == "m" else value
            return min(max(seconds + 1, 2), MAX_RATE_LIMIT_WAIT)
    # Otherwise take it from the message: "try again in 1.02s" / "retryDelay": "17s"
    found = re.search(r"(?:try again in|retryDelay\"?:\s*\")([\d.]+)s", str(exc))
    if found:
        return min(max(float(found.group(1)) + 1, 2), MAX_RATE_LIMIT_WAIT)
    return 20.0


def describe_model() -> str:
    """Which model answered, for logs, the eval report and the web page footer."""
    return settings.groq_model if settings.llm_provider == "groq" else settings.gemini_model
