# AnswerRank — Business Plan

**One line:** Done-for-you AI search visibility for local service businesses.

**Target:** $5,000/month in profit within 4–6 months, on ~7 clients.

---

## 1. The opportunity

Two facts, both established in 2026 market data, create a window:

**Search behaviour moved.** Gartner predicted traditional search volume would
fall 25% by 2026; that prediction has landed. Google AI Overviews now appear on
roughly half of US searches, and ChatGPT handles on the order of 700M weekly
queries. A growing share of "who should I call for X near me" ends in an AI
answer naming two or three businesses — with no page two to be on.

**The tooling is aimed at the wrong customer.** Every AI-visibility platform on
the market — Profound (from ~$399/mo into the thousands), Ahrefs Brand Radar
($699/mo on top of a base subscription), SE Visible ($79/mo), Surfer ($99/mo per
domain) — is *self-serve software for marketers*. It hands you a dashboard.

An HVAC owner in Tampa will never log into a dashboard, interpret a share-of-voice
chart, or hand-write JSON-LD. They have a truck, a phone that should ring, and no
marketing employee.

**The gap:** nobody is selling *done-for-you* AI visibility to the local service
businesses who are both most exposed to the shift and least equipped to respond.

## 2. Why local service businesses

| Factor | Why it matters here |
| --- | --- |
| Urgency | A missed call is a lost job worth $300–$15,000. The ROI math takes 30 seconds. |
| Budget | Home services, dental and legal already pay $2,000–$6,000/mo retainers for automation and marketing. A $499–$1,997 visibility retainer is a small line item. |
| Volume | 500,000+ home service businesses in the US alone, before dental, legal, medical and insurance. |
| Low sophistication | They cannot self-serve this, which is exactly why a service exists. |
| Measurable | "You appear in 2 of 10 AI answers; your competitor appears in 9" needs no explanation. |

## 3. The product

A monthly retainer built on one repeatable pipeline:

1. **Probe.** Ask 10 real buyer-intent questions ("Who is the best plumber in
   Charlotte?", "My AC died in a heat wave — who do I call?") across ChatGPT,
   Claude, Perplexity and Google AI Overviews.
2. **Score.** Compute a 0–100 **Visibility Score** from four weighted components
   — Presence (40%), Prominence (25%), Citation (20%), Sentiment (15%) — plus
   share of voice against the competitors who *are* being named.
3. **Fix.** Generate the assets that move the score: `LocalBusiness` and
   `FAQPage` JSON-LD, answer-shaped FAQ copy written against the exact questions
   they're losing, a Google Business Profile action list, and a citation gap list.
4. **Report.** A branded monthly report showing the score, the trend, the
   competitor gap, and a prioritised action plan.

Steps 1–4 are fully automated by the agent fleet in this repository.

### Why this retains

Most audit products churn in month two because the problem is diagnosed once.
This one doesn't, for three structural reasons:

- **The target moves.** Model updates, competitor activity and review velocity
  change visibility continuously. Last month's score is not this month's.
- **The report shows a trend.** A number that moves is a reason to keep paying;
  a number delivered once is not.
- **The fixes are ongoing work.** Schema, content, GBP and citations are a
  programme, not a one-off.

## 4. Pricing ladder

| Tier | Price | What they get | Who it's for |
| --- | --- | --- | --- |
| **Audit** | $297 one-time | Full audit + report + all deliverables | Toe-dippers; converts to retainer |
| **Starter** | $499/mo | Monthly audit, report, schema + FAQ refresh, 10 prompts | Single-location SMB |
| **Growth** | $997/mo | Starter + 20 prompts, competitor tracking, quarterly strategy call | The default sale |
| **Managed** | $1,997/mo | Growth + implementation done for them, multi-location, priority support | Multi-location and high-ticket verticals |

The $297 audit exists to make "yes" cheap. It is priced to cover attention, not
to be a business; roughly 30–40% of audit buyers should upgrade within 60 days
because the report ends with a list of things they do not want to do themselves.

## 5. Unit economics

At the **Growth** tier ($997/mo):

| Line | Amount |
| --- | --- |
| Revenue | $997.00 |
| API/delivery cost | −$18.00 |
| Payment processing (2.9% + $0.30) | −$29.21 |
| **Contribution margin** | **$949.79 (95%)** |

Fixed overhead is ~$138/mo (sending infrastructure, hosting, domain, accounting).

**$5,000/month profit = 6 Growth clients**, or a realistic blend of ~7–8 clients
across Starter and Growth. See `01_FINANCIAL_MODEL.md` for scenarios.

Measured cost of a full 10-prompt, 4-engine audit: **$0.06**. The gross margin is
not a projection — it is arithmetic on a metered cost.

## 6. Go-to-market

The acquisition loop is the product's own audit engine, which is the structural
advantage of this business:

```
Scout finds business  →  free 4-prompt teaser audit  →  personalised email
citing their real result  →  reply  →  full audit  →  retainer
```

The cold email does not say "we do AI SEO". It says:

> *Apex Heating & Air appears in 0 of 4 AI answers for HVAC in Austin, TX.
> Summit Climate Co appears in 4.*

That is a measured fact about their business, produced for a fraction of a cent,
and it is why this converts where generic agency outreach does not. **We only
contact businesses where the audit proved a gap** — enforced in code, not policy.

Channels, in order of expected efficiency:

1. **Evidence-led cold email** (primary). 120/day ceiling, 3-step sequence.
2. **Vertical-specific content**: "Is your HVAC company invisible to ChatGPT?"
   ranks for the exact anxiety and is cheap to produce.
3. **Partnerships**: web design shops and local marketing agencies already serve
   these businesses and cannot deliver this. Refer at 20%.
4. **Trade associations and Facebook groups** for each vertical.

## 7. Competition

| Competitor | Price | Why we win |
| --- | --- | --- |
| Profound, Ahrefs Brand Radar | $399–$699+/mo | Enterprise self-serve. No SMB motion, no done-for-you delivery. |
| SE Visible, Surfer | $79–$99/mo | Cheaper, but it's a dashboard — the client still does all the work. |
| Local SEO agencies | $500–$2,500/mo | Optimising for a results page, not for AI answers. Most cannot explain the difference. |
| Doing nothing | $0 | The default, and the one we actually displace. |

The honest competitive risk is that the $79–$99 tools add a service layer, or a
local SEO agency bolts this on. Both are 12–18 month moves, and neither has the
audit-as-lead-magnet loop. The durable moat is the delivery system plus vertical
specialisation, not the scoring formula.

## 8. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| **Engine APIs change or restrict** | Four engines behind one interface; losing one degrades the score, doesn't break it. Google AI Overviews already routes through a SERP provider. |
| **Answers are non-deterministic** | `probe_repeats` averages multiple runs; the score is reported as a trend, never as a guarantee. |
| **Cold email deliverability collapses** | Hard caps well under the 0.3% complaint threshold, SPF/DKIM/DMARC enforced in preflight, human approves every batch. Content channel as the hedge. |
| **Client asks "can you guarantee rank #1?"** | No, and we say so in writing. We sell measurement and the work that moves it. This is in the contract. |
| **Commoditisation** | Go deeper per vertical: HVAC-specific prompt sets and benchmarks are hard to replicate and easy to sell. |
| **Founder is the bottleneck on sales** | Only sales and approvals need a human. Everything else already runs unattended. |

## 9. What the agent fleet actually does

Seven agents, running on their own schedules in one process:

| Agent | Cadence | Job |
| --- | --- | --- |
| `scout` | 6h | Finds local businesses, dedupes by domain |
| `auditor` | 1h | Teaser audits on prospects, full audits for clients |
| `fixer` | 6h | Generates schema, FAQ copy, GBP and citation deliverables |
| `reporter` | 12h | Renders monthly client reports |
| `outreach` | 4h | Drafts evidence-backed, compliant email |
| `bookkeeper` | 24h | Bills clients, books costs, tracks progress to target |

**What stays human:** approving outreach batches, taking sales calls, and
signing clients. That is roughly 30–60 minutes a day, and it is deliberate —
those are the steps where a mistake is expensive.

## 10. Milestones

| Month | Target | Profit |
| --- | --- | --- |
| 1 | Infrastructure live, 200 prospects audited, first 2 clients | ~$1,300 |
| 2 | 4 clients, first reports delivered, content channel started | ~$2,600 |
| 3 | 6 clients, first referral, one vertical case study | ~$3,900 |
| **4** | **8 clients — target met** | **~$5,100** |
| 6 | 11 clients, partnership channel live | ~$7,400 |
| 12 | 16+ clients, second vertical, first contractor hired | ~$11,000 |

Assumes 2 new clients/month and 5% monthly churn. Both are conservative against
the published benchmark that solo operators reach $10–25k/month within 6–12
months, and both are adjustable in `run.py forecast`.
