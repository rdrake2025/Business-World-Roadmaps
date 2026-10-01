---
tags: [answerrank, agent]
runs: every 30 minutes
---
# Concierge

**Handles inbound replies and drafts the response.** Runs every 30 minutes.

## How it works
This was the largest unmanaged gap in the business. Everything upstream exists to produce a reply, and until now a reply landed in an inbox and sat there. The reply is worth more than every audit that preceded it.

Two modes:

- **Connected** (IMAP configured): polls the sending mailbox, matches replies to prospects, classifies intent and drafts a response.
- **Manual**: the operator logs a reply from the console, and the same classification and drafting runs.

It drafts; whether a draft goes without you is Autopilot's call (`automation.auto_approve`), and even on Autopilot only answers it is sure of go by themselves: the report, the payment link, a question with a written answer in `answers.py`, a client's billing or cancellation. Anything else is held for you and you're emailed about it at once ("escalated").

## Its researcher asks
Are inbound replies being read correctly?

## Works from
- [[Help-desk practice on saved replies (Zendesk, Intercom, HelpDesk)]]: Only answers you wrote yourself are saved for reuse, each under the words that trigger it, listed in one place to review or delete.

Part of [[Agents]].
