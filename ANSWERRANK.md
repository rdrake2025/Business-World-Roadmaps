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
| `onboarder` | 30m | Writes the welcome the hour a client signs, not the week after |
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
| `researcher` | 6h | Runs a researcher against every agent and reports what holds |

The orchestrator runs them on independent schedules in one process, started
by the same window that serves the console — so double-clicking the launcher
runs the business, not just the pages.

Four properties make unattended operation real rather than claimed, and each
is verified by experiment as well as by test:

- **A crash is contained.** An agent raising is recorded as a failed run and
  the fleet continues. Tested against `RuntimeError`, `MemoryError` and
  `RecursionError` — the last two escape a narrower `except`.
- **A hang is contained.** A crash is an exception; a hang is simply never
  returning, which no `except` catches. Every agent carries a time budget,
  and one that exceeds it is abandoned, recorded, and not started again while
  the stuck thread is still alive.
- **A restart resumes.** "Due" is computed from the database, not from
  memory. Fifteen ticks after a restart produced zero repeat runs where a
  naive loop would have produced two hundred.
- **A signal is honoured.** SIGINT and SIGTERM finish the current agent and
  exit cleanly, so a stop never lands mid-write.

Order is deliberate. The Concierge runs first because an inbound reply outranks
every piece of new work in the queue — it is the only event a human is waiting
on. The Analyst runs late, once the tick has produced whatever it is going to,
and the Strategist runs last so its single recommendation is made with the
Analyst's findings already written.

### A researcher for every agent

The fleet acts. The Analyst measures the funnel. Nothing asked whether each
*individual* agent was doing its own job well — so a Scout finding unpitchable
businesses, an Auditor asking questions nobody is ever named in, or a
Retention model that flags nothing before a client leaves would all keep
running and reporting success for months.

Each doing-agent is now shadowed by a researcher that reads the evidence that
agent leaves in the database and answers one question about it:

| Researcher | The question it exists to answer |
| --- | --- |
| concierge | Are inbound replies being read correctly? |
| onboarder | Do new clients actually hear from us? |
| scout | Is discovery finding businesses actually worth pitching? |
| prospector | Can the businesses we find actually be reached? |
| auditor | Do the questions we ask measure anything? |
| fixer | Does the work we deliver actually move the score? |
| reporter | Do the monthly reports start a conversation? |
| outreach | Which part of the sequence earns replies? |
| bookkeeper | Is any cost growing faster than the business? |
| retention | Does the health score see a churn coming? |
| explorer | Were our guesses about a market right when we measured it? |
| analyst | Is the Analyst concluding on enough evidence? |
| strategist | Is the recommended move ever acted on? |

They are subordinate: they investigate and report, they never act. Acting is
the operator's decision, or the Strategist's. A single coordinator runs all
thirteen so the fleet stays legible — twenty-six entries in the agent list
would be a worse tool, not a better one — while each researcher remains a
separate, named, separately tested unit.

**A researcher with insufficient evidence returns nothing.** Silence is the
correct and common output. Thirteen researchers each inventing a finding every
cycle would be thirteen things the operator stops reading by the end of the
first week, and the one real finding would be lost among twelve pieces of
filler. Every finding carries the arithmetic it rests on, so the reasoning can
be checked rather than trusted.

```bash
python3 run.py research --refresh
```

A test asserts the pairing is exact: every agent in the fleet has exactly one
researcher, and no researcher shadows an agent that does not exist.

### What it does not survive

Being honest about the boundary: the fleet runs as long as the process runs.
Closing the window stops it, and a laptop that sleeps stops it too. Because
restarts resume rather than replay, an intermittently-running laptop loses
throughput rather than data — the work simply happens more slowly.

Continuous operation needs a machine that stays awake, which is the $6/month
server in Phase 1 of the budget, triggered by the first paying client. The
systemd units in `deploy/` are for that machine. Until then, a laptop left
open overnight is the honest description.

## The three that close the loop

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
| `win NAME --plan growth` | They said yes: sign them up (awaiting payment; `--plan pilot` is free) |
| `paid NAME` | Their payment arrived: they go live and count as revenue |
| `keys` | Save the mailbox password and API keys (or double-click KEYS.bat) |
| `case-study NAME` | Before/after write-up for a client — or "too early", or "don't publish" |
| `server-script --domain D` | Write the one file that sets up the always-on server (deploy/SERVER.md) |
| `console-link` | Print the phone console address with its login |
| `simulate [--sales N]` | Run made-up sales through the real agents (or double-click SIMULATE.bat) |
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

## From yes to paid to delivered

What happens after someone says yes, end to end:

1. **They say "sign us up".** The Concierge answers with the payment link for
   their plan (set the links once with KEYS.bat). You tap **Sign them up** on
   the phone. They are now *waiting for payment* — not revenue, not welcomed.
2. **They pay.** With a read-only Stripe key saved, the Bookkeeper sees it by
   itself within two hours. Without one, tap **They paid** on the Clients tab.
   One reminder goes out after 3 days; after 10 you are told to call.
3. **They go live.** Welcome email, first full audit, month-1 files.
4. **Every month they get an email**, not just a file on your laptop: what
   changed, what's live on their website, what's next — and, until the fixes
   are live, the two files and the steps for *their* website builder
   (WordPress, Wix, Squarespace, GoDaddy, Shopify, Webflow…).
5. **Their homepage is checked daily** for the fixes. A client three weeks in
   with nothing live is flagged in Retention with a ten-minute call to fix it.
6. **Replies are read for you** once KEYS.bat has switched it on: quoted text
   stripped, out-of-office ignored, bounce notices counted toward the bounce
   brake, and mail from strangers listed rather than dropped.

The first clients should be **pilots** (`--plan pilot`, free): `case-study
NAME` then measures before and after like for like, and says plainly when
it is too early or when the result should not be published.

To send for real, the unsubscribe link has to work from the internet, which
means a small server: see **deploy/SERVER.md** (about $6/month, no terminal).

## What the agents are trained to deliver

`playbook.py` trained them to sell. `method.py` trains them to deliver, and it
exists for a commercial reason: a client paying a retainer for twelve months
was receiving roughly the same six files every month. That is the churn
mechanism the Retention agent names in as many words — *they are paying for
movement they cannot see* — and it arrives on a 60-to-90 day delay, long
before anyone asks to cancel.

The work is sequenced into an arc, each month doing something the last did
not:

| Month | Focus |
| --- | --- |
| 1 | Make the site readable — crawler access, LocalBusiness schema, GBP |
| 2 | Answer the questions being lost — FAQ copy, FAQPage schema, service pages |
| 3 | Make the business resolvable — NAP consistency, citations, trade directories |
| 4 | Give the engines proof to quote — review velocity and responses |
| 5 | Widen the surface — service-area pages, described job galleries |
| 6 | Authority off your own site — supplier locators, local press |

Two rules in here are load-bearing:

**Time-to-effect is stated and never shortened.** Structured data shows up
when an engine next crawls, which is days to weeks. Review velocity compounds
over months. A client told to expect results in thirty days and shown none is
a client who cancels in month three — the overpromise causes the churn it was
meant to prevent.

**Every lever says who does the work.** A plan full of owner tasks is a plan
that does not get done, and then the retainer looks worthless. The client's
own time is capped and shown to them: about 80 minutes in month one, 15 in
month two.

The arc is a default, not a script. A blocked `robots.txt` moves to the front
of whatever month it is found in, because nothing else can work while it
holds.

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
