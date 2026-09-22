# What this costs to run, and what the free tiers actually allow

Written 2026-09-21, from limits measured on this project rather than from marketing pages.
Applies to both portfolio projects, since `lead-to-crm-automation` calls the same LLM providers.
Re-check the numbers before quoting them to a client: providers change limits and prices often.

## The short version for a sales call

> "The demo you're watching runs on a free account, which is why it pauses occasionally.
> For your volume it's a few dollars a month, on your own account so you're never locked in.
> And if you'd rather nothing left your office, the same system runs on your own server
> with no per-question cost at all."

## Free-tier limits, measured on 2026-09-21

| Provider | Per minute | Per day | What that means here |
|---|---|---|---|
| **Groq** (`openai/gpt-oss-120b`) | 8,000 tokens | 200,000 tokens | About 100 questions a day, or 2 full evaluation runs. Fast and steady. |
| **Google Gemini** (free tier) | - | **20 requests per model** | Not enough for one evaluation run (35 calls). Each model has its own 20, so switching model buys another 20. Also returns "busy" (503) often, because free users are deprioritised. |

Notes worth remembering:
- Groq's limit is **tokens**, Gemini's is **requests**. Trimming the prompt helps on Groq and does nothing on Gemini.
- Google retires models quickly. `gemini-2.5-flash` was already closed to new accounts; the 404 error names its replacement.
- Free tiers are fine for a demo and awkward for an evaluation run. Don't run the eval right before recording.

## What one question costs

About **2,000 tokens**: roughly 1,800 in (4 document passages plus the prompt) and 300 out.

At pay-as-you-go rates for this class of model, that is around **$0.0005 per question** - half a cent for ten questions.

| Client size | Questions/day | Rough cost/month |
|---|---|---|
| 5-person office | 50 | under $1 |
| 30-person company | 500 | $5-8 |
| Running the 20-question eval daily | 35 calls | pennies |

Free in every case, because they run on the client's own machine:
- embeddings (bge-small),
- OCR (Tesseract),
- the search index (Chroma).

The only other real cost is hosting, if the client wants it always on: a $5-10/month VPS, or their own server. A laptop demo needs neither.

**Paying removes the throttling.** The per-minute and per-day caps and the "provider busy" waits are free-tier behaviour; they disappear once a card is attached.

## Three ways to bill it

1. **Client brings their own key (recommended).** They create the Groq or Google account and you put the key in `.env`. The bill is theirs, there is no billing relationship to manage, and they can see their own usage. Sell it as ownership: "you own the account, you're never locked in".
2. **Included in your price.** Simpler for a non-technical buyer. At a few dollars a month it can sit inside a maintenance retainer - but never on an uncapped account.
3. **Nothing leaves their building.** The same code runs a local model through Ollama on the client's hardware: no API, no per-question cost, no data leaving. This is the Premium tier ("deployment on the client's own infrastructure") and the answer for anyone with confidential contracts.

## Going from demo to paying client

Almost nothing changes in the code:

1. Put the client's API key in `.env` (`LLM_PROVIDER`, plus their key).
2. Change the model name if theirs differs.
3. Replace the demo documents with theirs and run `scripts/ingest.py`.

Search, the refusal gates, the citation checking and the evaluation set are untouched. Provider swaps live in `app/llm.py` alone, which is also where a local model would be added.

## Rules of thumb

- Quote **"a few dollars a month"**, never "free". Free tiers change, and a client who hits a limit mid-day will blame the system, not the provider.
- For anything unattended (the lead pipeline especially), assume the free tier **will** run out and design a fallback, as `app/llm.py` does.
- Measure limits from the error messages themselves. Both providers state the exact quota and the wait in the 429 body.
