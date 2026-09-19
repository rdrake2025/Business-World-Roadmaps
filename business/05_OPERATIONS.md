# Operations Manual

How to run the fleet day to day, and what to do when something breaks.

---

## Daily (10 minutes)

```bash
python3 run.py agents      # did every agent run clean?
python3 run.py inbox       # review drafts
python3 run.py approve     # approve the good ones
python3 run.py send --limit 40
```

Look for `ERR` in the agent list. One error is noise; the same agent erroring
twice in a row is a problem to investigate.

## Weekly (45 minutes)

```bash
python3 run.py dashboard              # MRR, profit, progress to target
python3 run.py prospects --stage audited --limit 30
python3 run.py forecast --adds-per-month 2
```

Ask three questions:
1. Is profit tracking toward target, and if not, which funnel step is weak?
2. Are reports going out on schedule and are they good?
3. Is any client quiet? Quiet clients churn. Call them.

## Monthly (2 hours)

- Review every client's score trend. **Anyone flat for two months gets a call
  before they cancel, not after.**
- Reconcile the ledger against the bank and Stripe.
- Move 25–30% of profit to the tax account.
- Re-read one delivered report as if you were the client.
- Update prompt sets if the vertical's buyer language has shifted.

## Running the fleet continuously

**systemd (recommended on a VPS):**

```ini
# /etc/systemd/system/answerrank.service
[Unit]
Description=AnswerRank agent fleet
After=network-online.target

[Service]
Type=simple
User=answerrank
WorkingDirectory=/opt/answerrank
EnvironmentFile=/opt/answerrank/.env
ExecStart=/usr/bin/python3 run.py run
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now answerrank
journalctl -u answerrank -f
```

The orchestrator computes "due" from the database, not memory, so a restart
resumes cleanly rather than re-running everything.

## Backups

The entire business state is one SQLite file.

```bash
# nightly, via cron
sqlite3 data/answerrank.db ".backup /backups/answerrank-$(date +%F).db"
```

Keep 30 days. Test a restore once a quarter — an untested backup is not a backup.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `engines: ['mock']` | No API keys in the environment | Export the provider keys; check with `python3 -c "import os;print(os.environ.get('OPENAI_API_KEY'))"` |
| `BLOCKED FOR SEND` | `physical_address` not set | Edit `answerrank.yml` — this is a legal gate, not a bug |
| `send` refuses with DNS errors | SPF/DMARC missing or `p=none` | Fix DNS. Do not use `--skip-dns` to work around this |
| Scores implausibly high | Business name too generic and matching loosely | Use the full legal name; check `name_matches` against a sample answer |
| Scores all zero | Business genuinely invisible, or name mismatch | Run `audit --depth teaser` and read the test log |
| Audits slow | Engine timeouts | Lower `request_timeout`; drop the slowest engine |
| Agent erroring repeatedly | Check `run.py agents` for the message | Most often an expired API key or exhausted credit |
| Bounce rate climbing | List quality | Stop sending. Verify the list. Re-warm before resuming. |

## Cost control

API spend is booked automatically to the ledger under `api`. Check it:

```bash
python3 run.py dashboard   # see COST BREAKDOWN
```

If spend climbs unexpectedly:
- Lower `teaser_budget` on the Auditor (default 20/run)
- Reduce `prompts_per_audit`
- Drop an engine from `engines` in the config
- Set `probe_repeats: 1`

A full 10-prompt, 4-engine audit costs about **$0.06**. If you are spending more
than $40/month on API calls before 10 clients, something is looping.

## Scaling past $5k

| Bottleneck | Fix |
| --- | --- |
| You can't take enough calls | Commission-only appointment setter |
| List building eats time | VA at ~$400/mo to qualify prospects |
| Reports need manual review | Only review new clients' first two; trust the fleet after |
| Implementation requests | Raise Managed to $2,497 and subcontract the work |
| One vertical saturated | Add a second. The prompt sets are already built. |

## What never gets automated

Three things stay human permanently. Each is a place where an agent mistake is
expensive and a human judgement is cheap:

1. **Approving outreach.** One bad batch burns a domain permanently.
2. **Sales calls.** People buy from people, especially at $997/mo.
3. **Firing a client.** Rare, but it is a judgement call, not a rule.
