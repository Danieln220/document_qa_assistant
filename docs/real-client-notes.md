# Taking this to a real company

Written 2026-09-22, from what the demo's evaluation run actually showed. The demo proves the
method; this file is what changes when the documents belong to a real business. Phase 4's
HANDOFF template draws on it, and so should any quote.

## What the demo measured

20 questions against 5 documents (44 passages):

| Measure | Result |
|---|---|
| Right document found | 14/15 (93%) |
| Answers correct | 9/15 complete, 6 correct-but-brief, **0 wrong** |
| Unanswerable questions refused | **5/5** |
| Invented answers | **0** |
| Real questions wrongly refused | **0** |

## What stays the same at a real company

- **Short answers.** Six answers were graded "partial" only because they left out a secondary
  detail (6 sick days, correct, without adding that they do not carry over). That is the prompt
  asking for two or three sentences, which suits someone at a counter with a customer waiting.
  It behaves the same with 5 documents or 500, and it is a one-line prompt change if the client
  prefers fuller answers. **Ask them during setup.**
- **The quote check.** Every quote is verified against the document text, so it does not get
  weaker as the document set grows. This is what keeps invented answers at zero.

## What gets harder, and why

**1. Finding the right passage.** The demo picks the best 4 passages out of 44. A client with
50 documents has perhaps 2,000, and picking 4 out of 2,000 is a much harder job. Real document
sets also contain things the demo's do not:

- **Near-duplicate versions** ("Rental Agreement 2024 / 2025 / 2026 FINAL v2"). The worst
  failure mode in practice: a confident answer taken from a superseded policy looks exactly
  like a correct one.
- **Jargon** - staff ask about "the yellow form", the document says "Form RER-114".
- **Tables and spreadsheets**, which survive PDF extraction badly.
- **Poor scans** - phone photos at an angle, faxes, handwriting in margins. The demo's scan is
  machine-generated and clean, so OCR accuracy on real scans will be lower.

**2. The relevance threshold does less work, not more.** More documents means more passages that
are *about* the right topic without containing the answer - precisely the case where the score
stays high and the answer is not there. In the demo, answerable questions scored 0.62-0.79 and
unanswerable ones 0.55-0.71: overlapping ranges, so no cut-off separates them. Refusal rests on
the model being shown only the retrieved passages, and on the quote check. Neither weakens with
scale.

## The process for a real job

1. **Ingest and inspect before answering anything.** Count the documents, list the duplicate
   versions, find the unreadable scans. Half the problems appear before the first question.
2. **Agree one current version per topic.** The biggest quality win available, and it costs
   nothing: the client names the authoritative file and archives the rest.
3. **Build the evaluation set from their questions.** Ask the owner for the 20 questions staff
   actually ask, plus 5 they know are not covered. This is already the Standard tier deliverable.
4. **Tune against that set** - `TOP_K`, chunk size, threshold - and re-measure after each change.
   Never tune on a hunch.
5. **Hand over the known limits in writing.** A limitation stated up front is a specification; the
   same limitation discovered later is a complaint.

## Ask these before quoting

They change the price:

- How many documents, and in what formats?
- Any scans? Clean, or phone photos?
- One current version of each policy, or several?
- Does everyone see everything, or should HR files be restricted? (Premium tier - the index
  already records which folder each passage came from, ready for this.)
- One language, or more?
- Roughly how many questions a day? (Sets the API cost; see `costs-and-limits.md`.)

## Settings to revisit for a real client

| Setting | Demo | Real client |
|---|---|---|
| `TOP_K` | 4, forced by the free tier's token limit | 6-8 on a paid account. The demo's one retrieval miss was a passage ranked just outside the top 4. |
| `RELEVANCE_THRESHOLD` | 0.5 | Leave at 0.5 unless their own eval set says otherwise. Raising it refuses real questions. |
| Answer length | 2-3 sentences | Ask the client. |

## How to say it on a sales call

> "It refuses in two ways: it won't answer if nothing in your documents looks relevant, and it
> won't answer if it can't quote a real line from your file. We test that with a set of questions
> from your team, including ones your documents can't answer, and you see the scores."

## Worth selling afterwards

Answers go stale when policies change and nobody re-indexes. A small recurring "document health"
check - re-ingest, re-run the evaluation set, report - is an easy retainer and genuinely useful.
