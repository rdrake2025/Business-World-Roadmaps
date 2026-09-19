# Deployment

Three ways to run this, in the order you will actually need them.

---

## Phase 0 — your laptop ($0)

This is where you start, and it is enough to land your first client.

```bash
git clone <repo> && cd Business-World-Roadmaps
pip install -r requirements.txt
python3 run.py setup            # interactive; writes answerrank.yml
python3 run.py doctor           # what is still blocking you
python3 run.py tick --force     # run the fleet once
```

The fleet only needs to be running when you are approving and sending, and you
are at the laptop for that anyway. A server buys you nothing yet.

**The one exception:** the unsubscribe endpoint has to be publicly reachable
before you send a single email. Serve it locally and expose it with a free
tunnel while you are still in Phase 0:

```bash
python3 run.py web              # serves on :8000
# then, in another terminal, any free tunnel:
#   cloudflared tunnel --url http://localhost:8000
```

Point `website:` in `answerrank.yml` at that URL and re-run
`python3 run.py doctor --probe` to confirm it answers.

> A tunnel is fine for the first few weeks. Move to real hosting before you
> pass ~100 sent emails — a tunnel that drops while an unsubscribe link is
> live is a compliance problem.

## Phase 1 — a $6 VPS (after your first client)

Your first client's payment covers this many times over.

```bash
# on the server, as root
adduser --system --group --home /opt/answerrank answerrank
git clone <repo> /opt/answerrank
cd /opt/answerrank
pip install -r requirements.txt

cp .env.example .env            # fill in keys and SMTP
python3 run.py setup

cp deploy/answerrank-*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now answerrank-fleet answerrank-web
```

Check it:

```bash
systemctl status answerrank-fleet
journalctl -u answerrank-fleet -f
curl localhost:8000/health
```

Put a reverse proxy in front for TLS (Caddy is two lines and gets you a
certificate automatically):

```
yourdomain.com {
    reverse_proxy localhost:8000
}
```

### Docker instead

```bash
cp .env.example .env            # fill it in
docker compose up -d
docker compose logs -f fleet
```

Two services share one database volume: `web` serves the public surface,
`fleet` runs the agents. `./data` is mounted — **back it up, or a redeploy
loses the business.**

## Backups

The entire business is one SQLite file. There is no excuse for not having this.

```bash
crontab -e
# 0 3 * * * /opt/answerrank/deploy/backup.sh
```

Keeps 30 nightly gzipped snapshots and prunes older ones. It uses SQLite's
`.backup`, which is safe on a live database — `cp` is not.

**Test a restore once a quarter.** An untested backup is not a backup:

```bash
gunzip -c backups/answerrank-2026-10-01-0300.db.gz > /tmp/restored.db
sqlite3 /tmp/restored.db "select count(*) from prospects;"
```

## What must never be committed

Already covered by `.gitignore`, but know why:

| Path | Why |
| --- | --- |
| `data/` | Prospect contact details and your full financial ledger |
| `answerrank.yml` | Your business address and sending identity |
| `budget.yml` | Your personal income and expenses |
| `.env` | API keys and your SMTP password |
| `backups/` | All of the above, historically |

Client credentials (GBP access, CMS logins) belong in a password manager and
**never** in this repository or its database.

## Health and monitoring

| Check | Command |
| --- | --- |
| Web alive | `curl -f localhost:8000/health` |
| Fleet running | `systemctl is-active answerrank-fleet` |
| Agents healthy | `python3 run.py agents` — look for `ERR` twice in a row |
| Spend | `python3 run.py dashboard` — the cost breakdown |
| Everything | `python3 run.py doctor` |

The Docker image has a `HEALTHCHECK` that polls `/health`, so an orchestrator
restarts the container if the web surface stops answering.

## Upgrading

```bash
cd /opt/answerrank
git pull
pip install -r requirements.txt
python3 -m unittest discover -s tests    # confirm green before restarting
systemctl restart answerrank-fleet answerrank-web
```

The database migrates itself — the schema uses `CREATE TABLE IF NOT EXISTS` and
stores rich fields as JSON, so a new field never requires a migration step.

Restarting is always safe: the orchestrator computes what is due from the
database, not from memory, so a restart resumes rather than replays.
