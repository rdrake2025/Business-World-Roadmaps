# Budget, Runway & Schedule

Written for a specific situation: **~$2,500/month from a 9-5, $250/month rent,
a laptop and a phone, and not much slack.** Every number below is checkable with
`python3 run.py budget` once you have entered your real figures.

---

## 1. The core decision: spend nothing until the channel is proven

The single most common way this kind of business dies is spending $800 on an
LLC, insurance, a logo and three SaaS subscriptions *before* finding out whether
anyone replies to the emails. Then the money is gone, the channel is untested,
and the whole thing gets abandoned.

So the spending is staged, and **each stage is paid for by the one before it.**

| Phase | Trigger | One-time | Monthly |
| --- | --- | --- | --- |
| **0 — Prove the channel** | Start here | **$47** | **$48.40** |
| 1 — First client signed | A client has paid | $500 | $30 |
| 2 — Three or more clients | ~$2,000 MRR | $0 | $98 |

### Phase 0 in full — $47 once, $48.40/month

| Item | Cost |
| --- | --- |
| Sending domain (1 year) | $12 one-time |
| API credits float | $35 one-time |
| Google Workspace, 1 seat (month to month) | $8.40/mo |
| Domain amortised | $1.00/mo |
| API usage (20 prospect checks a day) | ~$33/mo |
| Server (unsubscribe link + 24/7 fleet) | $6.00/mo |

**What you deliberately do NOT buy yet:**

- **No LLC.** You can legally test as a sole proprietor. Form the entity when
  money is actually coming in — the first client pays for it.
- The **$6 server is not optional**, even at zero clients: every email's
  unsubscribe link must work from the public internet, and a laptop cannot
  serve it. `deploy/SERVER.md` sets it up without typing commands on it.
- **No insurance, no logo, no CRM, no paid ads, no email tool.**

Every check searches the web live, the way ChatGPT and Google answer a real
customer, so the numbers are what a customer sees. That costs about **5.5 cents
per prospect** and about **$1.50 per client's monthly audit** (each question
asked three times, because AI answers change run to run). The daily cap,
`teaser_audits_per_day` (default 20), is the one dial on API spend: each extra
10 a day is about $17 a month.

## 2. Your runway

On $2,500 take-home with $250 rent, a realistic monthly picture:

| | |
| --- | --- |
| Take-home | $2,500 |
| Rent | $250 |
| Food | $350 |
| Transport | $200 |
| Utilities + internet | $120 |
| Phone | $50 |
| Personal / other | $200 |
| **Total living costs** | **$1,170** |
| **Disposable** | **$1,330/month** |

Against a $48.40/month burn, your disposable income covers the business **27
times over**. This never touches savings, and there is no realistic scenario
where Phase 0 puts you under financial pressure.

> Replace every line above with your real numbers:
> `python3 run.py budget-init` then edit `budget.yml`. Guesses produce a runway
> figure you cannot trust. The file is gitignored — it never leaves your machine.

**Your $250 rent is a genuine strategic advantage.** Most people attempting this
are carrying $1,200–2,000/month in rent and cannot afford to be patient. You can.
Patience is what lets you refuse a bad client and keep the sequence honest.

## 3. Tracking what you spend

Business costs are logged automatically by the Bookkeeper agent — API spend,
processing fees and fixed costs all land in the ledger without you typing
anything. For anything you pay for outside the system:

```bash
python3 run.py expense domain 12 --note "sending domain, 1yr"
python3 run.py expense software 8.40 --note "google workspace"
python3 run.py expense api 35 --note "initial credit float"

python3 run.py dashboard    # see the 30-day cost breakdown
python3 run.py budget       # personal + business together
```

Log it the day you spend it. A ledger you update monthly is a ledger you guess at.

## 4. What to do with profit

The rule changes as the business stops being fragile. `run.py budget --profit N`
gives you the split for any month.

| Monthly profit | Tax | Business reserve | Reinvest | To you |
| --- | --- | --- | --- | --- |
| Under $1,000 | 30% | 70% | 0% | **0%** |
| $1,000–$3,000 | 30% | 20% | 30% | 20% |
| $3,000–$5,000 | 30% | 10% | 30% | 30% |
| Over $5,000 | 30% | 5% | 20% | **45%** |

**Take nothing out below $1,000/month.** Build a $1,000 buffer first. A business
with no reserve dies to its first surprise — a chargeback, a failed payment, a
month where nobody closes.

**The 30% tax reserve is not optional and not negotiable.** Move it the day you
get paid, into a separate account you do not have a card for. Business profit is
pre-tax; a self-employed tax bill you did not reserve for is how people end up
owing money they have already spent.

## 5. When can you actually quit the job?

This is the question underneath everything, so be precise about it.

| | |
| --- | --- |
| Your take-home | $2,500/mo |
| Business profit that genuinely *matches* it | **$3,571/mo** (profit is pre-tax) |
| Safe to quit at | **$5,357/mo** |
| Sustained for | **3 consecutive months** |
| With cash banked | **$15,000** (6 months of living costs) |

$5,000/month in business profit is roughly **$3,500/month in your pocket** after
tax. That beats your job — but business income is variable and a wage is not.
Matching them dollar for dollar is a pay cut in disguise.

**Do not quit at $5,000.** Quit at ~$5,400/month sustained three months with six
months of living costs banked. At $250 rent, that buffer is far easier for you to
build than for almost anyone else attempting this.

### The milestone ladder

| Profit | Clients | What it actually means |
| --- | --- | --- |
| $0 | 0 | Costs $12/mo. Funded from your job. Testing phase. |
| $466 | 1 | Business is self-funding and pays for the LLC. |
| $1,400 | 2 | Buffer built. **Proof the channel repeats — the hardest milestone.** |
| $2,800 | 4 | Matches your take-home pre-tax. Do not quit yet. |
| $3,571 | 5 | Genuinely replaces your pay after tax. Still do not quit. |
| $5,000 | 6 | Target. ~$3,500/mo in your pocket. |
| $5,357 | 8 | Safe to leave the job, after 3 months here with $15k banked. |

**Client number two matters more than client number six.** One client can be
luck. Two is a repeatable channel, and everything after that is arithmetic.

## 6. Your schedule

```bash
python3 run.py schedule --start 2026-09-21
```

Writes an `.ics` file you import straight into your phone. It is built around a
9-5 — nothing conflicts with working hours.

| When | Block | Time |
| --- | --- | --- |
| Mon–Fri 06:30 | Morning ops — approve, send, check replies | 20 min |
| Mon–Fri 12:15 | Reply check | 10 min |
| Tue & Thu 17:30 | Sales calls | 90 min |
| Saturday 09:00 | Deep work — dashboard, pipeline, fix the funnel | 2 hrs |
| **Sunday** | **Rest. Deliberately empty.** | — |
| 1st Saturday 11:15 | Monthly close — bill, reconcile, move tax reserve | 45 min |

Plus 14 dated launch tasks across your first 30 days. Heavy setup work lands on
Saturdays; short tasks take weekday evenings.

**Roughly 6 hours a week.** Every calendar entry contains the exact commands for
that block, so you never need to go and find another document.

### Why the evening sales window

Owners of home service businesses are off the tools and not yet at dinner
between 5:30 and 7:00pm. It is the best calling window you have, and it happens
to be after your own workday. This is the main reason HVAC and plumbing are
better first verticals for you than something office-based.

### Why Sunday is in the calendar

A schedule with no rest day gets abandoned in week three. Six days a week is
sustainable for a year; seven is sustainable for about a month. This business
needs the year, and the rest day is what buys it.

## 7. The first 90 days, financially

| Month | Spend | Revenue | Net | What is happening |
| --- | --- | --- | --- | --- |
| 1 | ~$39 | $0 | **−$39** | Setup, warmup, first 400 emails |
| 2 | ~$48 | $499–997 | **+$450–950** | First client. Pays for the LLC. |
| 3 | ~$84 | $1,000–2,000 | **+$920–1,900** | Second client. Channel proven. |

**Your total downside is about $100.** That is the entire financial risk of
finding out whether this works. Against a $1,330/month disposable income, it is
not a meaningful bet — which is exactly why the phased structure matters. The
worst realistic outcome is losing a month of evenings and $100.
