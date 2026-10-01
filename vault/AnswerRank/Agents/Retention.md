---
tags: [answerrank, agent]
runs: once a day
---
# Retention

**Scores client health and names the one action that saves each account.** Runs once a day.

## How it works
The arithmetic is not close. At a $997 retainer and roughly 35 sends per client, replacing a churned client costs weeks of outreach; keeping one costs a report and a question. A business reaching $5,000/month profit on five clients cannot absorb losing one.

What the churn research says, and what this implements:

- **Health deteriorates 60 to 90 days before the cancellation.** By the time someone asks to cancel, the decision is months old. So this scores health continuously rather than reacting to notice.
- **Silence is the leading indicator.** Not complaints — complaints mean the client still expects something to change. The account that has said nothing at all is the one in danger.
- **The first 90 days decide the relationship.** A client who has not seen a result by day 90 will not wait for one at day 180.

Scores are deliberately unflattering. A health score that reads 85 for an account nobody has spoken to in two months is worse than no score at all.

## Its researcher asks
Does the health score see a churn coming?

## Works from
- [[BrightLocal, Local Consumer Review Survey 2026]]: Review work aims at a new review at least every two weeks, not a count.
- [[Customer health scoring practice (Gainsight, HubSpot, Planhat)]]: 'Act now' needs a concrete risk: a failing card, no report delivered, fixes still not live after three weeks, a falling score, or long silence with nothing moving.

Part of [[Agents]].
