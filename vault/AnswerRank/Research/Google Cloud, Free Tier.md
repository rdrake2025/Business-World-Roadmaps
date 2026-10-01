---
tags: [answerrank, research]
published: 2026
checked: 2026-09
---
# Google Cloud, Free Tier

[Read the source](https://cloud.google.com/free)

## What it found
One e2-micro VM a month is free in us-west1, us-central1 or us-east1, with 30 GB of standard disk and 1 GB of outbound data. An e2-micro has 2 shared vCPUs and 1 GB of memory. Ubuntu images read cloud-init user-data from instance metadata, and Google's network pricing says the free tier doesn't charge for an in-use external IP address.

## So AnswerRank
The server guide offers it as the free option: the same setup file, pasted as the user-data metadata key, in one of those three regions. Oracle's free tier was halved without notice in June 2026, so it is not recommended.

Used by: `server`. Read again every 6 months.

Part of [[Research]].
