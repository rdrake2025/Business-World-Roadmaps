---
tags: [answerrank, research]
published: 2026
checked: 2026-09
---
# Anthropic, Web search tool

[Read the source](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool)

## What it found
The web_search tool (web_search_20250305) takes max_uses and an approximate user_location, returns cited sources, and costs $10 per 1,000 searches plus the tokens the results add.

## So AnswerRank
The Claude check searches from the business's city, capped at two searches per question, and only runs in client audits where its cost is trivial next to the fee.

Used by: [[Auditor]]. Read again every 6 months.

Part of [[Research]].
