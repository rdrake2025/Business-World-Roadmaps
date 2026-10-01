---
tags: [answerrank, agent]
runs: every hour
---
# Auditor

**Runs teaser audits on prospects and full audits for clients.** Runs every hour.

## How it works
Handles both halves of the business:

- **Teaser audits** on `discovered` prospects, producing the proof that makes the cold email land.
- **Full audits** for paying clients on their monthly cycle.

Cold-prospect auditing is rate-limited per run so a runaway loop can never burn a month of API budget in an afternoon.

## Its researcher asks
Do the questions we ask measure anything?

## Works from
- [[SparkToro & Gumshoe, AI brand-recommendation consistency study]]: Audits report the share of answers a business is named in, over repeated runs, with a margin of error.
- [[BrightLocal, Uncovering ChatGPT Search Sources]]: The ChatGPT check searches the web the way ChatGPT does, rather than asking a model from memory.
- [[OpenAI, Web search tool and pricing]]: The ChatGPT check uses web search from the business's own city, so it sees what a local customer sees, with the sources it used.
- [[Anthropic, Web search tool]]: The Claude check searches from the business's city, capped at two searches per question, and only runs in client audits where its cost is trivial next to the fee.
- [[OpenAI, API pricing]]: A cold prospect's check costs about 6 cents (four questions at about 1.5 cents), so the daily number of checks is the budget dial: Lean runs 5 a day (about $9 a month), Standard 20 (about $36), Growth 40 (about $72).
- [[OpenAI Help Center, Setting up and managing prepaid API billing]]: Pilots can be measured before any monthly cost: with only an OpenAI key a full audit is about 45 cents, so three pilots measured three times each fit inside the $5 minimum.

Part of [[Agents]].
