# Financial Model

All figures are reproducible from the codebase:

```bash
python3 run.py forecast --adds-per-month 2 --churn 0.05 --months 12
python3 run.py dashboard
```

---

## 1. Startup costs

The whole point of this model is that it starts cheap. Nothing below is
optional, and nothing above it is needed to take the first dollar.

| Item | One-time | Monthly | Notes |
| --- | --- | --- | --- |
| LLC formation (state fee) | $50–$500 | — | Varies by state; TX $300, FL $125, WY $100 |
| Registered agent | — | $10–$25 | Required; also supplies the CAN-SPAM address |
| Domain | $12/yr | ~$1 | Plus a second domain for cold sending |
| Email sending (Google Workspace + warmup) | — | $20–$60 | Separate domain from the primary |
| Hosting (VPS for the fleet) | — | $6–$12 | A $6 droplet runs this comfortably |
| Payment processing | — | 2.9% + $0.30 | Stripe |
| Accounting software | — | $15–$30 | |
| API credits (OpenAI, Anthropic, Perplexity, Serper) | $50 float | $10–$40 | Scales with client count |
| Business bank account | $0 | $0 | Use a no-fee business account |
| **Total to launch** | **~$150–$600** | **~$140/mo** | |

**Not needed at this stage:** logo design, a custom-built website (a one-page
site is enough), paid ads, a CRM subscription, an office, employees.

## 2. Unit economics by tier

| Plan | Price | Delivery | Processing | **Margin** | **% margin** | To reach $5k |
| --- | --- | --- | --- | --- | --- | --- |
| Audit (one-time) | $297 | $1.50 | $8.91 | $287 | 97% | — |
| Starter | $499 | $18 | $14.77 | **$466** | 93% | 12 clients |
| Growth | $997 | $18 | $29.21 | **$950** | 95% | **6 clients** |
| Managed | $1,997 | $18 | $58.21 | **$1,921** | 96% | 3 clients |

Delivery cost is dominated by API calls. A client's monthly audit — 10
questions across 4 engines, each asked three times with live web search —
costs about **$1.50**. The $18 figure budgets generously for re-runs, content
generation, citation checks and headroom.

The margin structure is why this business works with one person: there is no
labour in the cost of goods. Published benchmarks put a solopreneur AI stack at
$3,000–$12,000/year supporting 60–80% operating margins; this model runs leaner
because delivery is metered API calls rather than seat licences.

## 3. Path to $5,000/month profit

**Base case — 2 new clients/month, 5% monthly churn, blended price $748:**

| Month | Clients | MRR | Costs | Profit |
| --- | --- | --- | --- | --- |
| 1 | 2.0 | $1,496 | $218 | $1,278 |
| 2 | 3.9 | $2,917 | $294 | $2,623 |
| 3 | 5.7 | $4,267 | $366 | $3,901 |
| **4** | **7.4** | **$5,550** | **$435** | **$5,115** ← target |
| 5 | 9.0 | $6,768 | $500 | $6,269 |
| 6 | 10.6 | $7,926 | $562 | $7,364 |
| 12 | 18.4 | $13,752 | $873 | $12,879 |

**Scenario comparison:**

| Scenario | Adds/mo | Churn | Target hit | Month 12 profit |
| --- | --- | --- | --- | --- |
| Pessimistic | 1 | 8% | Month 11 | ~$5,460 |
| **Base** | **2** | **5%** | **Month 4** | **~$12,880** |
| Optimistic | 3 | 4% | Month 3 | ~$20,430 |

Even the pessimistic case — one client a month with churn running at nearly
twice the SMB SaaS average — clears $5k inside a year. The model is not sensitive
to price — it is sensitive to **client adds**, which is a sales-activity problem,
not an economics problem.

## 4. What has to be true

The model rests on four assumptions. Each is checkable in the first 60 days, and
each has a stated failure signal:

| # | Assumption | Basis | Fails if |
| --- | --- | --- | --- |
| 1 | 2 new clients/month is achievable | 120 emails/day × 3-step sequence at a 1–3% reply rate yields 30–100 replies/month | Under 10 replies/month after 3 weeks of sending |
| 2 | Local businesses will pay $499–$997/mo | They already pay $2,000–$6,000/mo retainers in these verticals | 20+ qualified calls with zero closes |
| 3 | Monthly churn stays near 5% | SMB SaaS averages 3.5%; done-for-you service with a visible trend line should beat bare software | Two churns in the first five clients |
| 4 | Delivery stays ~$18/client | About $1.50 per monthly audit with live search | API pricing rises 10×, or clients demand daily re-runs |

**Assumption 1 is the one that decides the business.** Everything else is
arithmetic. Test it first and test it hard — see `04_LAUNCH_CHECKLIST.md`.

## 5. Cash flow reality

- **Bill monthly in advance.** Charge on signup, then on the same day each
  month. Never invoice in arrears for an SMB retainer.
- **Expect 30–45 days from first email to first payment.** Budget for two
  months of fixed costs (~$280) before revenue arrives.
- **No refunds after the first report is delivered**, stated plainly in the
  agreement. Offer a 30-day money-back guarantee on the *first* month only —
  it removes the risk objection and is rarely claimed.
- **Set aside 25–30% for tax** from day one, in a separate account. At $5k/month
  profit, that is roughly $1,250–$1,500/month that is not yours.

**Take-home reality check:** $5,000/month in business profit is approximately
**$3,500–$3,750/month after self-employment tax and income tax**, depending on
state and structure. If the goal is $5,000 *in your pocket*, target ~$7,000/month
in business profit — 9 Growth clients rather than 6.

## 6. When to reinvest

| Profit level | Next investment |
| --- | --- |
| $2,000/mo | Second sending domain; a real logo and one-page site |
| $5,000/mo | A cold-email platform with warmup; a VA for list building (~$400/mo) |
| $8,000/mo | Commission-only appointment setter; paid content |
| $12,000/mo | First contractor for fulfilment QA; build a client-facing dashboard |

Hold overhead flat until $5k profit is hit for two consecutive months. The
temptation to spend on tools before the acquisition channel is proven is the
most common way this category of business dies.

## 7. Valuation, if you ever sell

Productized services with recurring revenue and documented systems trade at
roughly **2.5–4× annual profit**. At $5,000/month profit ($60k/year), that is a
**$150,000–$240,000** asset — provided the systems are documented and the
business is not dependent on the founder's personal relationships.

The agent fleet in this repository *is* the documentation. Keep it current; it is
a material part of what makes the business saleable rather than just a job.
