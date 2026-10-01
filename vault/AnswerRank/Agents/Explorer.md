---
tags: [answerrank, agent]
runs: every 12 hours
---
# Explorer

**Samples candidate markets to find the next vertical worth entering.** Runs every 12 hours.

## How it works
The market scoring model is a set of priors. This agent tests them. It picks the least-examined candidate trade, samples real businesses in it, runs the same audit the paying product runs, and reports what it measured rather than what was assumed.

That distinction matters. A trade can look ideal on paper — high ticket, fragmented, big marketing budgets — and turn out to be perfectly visible in AI answers already, in which case there is nothing to sell. The only way to know is to measure, and measuring costs fractions of a cent.

One market per run, deliberately. Exploration should never crowd out the work that pays.

## Its researcher asks
Were our guesses about a market right when we measured it?

## Works from
- None yet.

Part of [[Agents]].
