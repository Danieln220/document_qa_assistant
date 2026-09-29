# Costs and limits

Numbers checked on 2026-09-21. Providers change their limits and prices often, so check again before relying on them.

## Free plans

| Provider | Limit | In practice |
|---|---|---|
| Groq (`openai/gpt-oss-120b`) | 8,000 tokens per minute, 200,000 per day | About 100 questions a day. Fast and reliable. |
| Google Gemini | 20 requests per day per model | Not enough to run the full test set (35 calls). Often busy. Useful as a backup. |

Groq limits tokens and Gemini limits requests, so a shorter prompt helps on Groq but not on Gemini.

Google retires Gemini models fairly quickly. If you get a 404, the error message names the replacement model. Put it in `GEMINI_MODEL`.

## Cost per question

One question uses about 2,000 tokens (roughly 1,800 in and 300 out). On a paid plan that's around $0.0005 per question.

| Size | Questions a day | Cost a month |
|---|---|---|
| Small office, 5 people | 50 | under $1 |
| Company, 30 people | 500 | $5-8 |

The embeddings, OCR and search index all run locally and cost nothing. If it needs to be online all the time, a small server is $5-10 a month.

The free plan limits and the "busy" waits go away on a paid account.

## Paying for it

- The client makes their own Groq or Google account and the key goes in `.env`. They pay the provider directly and can see their own usage. This is the simplest option.
- Or the cost can be included in a monthly maintenance fee.
- If nothing is allowed to leave the office, a local model can run on their own machine instead. There's no per-question cost then, but it needs decent hardware.

## Switching from the demo to a real company

1. Put their API key in `.env`
2. Change the model name if needed
3. Replace the demo documents with theirs and run `scripts/ingest.py`

Nothing else changes.
