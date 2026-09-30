# Autopilot: AnswerRank running itself

Autopilot is one switch on the phone's Today tab. With it on, the agent fleet
runs the whole business, from finding a business to collecting its monthly
payment, and emails you only when something genuinely needs a person.

This page has three parts: what runs by itself, what still comes to you, and
the one-time setup only you can do (accounts, cards, DNS), in order.

---

## 1. What runs by itself

| Step | Who does it |
| --- | --- |
| Find local businesses in your trade and cities, and their contact email | Scout, Prospector |
| Check how ChatGPT, Google's AI Overviews, Perplexity and Claude answer for them | Auditor, Citations |
| Write and send the first email, then up to three follow-ups, in business hours, inside the warm-up limits | Outreach, Sender |
| Read every reply in your inbox, and work out what the person wants | Concierge |
| "Yes, send it": run a full audit and email the report, with a link to start | Concierge |
| A question ("how much?", "is there a contract?", "how long?", "can my web guy do it?"…): answer it from written answers that are true of every client | Concierge + `answers.py` |
| "Sign us up": reply with the payment link and open their account | Concierge + `sales.py` |
| Someone pays, from the report or the reply | Stripe, then Bookkeeper |
| Welcome email, first full audit, fix files with steps for their website builder | Onboarder, Fixer |
| Monthly report email, and a daily check that the fixes are live on their site | Reporter |
| Remind once if they haven't paid; flag if they still haven't | Bookkeeper |
| Clients who go quiet, haven't installed the fixes, or have a failing card get the right email | Retention |
| "How do I cancel?", "where's my invoice?", "who do I send the login to?": answered, with the billing link | Concierge + `answers.py` |
| Watch for anything going wrong, pause that part, and tell you | **Guardian** (new) |
| Morning list, instant alerts, and the Friday "Your week" review | Briefing |

**The proof:** `python run.py simulate --autopilot` runs all of this for 100
simulated days with nobody at the console. The businesses, their replies and
the AI answers are made up; the agents, database and send path are the real
ones. The latest run:
- Sales: 30 of 30 buyers bought. Of the 30, 28 were scripted to pay and all
  of them did; the 2 scripted never to pay got one reminder and were
  flagged.
- Replies: answered in about an hour (median), against 20 hours when a
  person approved each one. None were misread, and none needed you.
- 8 buyers paid straight from their report without writing back.
- Cancellations: 4 clients asked to cancel; each got the billing link, was
  cancelled in Stripe, and was taken off the books.

That proves the software can run a sale without you. It doesn't prove the
market will buy: real reply rates decide that.

## 2. What still comes to you

Honestly, a little. On Autopilot this is all of it:

- **A reply with no written answer.** For example, "Do you also do Facebook
  ads?" It is held rather than guessed at, and you're emailed at once with
  what they wrote. Answer it from the phone inbox.
- **Something you should know about.** For example, a client cancelled,
  asked for a refund, or changed their address. It has already been answered
  (with the billing link, for example); you get a copy.
- **A Guardian pause.** Three spam-style replies in a week, too many
  "remove me" replies, or too many bounces pause first emails, and you're
  told why. Bounce pauses lift by themselves. For the rest, look, fix the
  cause, and tap **Resume**.
- **Friday afternoon:** the "Your week" email, with the one thing to change.
- **Refunds.** They're your call, in Stripe. The written guarantee is: if
  they've put the fixes in and the number hasn't moved after 30 days, the
  month is refunded.

Expect about ten minutes a week. The optional extras still work if you want
them: calls, walkthroughs and the booking link.

**What Autopilot won't do:**
- It won't send a first email to a stranger until you've read 20 of them
  yourself.
- It won't sell the $1,997 Managed plan. That plan means installing fixes
  on the client's website by hand, so on Autopilot the top plan is Growth
  ($997).
- It won't promise a ranking. Every answer it sends is on the list in
  `answerrank/answers.py`.

---

## 3. Your one-time setup, in order

About three hours, spread over a few days because DNS and Stripe checks
take time. You already have the domain. None of these steps can be done for
you: each one is an account in your name, a card, or a setting at your
registrar.

**The desktop button's option 4, "What still needs doing (Autopilot
checklist)", shows which of these are done.** Run it after each step.

### Step 1: Mailbox on your domain (Google Workspace), about 20 minutes, about $7-8.40/month
1. workspace.google.com → **Business Starter** → use the domain you already
   have. Create `hello@yourdomain.com` (or your name).
2. Turn on **2-Step Verification** for that account, then create an **App
   password** (Google Account → Security → App passwords). You'll paste it in
   step 7.

### Step 2: Email domain records (SPF, DKIM, DMARC), about 20 minutes plus waiting
Desktop button → **3 Email domain: set up and check**. It tells you exactly
which records to add at your registrar, and checks them until they're green.
Without this, Gmail and Outlook put your email in spam.

### Step 3: A postal address, about $10-20/month if you don't want to use your home
The law (CAN-SPAM) requires a real postal address in every email. A USPS PO
Box or a virtual mailbox (for example iPostal1 or Anytime Mailbox) is fine.

### Step 4: Stripe (payments), about 40 minutes
1. stripe.com → create the account → add your bank for payouts.
2. **Products:** create *Starter*, $499 a month recurring, and *Growth*, $997
   a month recurring.
3. **Payment Links:** make one for each. These are what clients click to pay.
4. **Settings → Billing → Customer portal → Activate**, then copy the
   **login link**. Clients update their card, get invoices and cancel there
   themselves.
5. **Developers → API keys → Create restricted key.** Give it **Read** on
   *Checkout Sessions* and *Subscriptions*, and nothing else. That's how
   payments are confirmed without you. It can't move money.

### Step 5: The AI and finder keys, about 15 minutes
- **OpenAI** (platform.openai.com → API keys), about $30-60 a month. This runs
  the real checks of what ChatGPT says. Add $35 of credit to start (about a
  month of checks at the default 20 a day).
- **Serper** (serper.dev), 2,500 free searches, then $50 for 50,000. This
  finds the businesses.

### Step 6: The server, about 30 minutes, $6/month
Follow `deploy/SERVER.md`:
1. Desktop button → **5 Make the server setup file**.
2. Create a DigitalOcean droplet with the file pasted in.
3. Add one **A record** at your registrar pointing your domain at the server.

From then on the business runs there, all day, every day, whether your PC is
on or not.

### Step 7: Keys and settings, about 15 minutes
Desktop button → **2 Keys and settings**. Paste everything from steps 1-5,
then:
- Pick your **trade and up to 3 cities**.
- Give your **time zone** and where alerts go.
- Paste the **Stripe payment links** and the **customer portal link**.
- Optionally, add a **booking link**.

It tests the mailbox before saving. Then make the server setup file again
(step 6) so the server has the same keys.

### Step 8: The supervised start, about 10 minutes over 2 days
Open the phone console. The first emails appear in **Review drafts one by
one**: read each, then **Approve**, **Edit** or **Skip**. After 20, Autopilot
writes them alone. This is the one step that stays human on purpose. It's
the only email that goes to a stranger, so a person checks the drafts on
real businesses first.

### Step 9: Switch it on
Phone → Today → **Autopilot** card → **Switch Autopilot on**. The card shows
anything still missing. You can switch it on early, and the missing parts
simply wait for you.

---

## Costs

| | Monthly |
| --- | --- |
| Google Workspace | ~$7-8.40 |
| Server | $6 |
| Postal address (optional) | $10-20 |
| OpenAI | ~$30-60 (the Guardian tells you if it passes $150; change `api_budget_monthly`) |
| Serper | $0 at first, then ~$50 per 50,000 searches |
| Stripe | about 3.6% of each payment (card fee plus subscriptions), ~$36 of a $997 month |
| **Total before the first client** | **about $55-135** |

One Growth client ($997) pays for all of it many times over. The $5,000/month
profit target is about six Growth clients after costs.

## What to expect, and what not to

- **Sending ramps up slowly on purpose:** 10 a day, then 20, 40, 70, 100,
  and the full 120 a day from day 29. A new domain that sends hundreds on
  day one lands in spam for months.
- **The first replies** usually come in the first week or two of sending. The
  benchmark is 3-5% of first emails, so about 1 in 25.
- **The first sales** depend on the market, not the software. The simulation
  shows the machine works. Your real reply rate, visible in the Friday email,
  shows whether the trade and cities are right. If the Friday email names the
  reply rate as the thing to fix, change the trade or cities in Keys and
  settings.
- **You stay responsible** for the business itself. Register it as you would
  any business (an LLC is optional, an EIN is free), keep the money for taxes
  (the Bookkeeper tracks income), and read the Friday email.

## Switching off, pausing, stopping

- **Autopilot off** (the same card): drafts wait for you again, and nothing
  else changes.
- **Pull back** any approved email in the inbox until the moment it sends.
- Each stage can be paused by the Guardian and resumed by you, separately:
  first emails, answers, and client emails.
