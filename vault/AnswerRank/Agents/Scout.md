---
tags: [answerrank, agent]
runs: every 6 hours
---
# Scout

**Discovers local service businesses and adds them to the prospect pool.** Runs every 6 hours.

## How it works
Two sources, in priority order:

1. **Serper Places** (live): searches "<vertical> in <city>" and reads the local pack. Real businesses, with websites and phone numbers.
2. **Seed file** (offline): a CSV the operator drops in. In demo mode only, made-up businesses so the pipeline can be watched without keys. Real mode never invents any: with no key and no file it says so and adds nothing.

The Scout enforces one hard rule: never add a business we have already seen. Duplicate outreach is the fastest way to a spam complaint, and complaint rate is the constraint that governs the whole acquisition channel.

## Its researcher asks
Is discovery finding businesses actually worth pitching?

## Works from
- [[Serper, Pricing]]: The finder costs nothing to start; one places search finds up to 10 businesses.

Part of [[Agents]].
