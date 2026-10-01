---
tags: [answerrank, costs]
---
# Costs

The one choice is how many new businesses are checked a day (Keys and settings
asks). Pilots on your own computer cost nothing a month: see [[Pilots]].

| Budget | Checked a day | Google's free server | $6 server |
| --- | --- | --- | --- |
| Lean | 5 | $20.97 | $26.97 |
| Standard | 20 | $49.78 | $55.78 |
| Growth | 40 | $88.18 | $94.18 |

## Lean, line by line (free server)

| What | A month | Note |
| --- | --- | --- |
| Mailbox (Google Workspace) | $8.40 | one mailbox, month to month |
| Server | $0.00 | Google Cloud free tier |
| AI checks of new businesses | $9.00 | 5 a day at about 6 cents each |
| Market research | $1.50 | 5 possible new trades re-checked once a month, 5 businesses each |
| Business finder (Serper) | $1.07 | about 1,075 searches a month; nothing until the first 2,500 free ones are used |
| Domain | $1.00 | you already have it |

On top: Stripe takes about 3.6% of each payment, and each client's monthly
audit costs about $1.59.

`python run.py costs` prints your own numbers. Back to [[AnswerRank]].
