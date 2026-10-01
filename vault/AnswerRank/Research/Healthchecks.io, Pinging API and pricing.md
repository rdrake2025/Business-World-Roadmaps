---
tags: [answerrank, research]
published: 2026
checked: 2026-09
---
# Healthchecks.io, Pinging API and pricing

[Read the source](https://healthchecks.io/docs/http_api/)

## What it found
A running process signals it is alive with a GET or HEAD to https://hc-ping.com/<uuid>; when the signals stop, Healthchecks emails you. The free Hobbyist plan monitors up to 20 checks, with email alerts included.

## So AnswerRank
The fleet pings your check every cycle. If the server dies, the Guardian dies with it and can't warn you; Healthchecks can.

Used by: [[Guardian]], `server`. Read again every 12 months.

Part of [[Research]].
