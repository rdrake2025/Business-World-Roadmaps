---
tags: [answerrank, agent]
runs: every 15 minutes
---
# Briefing

**Emails you the day's list each morning, and alerts when it matters.** Runs every 15 minutes.

## How it works
Knowing what needed doing meant opening the console. Now it comes to you:

- **Every morning** (Monday to Saturday, from 7am your time): the Up next list in order, yesterday's numbers, and the month against the target.
- **As it happens**: someone wrote back ready to buy or asking for their report, a client paid, or cold sending paused itself. Those can't wait for tomorrow's briefing.
- **Friday afternoon**: the week reviewed, and the one step of the funnel to fix (see `weekly.py`). That was 45 minutes of the playbook's Friday.
- **Sunday night**: a compressed copy of the whole business (`backup.py`), so losing the server never means losing the business.

It goes to the briefing address (Keys and settings), or the mailbox you send from. The reply reader ignores mail from your own address, so a briefing never looks like a customer reply.

## Its researcher asks
Does your morning briefing reach you?

## Works from
- None yet.

Part of [[Agents]].
