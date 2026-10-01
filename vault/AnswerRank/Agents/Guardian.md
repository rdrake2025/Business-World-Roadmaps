---
tags: [answerrank, agent]
runs: every 30 minutes
---
# Guardian

**Watches Autopilot and pauses any part that starts going wrong.** Runs every 30 minutes.

## How it works
A business that sends email on its own needs something watching that isn't the thing sending. Every other agent is judged on getting its job done; the Guardian is judged only on whether it noticed, in time, that something was going wrong, and whether it stopped the right part and told you.

What it watches, and what it does:

- **Complaints.** Mailbox providers act on spam reports (Gmail's line is 0.3% of mail reported, and the aim is under 0.1%). You can't see the reports, but you can see the replies that say it: "this is spam", "reporting you". Three of those in a week pauses prospecting until you look. So does more than 5% of a week's first emails answered "remove me", which says the targeting is off. An unsubscribe on its own is healthy: it's what you want people to do instead of reporting you. It does not resume by itself: the copy or the targeting is wrong, and only a person can say which.
- **Bounces.** The send path already refuses cold email over the bounce ceiling. The Guardian makes that visible as a pause, and lifts it by itself once the rate is back under the line.
- **Things waiting for you.** Answers it wasn't sure of, held for more than a day. A person who asked a question and heard nothing is a lost sale.
- **Agents failing.** Any agent whose last three runs failed.
- **The mailbox failing.** A send that errored (not a bounce) in the last day: usually a changed password.
- **Mail from strangers** that matched nobody: often a referral or a client writing from a new address.
- **API spend** over the month's budget.

Everything it finds is emailed to you once a day at most, per problem, and shown on the phone.

## Its researcher asks
Does anything stay paused without you noticing?

## Works from
- [[Healthchecks.io, Pinging API and pricing]]: The fleet pings your check every cycle.

Part of [[Agents]].
