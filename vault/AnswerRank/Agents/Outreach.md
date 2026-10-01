---
tags: [answerrank, agent]
runs: every 4 hours
---
# Outreach

**Drafts compliant, evidence-backed outreach for audited prospects.** Runs every 4 hours.

## How it works
Design decisions that are deliberate, not defaults:

**Drafts, never auto-sends.** The agent writes messages and queues them at `status="drafted"`. Sending requires an explicit human approval step plus configured SMTP. One misconfigured loop that blasts a bad list destroys the sending domain permanently, and a domain reputation cannot be bought back. A human approving a batch costs two minutes a day and removes that risk.

**Every message carries real evidence.** We only pitch businesses where the teaser audit proved a gap. The opening line is a measured fact about *their* business, not a template variable. That is what separates this from spam in both the recipient's judgement and a regulator's.

**Compliance is enforced in code, not documented in a wiki.** CAN-SPAM requires a physical postal address, a working opt-out, and a non-deceptive subject line. The 2026 Google/Yahoo/Microsoft bulk rules add one-click unsubscribe and complaint rates under 0.3%. `_compliance_block` and the rate caps in :class:`~answerrank.config.OutreachPolicy` implement all of it, and :meth:`preflight` refuses to send if anything is missing.

## Its researcher asks
Which part of the sequence earns replies?

## Works from
- [[BrightLocal, Local Consumer Review Survey 2026]]: Review work aims at a new review at least every two weeks, not a count.
- [[Instantly, Cold Email Benchmark Report 2026]]: The first email carries most of the weight and is kept under 80 words; the checker rejects a first touch over 100.

Part of [[Agents]].
