# Using it with real company documents

Notes from the demo test run (2026-09-22) and what would change with a real company's documents.

## Demo results

20 questions, 5 documents (44 passages):

| | Result |
|---|---|
| Right document found | 14 of 15 |
| Correct answers | 9 of 15 full, 6 correct but short, 0 wrong |
| Unanswerable questions refused | 5 of 5 |
| Made-up answers | 0 |
| Real questions wrongly refused | 0 |

The 6 "partial" answers were right but left out a detail, because the prompt asks for 2-3 sentences. That's easy to change if longer answers are wanted.

## What gets harder with more documents

The demo picks the best 4 passages out of 44. With 50 real documents there could be around 2,000, which makes finding the right one harder. Real documents also bring problems the demo doesn't have:

- Several versions of the same document (2024, 2025, "FINAL v2"). This is the worst one, because an answer from an old version looks just as correct.
- Internal names that don't match the documents (staff say "the yellow form", the document says "Form RER-114")
- Tables, which don't come out of PDFs well
- Bad scans, like phone photos or faxes

The relevance score also doesn't separate answerable from unanswerable questions very well. In the demo, answerable questions scored 0.62-0.79 and unanswerable ones 0.55-0.71. The refusals mostly come from the model only seeing the retrieved passages and from the quote check, not from the score.

## Setting it up for a company

1. Load their documents first and look for duplicates and unreadable scans
2. Agree on one current version of each document and archive the rest
3. Get 20 real questions from staff, plus 5 the documents don't cover, and use them as the test set
4. Adjust `TOP_K`, chunk size and the threshold against that test set, re-testing after each change
5. Write down the known limitations and give them to the client

## Questions to ask first

- How many documents, and what formats?
- Any scans? How good are they?
- Is there one current version of each policy?
- Should everyone see everything, or should some files (like HR) be restricted?
- What languages?
- About how many questions a day?

## Settings

| Setting | Demo | Real company |
|---|---|---|
| `TOP_K` | 4 (because of the free plan limit) | 6-8 on a paid plan. The one miss in the demo was just outside the top 4. |
| `RELEVANCE_THRESHOLD` | 0.5 | Keep 0.5 unless their test set says otherwise |
| Answer length | 2-3 sentences | Ask the client |

## Keeping it up to date

Answers go out of date when a policy changes and nobody re-indexes. It's worth re-running the indexing and the test set every so often.
