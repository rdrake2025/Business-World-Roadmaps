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

**Windows** — double-click **`start.bat`** in the project folder. No terminal
needed.

**Mac / Linux** — one command:

```bash
./start.sh
```

Either does everything: isolated environment, dependencies, tests,
configuration, diagnostics, and the server.

Or step by step:

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
python3 run.py setup               # interactive configuration
python3 run.py doctor              # what is still blocking you
export OPENAI_API_KEY=...          # ChatGPT
export ANTHROPIC_API_KEY=...       # Claude
export PERPLEXITY_API_KEY=...      # Perplexity
export SERPER_API_KEY=...          # Google AI Overviews + prospect discovery
python3 run.py run                 # 24/7
```

With no keys present, every engine falls back to a deterministic simulator, so
the whole system is demonstrable offline. Add keys and the same code paths hit
live engines.

## What the agents know

The agents reason from a cited knowledge layer (`answerrank/knowledge.py`)
rather than hardcoded strings: real 2026 benchmarks for average ticket,
lifetime value, acquisition cost, seasonality, buyer language and objections,
per trade.

That changes what the system can say. Instead of "you aren't visible in AI
search", an audit produces:

> At an average ticket of $1,600, that gap is worth an estimated $27,200 a year
> in first-job revenue — about 1.4 jobs a month.

…with its assumptions printed alongside, because a number a client cannot
interrogate is one they should not believe.

It also makes the system honest about where the business model works:

```bash
python3 run.py verticals          # which trades justify $997/mo, and on what argument
```

Twenty-two trades are encoded. At $997/mo eleven of them clear — some on
first-job revenue, some only on lifetime value, and the system says which,
because selling a dentist on first-job maths is a claim that falls apart the
moment they check it. The qualifier refuses to pitch the rest at that price:
pitching poor-fit prospects spends complaint-rate budget that cannot be bought
back.

A trade that fails at $997 is a pricing problem, not a dead market. Every one
of the twenty-two is sellable somewhere on the ladder, and `recommended_price`
finds the highest tier its own economics defend — $1,997 for a remodeler,
$297 for a garage door company. That turned eleven viable trades into
twenty-two.

## How the agents are trained

`answerrank/playbook.py` encodes the method, so the same discipline applies on
the four-hundredth prospect as on the fourth. It is drawn from this
repository's own `Sales_Business_Development_README.md`, which specifies BANT
as the qualification framework and names the two pitfalls this implementation
is built to avoid — broad targeting and weak follow-ups.

- **BANT**, scored from measured things rather than assumed ones: Budget from
  whether the trade's economics defend the price, Authority from how many
  people have to agree, Need from the audit, Timeline from seasonality. Every
  dimension returns the evidence behind it.
- **Objection handling** — every one of the 67 objections recorded across the
  22 trades has an answer that concedes the owner's point first. An objection
  argued with is an objection repeated.
- **Discovery questions** that make the prospect do the arithmetic themselves,
  because a number they say out loud is worth more than the same number in our
  email.
- **Sequence discipline**, enforced rather than documented: `sequence_check`
  runs against the system's own drafts and rejects a content-free nudge, an
  over-long message, a missing unsubscribe line or a broken wrap. A rule the
  agents are trained on but never measured against is a comment, not a rule.

```bash
python3 run.py playbook septic        # how to sell one trade
python3 run.py brief "Apex"           # the full read on one prospect
```

## Finding the next market

The first seven verticals were chosen by hand, which is a ceiling. Two agents
lift it — seven trades have since been promoted out of the candidate list and
into the served library on measured evidence.

**Explorer** tests the market model rather than trusting it. It samples real
businesses in a candidate trade, runs the same audit the paying product runs,
and reports what it measured. A trade can look ideal on paper — high ticket,
fragmented, big budgets — and turn out to be perfectly visible already, in
which case there is nothing to sell. Measuring costs fractions of a cent.

**Strategist** reads that evidence against what is commercially happening and
returns *one* move. A list of twelve opportunities is a way of avoiding a
decision.

```bash
python3 run.py markets      # candidates, measured, and what to do next
```

It caught a real inconsistency on its first run: the Scout was adding roofing
prospects at a price roofing cannot justify, which Outreach then filtered out
— API spend and pipeline noise generated for nothing. Discovery now selects on
the same economics qualification uses, and per-cycle waste went from ten
filtered prospects to zero.

## Run it from your phone

The fleet runs on your laptop; you manage it from your pocket.

```bash
./start.sh        # prints a link (and a QR code if `qrencode` is installed)
```

Open that link once on a phone on the same Wi-Fi. It stays signed in, and
"Add to Home Screen" makes it open like a native app.

### Two surfaces

**`/app`** — the console you operate: approve drafts, send, watch the number.

**`/ops`** — a live command deck showing what every agent is actually doing:
execution traces, durations, reliability, spend, and a streaming activity log.
Built on the principle that agent observability is about seeing real decisions
and real failures, not a prettier summary — so every line on it is a recorded
run, never decoration.

| Tab | What it's for |
| --- | --- |
| **Today** | What needs you now, fleet health, and the three actions |
| **Inbox** | Every draft with its evidence line — Approve or Skip with a thumb |
| **Pipeline** | Prospects by stage, and the hot leads — tap one for the full read |
| **Clients** | Health score per account, worst first, with the one action for each |
| **Brain** | What the fleet worked out: findings, the next move, required volume, where each trade should be priced |

Tapping a hot lead opens the qualification sheet: priority, ICP tier, BANT with
its evidence, whether the quoted price fits that trade, and the question to ask
next. It carries a reply box, so a reply that arrives on the phone can be
pasted straight in — the Concierge reads it, advances the prospect, and drafts
the response for approval without a laptop being involved. Money is one tap
from Brain; five tabs is the most a phone nav carries legibly.

**The console cannot bypass a compliance gate.** Sending from the phone runs
the same preflight as the command line: no postal address or failing DNS means
the button refuses, and says why.

Access is a single long token, minted on first run and held in the database.
It arrives once in the URL, is exchanged for an `HttpOnly` cookie, and never
appears in a URL again. Anyone on your network holding that link can approve
outreach — treat it like a password; restarting issues a new one.

## The agent fleet

| Agent | Every | Does |
| --- | --- | --- |
| `concierge` | 30m | Reads inbound replies, classifies intent, drafts the answer |
| `scout` | 6h | Finds local businesses in defensible verticals, dedupes by domain |
| `prospector` | 2h | Reads the contact page a business publishes and records the address |
| `auditor` | 1h | Teaser audits on prospects, full audits for clients |
| `fixer` | 6h | Generates JSON-LD schema, FAQ copy, GBP and citation plans |
| `reporter` | 12h | Renders branded monthly client reports |
| `outreach` | 4h | Drafts evidence-backed, CAN-SPAM-compliant email |
| `bookkeeper` | 24h | Bills clients, books costs, tracks the target |
| `retention` | 24h | Scores client health and names the one action per account |
| `explorer` | 12h | Samples candidate markets to find the next vertical worth entering |
| `analyst` | 12h | Reads recorded outcomes and reports what is actually converting |
| `strategist` | 24h | Reads the evidence and recommends the single next move |

The orchestrator runs them on independent schedules in one process. An agent
that crashes is recorded as a failed run; the fleet keeps going. "Due" is
computed from the database, so restarts resume rather than replay.

Order is deliberate. The Concierge runs first because an inbound reply outranks
every piece of new work in the queue — it is the only event a human is waiting
on. The Analyst runs late, once the tick has produced whatever it is going to,
and the Strategist runs last so its single recommendation is made with the
Analyst's findings already written.

### The three that close the loop

Everything else in the fleet *acts*. These three are what let it improve.

**Concierge** handles the moment a prospect replies — previously the largest
unmanaged gap in the business, since everything upstream exists to produce a
reply and a reply landed in an inbox and sat there. It classifies intent
conservatively (ambiguity routes to a human, never to an assumption),
suppresses instantly on an unsubscribe, and answers the objection hiding inside
most "questions". It drafts; it never sends.

**Analyst** is the only agent that asks whether the acting worked. It reads the
`outcomes` table and reports reply and win rates by trade and by sequence step —
and refuses to conclude below 25 sends, because acting on noise is worse than
acting on a benchmark, since it feels like evidence. It also turns the
$5,000/month goal into the only form that can be acted on: emails per day.

**Retention** scores client health continuously rather than reacting to notice,
because health deteriorates 60–90 days before a cancellation. Silence is the
leading indicator it weighs heaviest — not complaints, which at least mean the
client still expects something to change.

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
| `setup` | Interactive first-run configuration |
| `doctor [--probe]` | What is blocking you from operating |
| `verticals [--price N]` | Which trades justify which retainer, and where each should be priced |
| `markets [--price N]` | Candidate markets, measured, and the next move |
| `brief NAME` | Full qualification read on one prospect: fit, BANT, objections, questions |
| `reply NAME "text"` | Log an inbound reply; the Concierge classifies it and drafts the answer |
| `clients` | Client health scores, worst first, with the one action for each |
| `learn [--days N]` | What the recorded outcomes actually show |
| `playbook TRADE` | How to sell one trade: positioning, objections, discovery |
| `domain NAME --provider X` | Sending-domain setup: the exact DNS records, then whether they are live |
| `web` | Serve the site and the phone console |

## The finding that sells itself

Before anything else, the Auditor reads the prospect's own `robots.txt`. A
site that blocks the answer engines cannot be named in their answers however
good its content is, and it happens constantly — a plugin or a previous
agency pastes in a "block AI scrapers" rule, not knowing the same line
removes the business from the answers its customers are reading.

That finding leads the outreach when present, because it is a stronger and
more checkable claim than a low score:

> apexhvac.com blocks OAI-SearchBot, PerplexityBot in its own robots.txt.
> That removes it from ChatGPT search results; Perplexity answers and
> citations — not because of competition, but because the site asks them to
> leave.

The owner can verify it in ten seconds, and the fix is one line and free.
Giving it away is the point: it earns the paid conversation.

The distinctions here are encoded rather than assumed, because getting one
wrong would be disproven immediately and cost the account:

- Blocking `Google-Extended` does **not** remove a site from AI Overviews.
  That surface is served from the normal Googlebot index.
- Blocking `GPTBot` does **not** remove a site from ChatGPT search.
  `OAI-SearchBot` builds that index; GPTBot is the training crawler.
- A training-only block is reported as *not costing visibility*, in as many
  words.

A `robots.txt` that returns 403 is reported as unknown, never as all-clear.
A refusal is not an absence, and false reassurance is the one direction this
check must not be wrong in.

## Getting a real prospect you can actually write to

Local search results give a name, a website and a phone number. They never
give an email, and the outreach agent requires one — so in production every
real prospect was filtered out as uncontactable while the simulated fixtures,
which fabricate addresses, sailed through. The fleet looked healthy in every
dashboard and could not send one message to a real business.

**Prospector** does what a person does: opens the site, clicks Contact, reads
the address printed there. It obeys robots.txt, identifies itself honestly,
pauses between sites, and re-checks a business at most every 45 days.

It never guesses. `info@theirdomain.com` is right often enough to be tempting
and wrong often enough to be fatal — every wrong guess is a bounce, bounces
are capped at 2% before the sending domain is throttled wholesale, and a
guessed address is indistinguishable from a real one until the damage is
done. A business with no published address is recorded as exactly that, which
is a fact the operator can act on by calling the number already on file.

## One price per trade, not one price

Quoting every trade $997 meant half the library was unsellable and therefore
unprospected. `Settings.quote_for(vertical)` is now the single place that
decision is made, so the Scout, the qualifier and the copy cannot disagree
about what a prospect is being offered. The Scout prospects every trade with
a defensible tier, best-paying first — twenty trades rather than eleven.

## Turning the domain on

Double-click **SETUP-DOMAIN.bat** (Windows) or run **./setup-domain.sh**
(macOS, Linux). It asks for the domain and the mailbox provider, and nothing
else. From a terminal it is:

```bash
python3 run.py domain yourdomain.com --provider google
```

It is a separate file from the launcher on purpose. Domain setup is not a
one-shot — DNS takes minutes to hours to appear, so this is something you run,
go and add a record, and run again.

Prints the exact rows to paste into the registrar — MX, SPF, DKIM, DMARC —
with what each one is for, then checks live DNS and tells you which are
actually published. Run it again after adding them; it is idempotent and safe
to run as many times as it takes.

It refuses rather than warns. A domain that sends unauthenticated mail is not
recoverable — you buy a new one — so nothing sends until every blocking row
passes.

Two things it is strict about, because both are silent failures:

- **DKIM with an empty key is treated as missing.** `v=DKIM1; p=` means the
  key is *revoked* under RFC 6376, and it is sometimes published on a wildcard
  to say "we sign nothing here". Reporting that domain as authenticated while
  it sends unsigned mail would be the worst thing this check could do.
- **Lookups go over DNS-over-HTTPS**, not `dig`. `dig` does not ship with
  Windows, so the previous check could never pass on the machine this is
  actually run from — sending was blocked by a resolver that was never there.

### Warm-up is enforced, not suggested

A domain with no sending history that opens at 120 a day is read as a
compromised account, and that reputation does not come back. The cap ramps
over about a month — 10 a day, then 20, 40, 70, 100, then full — and the send
path will not exceed it. Day one is stamped in the database on the first real
send rather than set in the config, because a warm-up that can be reset by
editing a file is a warm-up that gets reset the first time the cap feels slow.

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
| [Deployment](business/07_DEPLOYMENT.md) | Laptop, VPS, Docker, backups, monitoring |
| [Service agreement](business/contracts/SERVICE_AGREEMENT.md) | Client contract template |
| [Client onboarding](business/contracts/CLIENT_WELCOME_EMAIL.md) | Welcome sequence and retention emails |

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
├── playbook.py        BANT, objection handling, sequence discipline
├── sending.py         The single path a message leaves by
├── agents/            The eleven workers
├── report/templates/  Client-facing HTML report
├── doctor.py          Preflight checks — what is blocking you
├── wizard.py          Interactive setup
├── budget.py          Runway, profit policy, quit threshold
└── schedule.py        .ics calendar generation

web/                   Public surface
├── app.py             WSGI: landing, RFC 8058 unsubscribe, lead capture
└── templates/         Landing, unsubscribe, privacy, terms

deploy/                systemd units, backup script
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
