---
tags: [answerrank, agent]
runs: every 6 hours
---
# Fixer

**Generates schema, FAQ copy, GBP and citation deliverables from audits.** Runs every 6 hours.

## How it works
An audit that only reports a problem churns in month two. The Fixer produces paste-ready assets that move the score, which is what makes the retainer renewable:

1. `LocalBusiness` JSON-LD — the structured data that makes a site machine-readable. Retrieval-based engines quote what they can parse.
2. `FAQPage` JSON-LD plus answer-shaped copy, written against the exact buyer prompts the audit showed the client losing.
3. A Google Business Profile action checklist — the local pack feeds AI Overviews, so GBP completeness is upstream of AI visibility.
4. A citation/directory gap list — the corroborating sources engines check.

Content generation is template-driven so it works with no LLM key; when a key is present the copy is upgraded in place.

## Its researcher asks
Does the work we deliver actually move the score?

## Works from
- [[BrightLocal, Uncovering ChatGPT Search Sources]]: The ChatGPT check searches the web the way ChatGPT does, rather than asking a model from memory.
- [[Cheers, AI search engine source differences (home services baseline)]]: For trades, a contractor's own site carries most engines, and directories carry nearly half of ChatGPT.
- [[Yext, analysis of 6.8 million AI citations (as reported by Cheers)]]: Most of what the engines quote is within a client's control, which is what the retainer sells: the website and the listings, kept right.
- [[Whitespark, 2026 Local Search Ranking Factors (AI search visibility)]]: The delivery method is ordered by this: service pages in month one, curated lists in month two, industry domains and citations in month three, reviews on third-party sites in month four.
- [[Whitespark, 2026 Local Search Ranking Factors (local pack)]]: Getting the primary category exactly right is the first GBP task.
- [[BrightLocal, Local Consumer Review Survey 2026]]: Review work aims at a new review at least every two weeks, not a count.

Part of [[Agents]].
