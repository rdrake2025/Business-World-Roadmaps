---
tags: [answerrank, research]
published: 2024-02
checked: 2026-09
---
# Google, Email sender guidelines

[Read the source](https://support.google.com/a/answer/14229414?hl=en)

## What it found
Senders of 5,000+ messages a day to Gmail need SPF, DKIM and DMARC (p=none at least, aligned), and one-click unsubscribe. Keep the user-reported spam rate below 0.1% and never let it reach 0.3%.

## So AnswerRank
The doctor blocks sending until SPF, DKIM and DMARC pass, whatever the volume. Every email has a one-click unsubscribe. The complaint ceiling is 0.1%.

Used by: `sending`, `doctor`. Read again every 12 months.

Part of [[Research]].
