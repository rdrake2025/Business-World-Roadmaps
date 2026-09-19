# AnswerRank

**Done-for-you AI search visibility for local service businesses, run by a fleet
of agents that operate 24/7.**

When someone asks ChatGPT, Claude, Perplexity or Google "who's the best plumber
in Charlotte?", two or three businesses get named. Everyone else is invisible —
and there is no page two to be on. AnswerRank measures whether a business is
being named, and does the work to change it.

- **Target:** $5,000/month profit on ~7 clients
- **Margin:** ~95% (a full 10-prompt, 4-engine audit costs $0.06; the retainer is $997)
- **Human time:** ~5 hours/week — sales calls and approving outreach

---

## Quick start

```bash
# Runs with zero API keys in simulation mode
python3 run.py tick --force        # run one full cycle of the fleet
python3 run.py dashboard           # MRR, profit, progress to target
python3 run.py forecast            # model the path to $5k/month

# Audit any real business and produce the sellable report
python3 run.py audit "Apex Heating & Air" Austin --state TX \
    --vertical hvac --website https://apexhvac.com --report
```

Going live:

```bash
python3 run.py init                # write answerrank.yml, then edit it
export OPENAI_API_KEY=...          # ChatGPT
export ANTHROPIC_API_KEY=...       # Claude
export PERPLEXITY_API_KEY=...      # Perplexity
export SERPER_API_KEY=...          # Google AI Overviews + prospect discovery
python3 run.py run                 # 24/7
```

With no keys present, every engine falls back to a deterministic simulator, so
the whole system is demonstrable offline. Add keys and the same code paths hit
live engines.

## The agent fleet

| Agent | Every | Does |
| --- | --- | --- |
| `scout` | 6h | Finds local businesses, dedupes by domain |
| `auditor` | 1h | Teaser audits on prospects, full audits for clients |
| `fixer` | 6h | Generates JSON-LD schema, FAQ copy, GBP and citation plans |
| `reporter` | 12h | Renders branded monthly client reports |
| `outreach` | 4h | Drafts evidence-backed, CAN-SPAM-compliant email |
| `bookkeeper` | 24h | Bills clients, books costs, tracks the target |

The orchestrator runs them on independent schedules in one process. An agent
that crashes is recorded as a failed run; the fleet keeps going. "Due" is
computed from the database, so restarts resume rather than replay.

## How the product works

1. **Probe** — ask 10 real buyer-intent questions ("My AC died in a heat wave —
   who do I call?") across four AI engines.
2. **Score** — a 0–100 Visibility Score from Presence (40%), Prominence (25%),
   Citation (20%) and Sentiment (15%), plus share of voice against the
   competitors who *are* being named.
3. **Fix** — generate `LocalBusiness` and `FAQPage` JSON-LD, answer-shaped FAQ
   copy written against the exact questions being lost, a Google Business
   Profile action list, and a citation gap list.
4. **Report** — a branded monthly report with the score, the trend, the
   competitor gap, and a prioritised action plan.

**The same audit engine sells the deal and delivers the service.** A free
4-prompt teaser produces the line that opens the cold email —

> *Apex Heating & Air appears in 0 of 4 AI answers for HVAC in Austin, TX.
> Summit Climate Co appears in 4.*

— for a fraction of a cent. Every improvement to the audit improves conversion
and retention at the same time.

## Commands

| Command | Purpose |
| --- | --- |
| `init` | Write a starter config |
| `tick [--force]` | Run one cycle of due agents |
| `run` | Run the fleet continuously |
| `agents` | List the fleet and recent runs |
| `audit NAME CITY [--report]` | Audit one business now |
| `prospects [--stage]` | Show the pipeline |
| `inbox [--full]` | Review drafted outreach |
| `approve` / `send` | Approve and deliver messages |
| `win NAME --plan growth` | Convert a prospect to a client |
| `dashboard` | KPIs and progress to target |
| `forecast` | Model the path to the profit target |
| `export AUDIT_ID` | Export an audit's deliverables |
| `budget-init` / `budget` | Personal + business budget, runway, milestones |
| `expense CAT AMOUNT` | Log a business expense |
| `schedule --start DATE` | Generate an .ics calendar for your phone |

## Safety rails

These are enforced in code, not policy, because each one is a mistake that ends
the business rather than costing a day:

- **Outreach is drafted, never auto-sent.** A human approves every batch. One
  runaway loop permanently burns a sending domain.
- **Sending is blocked** until a physical postal address is configured
  (CAN-SPAM) and SPF/DMARC pass on the sending domain.
- **Only businesses with a proven visibility gap are contacted.** No evidence,
  no email.
- **Rate limits** sit far below the 0.3% complaint and 2% bounce thresholds that
  trigger Gmail/Yahoo/Microsoft enforcement.
- **Bounced and unsubscribed addresses** are suppressed permanently and checked
  before every send.
- **Billing is idempotent per calendar month** — the fleet can run every hour
  for a year without double-charging anyone.

## Documentation

| Document | Contents |
| --- | --- |
| [Business plan](business/00_BUSINESS_PLAN.md) | Thesis, market, product, competition, risks |
| [Financial model](business/01_FINANCIAL_MODEL.md) | Unit economics, scenarios, path to $5k, tax reality |
| [Sales playbook](business/02_SALES_PLAYBOOK.md) | Email sequence, the call, objections, pricing rules |
| [Legal & compliance](business/03_LEGAL_COMPLIANCE.md) | Entity, CAN-SPAM, 2026 sender rules, contracts, claims |
| [30-day launch checklist](business/04_LAUNCH_CHECKLIST.md) | Day-by-day to first revenue |
| [Operations manual](business/05_OPERATIONS.md) | Daily rhythm, systemd, backups, troubleshooting |
| [Budget & schedule](business/06_BUDGET_AND_SCHEDULE.md) | Phased spending, runway, profit splits, quit threshold |

## Architecture

```
answerrank/
├── config.py          Settings; env > yaml > defaults; degrades to simulation
├── models.py          Domain dataclasses
├── store.py           SQLite persistence — the whole business is one file
├── prompts.py         Buyer-intent prompt generation per vertical
├── scoring.py         The Visibility Score
├── audit.py           The audit runner (teaser + full)
├── mailer.py          SMTP with RFC 8058 one-click unsubscribe
├── orchestrator.py    The 24/7 scheduler
├── cli.py             Operator command line
├── engines/           ChatGPT, Claude, Perplexity, Google AI Overviews, mock
│   └── base.py        Answer parsing — the core IP
├── agents/            The seven workers
└── report/templates/  Client-facing HTML report
```

## Requirements

Python 3.11+. Only `requests`, `jinja2` and `PyYAML` — everything else is
standard library. Provider SDKs are deliberately avoided; the wire formats are
simple JSON and one fewer dependency is one fewer thing to break at 3am.

```bash
pip install -r requirements.txt
python3 -m unittest discover -s tests -v   # 43 tests
```

## Honest limitations

- **AI answers are non-deterministic.** The same prompt can return different
  businesses on different runs. Scores are reported as trends; set
  `probe_repeats: 3` for stabler numbers at 3× the cost.
- **Google AI Overviews has no first-party API.** It is read through a SERP
  provider, so coverage depends on that provider surfacing the block.
- **No engine exposes "why" it named a business.** The recommended fixes are
  grounded in how retrieval-based systems work, not in documented ranking
  factors. Treat the score as the measurement and the fixes as informed
  practice.
- **Nobody can guarantee placement in an AI answer.** Say so, in writing, to
  every client.
