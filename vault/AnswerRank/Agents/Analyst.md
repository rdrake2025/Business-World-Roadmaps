---
tags: [answerrank, agent]
runs: every 12 hours
---
# Analyst

**Reads outcomes and reports what is actually converting.** Runs every 12 hours.

## How it works
Every other agent acts. This one is the only one that asks whether the acting worked, which is the difference between a system that runs and a system that improves. It reads the `outcomes` table and answers three questions:

1. **What is the funnel actually doing?** Sent to replied to won, measured, not assumed.
2. **Which trades and which sequence steps earn their place?** Reply rate by vertical and by step, so effort moves toward what converts.
3. **How much volume does the target require at the observed rates?** The $5,000/month goal expressed as emails per week, which is the only form of it the operator can act on.

The discipline that matters here is refusing to conclude. Below :data:`MIN_SAMPLE` sends, a per-vertical reply rate is noise, and acting on noise is worse than acting on the benchmark prior — it feels like evidence. Every finding therefore carries the sample it rests on, and thin samples are reported as "not yet known" rather than quietly rounded into a decision.

## Its researcher asks
Is the Analyst concluding on enough evidence?

## Works from
- [[Instantly, Cold Email Benchmark Report 2026]]: The first email carries most of the weight and is kept under 80 words; the checker rejects a first touch over 100.

Part of [[Agents]].
