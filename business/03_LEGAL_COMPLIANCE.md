# Legal & Compliance

**This is not legal advice.** It is an operator's checklist of the obligations
that apply to this specific business model. Have a lawyer review your contract
and entity setup before you sign your first client.

---

## 1. Entity and setup

| Step | Detail | Cost |
| --- | --- | --- |
| Form an LLC | Single-member LLC in your home state. Do not use Delaware/Wyoming for a one-person local services business — it adds a foreign-qualification burden with no benefit. | $50–$500 |
| Get an EIN | Free, direct from the IRS. Never pay a service for this. | $0 |
| Registered agent | Required. Also supplies a usable business address for CAN-SPAM. | $10–$25/mo |
| Business bank account | Separate from personal, from day one. Commingling funds is what pierces the liability veil. | $0 |
| General liability + E&O | ~$40–$80/mo. Get it before the first client, not after the first complaint. | $40–80/mo |
| Sales tax | Most states do not tax digital marketing services, but several do. Check yours. | — |

## 2. Email compliance — the one that can end the business

Cold email to a business address is legal in the US under CAN-SPAM. It is
**not** legal without the following, and the penalty is up to five figures per
message.

### CAN-SPAM (legally required)

- [x] **Accurate "From" and routing information.** No spoofing, no lookalike domains.
- [x] **Non-deceptive subject line.** The subject must describe the message.
- [x] **Identify it as a solicitation** — the evidence-led opening does this implicitly; the footer does it explicitly.
- [x] **Valid physical postal address** in every message. *Enforced in code — `outreach.preflight()` blocks all sending until configured.*
- [x] **Working opt-out**, honoured within 10 business days. *We honour immediately via the suppression list.*
- [x] **No selling or transferring** an address that opted out.

### 2026 bulk-sender requirements (Google, Yahoo, Microsoft)

These are not law, but they decide whether mail is delivered at all.
Non-compliant senders see 22–34% of mail filtered or rejected; compliant senders
average ~89% inbox placement.

- [ ] **SPF** record on the sending domain
- [ ] **DKIM** signing enabled
- [ ] **DMARC** at `p=quarantine` or `p=reject` — `p=none` is no longer sufficient
- [x] **One-click unsubscribe** (RFC 8058): both `List-Unsubscribe` and `List-Unsubscribe-Post` headers. *Implemented in `mailer.py`.*
- [x] **Spam complaints under 0.3%** — operating ceiling 0.1%, elite 0.04%. *Capped by policy.*
- [x] **Bounces under 2%** — *bounced addresses auto-suppressed.*

`run.py send` runs `check_dns_readiness()` and **refuses to send** if SPF or
DMARC are missing or DMARC is at `p=none`. This is deliberate: a domain burned
by unauthenticated bulk mail cannot be recovered, only abandoned.

### Operating rules

1. **Send from a separate domain** (e.g. `answerrank-mail.com`), never the
   primary. If it burns, the main domain and client email survive.
2. **Warm up for 2–3 weeks** before volume: 10/day rising to 100/day.
3. **Never buy a list.** Scraped-but-verified business addresses only, and
   verify deliverability before sending.
4. **Honour opt-outs instantly and permanently.**
5. **Never email consumers** — B2B only. Consumer email is a different legal regime.
6. **GDPR/CASL:** if you email the EU or Canada, different and stricter rules
   apply (CASL requires consent). **Stay US-only unless you have taken advice.**

## 3. Client contracts

Every client signs before the first report. Non-negotiable clauses:

| Clause | Why |
| --- | --- |
| **No guarantee of ranking or placement** | AI answers are non-deterministic and outside anyone's control. Promising placement is the fastest route to a lawsuit. State it explicitly. |
| **Scope definition** | Exactly what is delivered monthly. Prevents scope creep into general SEO. |
| **Month-to-month, 30 days' notice** | Low friction to buy; no consumer-protection exposure from long lock-ins. |
| **Payment terms** | Monthly in advance, auto-charged. Service pauses on failed payment. |
| **Client responsibilities** | They must implement or authorise implementation. Without this, they blame you for their inaction. |
| **Limitation of liability** | Capped at fees paid in the last 3 months. |
| **Data and access** | What you may access (GBP, website) and what you do with it. |
| **Termination** | Either side, 30 days. They keep the deliverables already provided. |

Use a plain-language template and have a lawyer review it once (~$300–$600).
That one review covers every client you will ever sign at this scale.

## 4. Claims you may and may not make

**Safe:**
- "We measure how often your business appears in AI-generated answers."
- "We generate the structured data and content that make your site quotable."
- "Your visibility score went from 12 to 41 over three months."

**Not safe:**
- "We'll get you ranked #1 in ChatGPT." *(Nobody controls this.)*
- "Guaranteed results or your money back" *(unless you genuinely honour it —
  the narrow first-month guarantee in the sales playbook is fine because it is
  specific, time-boxed, and actually paid out.)*
- "We're partnered with OpenAI/Google." *(You are not. This is actionable.)*
- Any comparative claim about a named competitor's client results.

**FTC endorsement rules:** testimonials must be genuine and typical. If you
publish a case study, the result must be real and the client must have agreed
in writing.

## 5. Data protection

- Audit data is public information — what an AI says in response to a public
  question. Low risk.
- Client credentials (GBP access, CMS logins) are **high** risk. Use a password
  manager with per-client vaults. Never store credentials in the database or in
  this repository.
- The SQLite database contains prospect business contact details. Back it up
  encrypted; do not commit it to version control. *(`.gitignore` covers `data/`.)*
- Have a simple privacy policy on the site. Required by several state laws and
  by Google if you run ads.

## 6. Pre-launch legal checklist

- [ ] LLC formed, EIN issued
- [ ] Business bank account open, no commingling
- [ ] General liability + E&O insurance active
- [ ] Client service agreement drafted and lawyer-reviewed
- [ ] Privacy policy and terms published on the site
- [ ] Physical address configured in `answerrank.yml` (**blocks sending until done**)
- [ ] SPF, DKIM, DMARC (`p=quarantine`+) configured on the sending domain
- [ ] Unsubscribe endpoint live at `/unsubscribe` and wired to the suppression list
- [ ] Sending domain warmed for 2+ weeks
- [ ] Accounting set up; 25–30% of profit reserved for tax
