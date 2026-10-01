---
tags: [answerrank, agent]
runs: every 6 hours
---
# Researcher

**Runs a researcher against every agent and reports what holds.** Runs every 6 hours.

## How it works
One slot in the tick order rather than seventeen. The researchers are subordinate by design: they read what their agent produced, report on it, and never act. Putting them behind a single coordinator keeps the fleet legible — twenty-six entries in the agent list would be a worse tool, not a better one — while each researcher stays a separate, named, separately tested unit.

It runs last, after every agent has produced whatever it is going to produce this cycle, for the same reason the Analyst does: studying a half-finished tick tells you about the tick, not about the agent.

## Works from
- None yet.

Part of [[Agents]].
