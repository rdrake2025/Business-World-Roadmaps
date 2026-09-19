# 30-Day Launch Checklist

The order matters. Weeks 1–2 are setup with zero revenue; week 3 is when the
business actually starts. Do not reorder to feel productive — the single most
common failure is spending three weeks on a logo and never sending an email.

Estimated total time: **25–35 hours over 30 days.**

---

## Week 1 — Foundation (8–10 hours)

**Day 1–2: Entity and money**
- [ ] Form the LLC in your home state
- [ ] Apply for an EIN (free, IRS.gov — do not pay a service)
- [ ] Open a business bank account
- [ ] Sign up for Stripe; verify the account
- [ ] Set up accounting; create a separate tax-reserve account

**Day 3–4: Domains and email**
- [ ] Buy the primary domain
- [ ] Buy a **separate sending domain** (`-mail`, `-hq`, or `get-` variant)
- [ ] Set up Google Workspace on the sending domain
- [ ] Configure **SPF, DKIM, DMARC at `p=quarantine`** on the sending domain
- [ ] **Begin email warmup today.** It takes 2–3 weeks and gates everything else.
      Start at 10/day.

> Warmup is the long pole. Start it on day 3 even though you won't send real
> outreach until day 18.

**Day 5–7: The platform**
- [ ] Clone this repo to a $6 VPS
- [ ] `python3 run.py init` and fill in every field
- [ ] Add API keys: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `PERPLEXITY_API_KEY`, `SERPER_API_KEY` ($50 total float is plenty)
- [ ] `python3 -m unittest discover -s tests` — confirm 43 tests pass
- [ ] `python3 run.py tick --force` — confirm the fleet runs
- [ ] **Audit 3 businesses you know personally.** Read the reports critically.
      Would you pay $997 for this? If not, fix it now, before strangers see it.

## Week 2 — Proof and positioning (7–9 hours)

**Day 8–10: Pick your vertical and market**
- [ ] Choose **one** vertical (HVAC, plumbing, dental, legal, roofing) and **2–3
      metros**. Do not start broad — specificity is what makes the email land
      and the case study credible.
- [ ] Run 20 audits in that vertical. Find the patterns: what do the *visible*
      businesses have that the invisible ones don't?
- [ ] Write those patterns down. That is your expertise, and it is what you'll
      say on calls.

**Day 11–12: Sales assets**
- [ ] One-page website: what it is, who it's for, the three tiers, a booking link
- [ ] Publish a privacy policy and terms
- [ ] Draft the client service agreement (see `03_LEGAL_COMPLIANCE.md`); send for
      lawyer review
- [ ] Set up a calendar booking link
- [ ] Create Stripe payment links for all four tiers

**Day 13–14: The free-audit offer**
- [ ] Build a landing page: "Free AI Visibility Audit for [Vertical] in [City]"
- [ ] Wire the form to your inbox
- [ ] **Build the unsubscribe endpoint** at `/unsubscribe` and connect it to the
      suppression list. *(Legally required. Do not send before this works.)*

## Week 3 — First contact (6–8 hours)

**Day 15–17: Build the list**
- [ ] Run `scout` against your chosen vertical and metros, or import a CSV via
      `ANSWERRANK_SEED_FILE`
- [ ] Target **200–300 qualified prospects**
- [ ] Verify email deliverability on the list (bounces above 2% get you filtered)
- [ ] Let `auditor` run teaser audits overnight

**Day 18–21: Start sending**
- [ ] Confirm warmup is complete and DNS passes: `python3 run.py send --dry-run`
- [ ] `python3 run.py inbox --full` — **read every draft before approving.**
      Read them all for the first week; they go out under your name.
- [ ] `python3 run.py approve` then `python3 run.py send --limit 20`
- [ ] Ramp: 20/day → 40 → 60 → 100 over the week
- [ ] Watch bounce and complaint rates daily. Stop immediately if bounces
      exceed 2% or complaints exceed 0.1%.

> **The first 50 emails are a test, not a campaign.** If nobody replies, the
> problem is the subject line or the targeting — not the volume. Fix it before
> sending 500 more.

## Week 4 — First revenue (5–8 hours)

**Day 22–26: Convert**
- [ ] Reply to every response within 2 hours during business hours
- [ ] Send the full report to anyone who asks; offer a 20-minute call
- [ ] Run calls per `02_SALES_PLAYBOOK.md`. **Ask for the card on the call.**
- [ ] `python3 run.py win "<business>" --plan growth` on every close

**Day 27–30: Deliver and review**
- [ ] Let `fixer` and `reporter` produce the first client deliverables
- [ ] **Review the first report by hand before it goes out.** Every time, for the
      first three clients.
- [ ] Send it with a personal note and a 15-minute walkthrough offer
- [ ] `python3 run.py dashboard` — where do you actually stand?
- [ ] Write down what worked and what didn't. Adjust the sequence.

---

## Day 30 targets

| Metric | Target | Acceptable |
| --- | --- | --- |
| Prospects audited | 250 | 150 |
| Emails sent | 400 | 250 |
| Replies | 8–15 | 4 |
| Calls booked | 4–8 | 2 |
| **Clients closed** | **2–3** | **1** |
| MRR | $1,500–$2,500 | $499 |

**One client by day 30 puts you on the pessimistic curve, which still clears
$5k inside a year.** Two puts you on the base case and at target by month 4.

**Zero clients by day 30 is a signal, not a failure** — but you must diagnose
which step broke:

| Symptom | Diagnosis | Fix |
| --- | --- | --- |
| Emails not delivered | DNS or reputation | Stop. Fix SPF/DKIM/DMARC. Re-warm. |
| Delivered, no replies | Subject line or targeting | Rewrite the subject. Verify the audits show a real gap. |
| Replies, no calls | The report isn't landing | Add competitor detail; lead with the gap. |
| Calls, no closes | The pitch | Talk less. Show the test log. Ask for the card. |

Work the earliest broken step first. Fixing the pitch while emails are landing
in spam wastes a month.

## Ongoing weekly rhythm (post-launch)

| Day | Task | Time |
| --- | --- | --- |
| Mon | Approve the week's outreach batch | 30 min |
| Tue–Thu | Calls, replies, daily approvals | 45 min/day |
| Fri | `dashboard`, review reports going out, adjust | 45 min |
| — | Everything else | *The fleet* |

**~5 hours/week once running.**
