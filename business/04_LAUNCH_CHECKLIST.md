# Launch Checklist

The software is built and tested. Launching is a set of accounts, keys and
records that only you can create, because they are in your name. **All of it
fits in one evening, about three hours.** A few things then have to wait on
Google and DNS, and this says which ones and why.

Nothing on this list needs you to edit a file or type a command on a server.

---

## Starting on a Monday

| When | What | Why then |
| --- | --- | --- |
| **Friday night** | Steps 1–4 below, first: mailbox, first run, DNS, app password. Then as much of 5–10 as you can. | Google's DKIM wait (24–72 hours) starts when Gmail is switched on. Friday night makes Monday likely; Sunday makes it unlikely. |
| **Saturday** | Finish 5–11. Once the server is up with your trade and cities, the fleet finds and checks businesses all weekend, and your call list fills up. Get a free Google Voice number if you want your cell private. Call the 2–3 people you know for pilots. | Businesses need to be found and audited before they can be called. |
| **Sunday** | DKIM, if it's been 24 hours: admin.google.com → Apps → Google Workspace → Gmail → Authenticate email. Read the call list and three audits. Say the opener and the voicemail out loud five times each. Read the first email drafts, but don't send yet. | The script sounds like reading until you've said it a few times. |
| **Monday 8–9:30am** (their time) | Calls. Tap each name in the call list, dial, tap what happened. | Owners pick up before the first job. |
| **Monday midday** | If the doctor is all green, send the first 10 emails. If DKIM isn't ready, calls only; email starts the day it is. Send any reports people asked for. | |
| **Monday 4–6pm** (their time) | Calls again. | After the last job. |

The reports you promise on calls go out as email, so they also wait for DKIM.
Tell anyone who asks on Monday it'll be with them in a day or two.

---

## Tonight — about 3 hours

Do them in this order. The server goes last because it copies your keys and
settings when it is created.

### 1. Mailbox on a sending domain — 20 min

- [ ] workspace.google.com → **Business Starter**, 1 user. $8.40/month month to
      month ($7 on a yearly plan), first 14 days free.
- [ ] Use a **separate sending domain**, never your main one — if it is ever
      burned, your real domain survives. Buy one during Google's signup or at
      any registrar (~$12/year). Pattern: `get<brand>.com`, `<brand>hq.com`.
- [ ] Make `hello@yourdomain` and verify the domain when Google asks.

### 2. First run — 10 min

- [ ] Double-click **start.bat** in the folder, **once**. It sets everything up,
      asks six questions (name, domain, address, trade, prices), and puts an
      **AnswerRank button on your desktop**. From then on, use that button: it
      opens a menu for everything below, and it updates itself.


### 3. DNS records — 15 min

- [ ] Desktop **AnswerRank** button → **3 Email domain**. Press Enter, pick Google.
- [ ] At your registrar, paste the **MX**, **SPF** and **DMARC** rows it prints.
- [ ] **DKIM will not be ready tonight.** Google only lets a new account
      generate the key 24–72 hours after Gmail is switched on. It is on the
      "what waits" list below.

### 4. App password — 5 min

- [ ] myaccount.google.com → Security → **2-Step Verification** on.
- [ ] myaccount.google.com/apppasswords → make one called `Mail`. Copy the 16
      letters. (That page does not exist until 2-Step Verification is on.)

### 5. Stripe — 40 min

- [ ] stripe.com → sign up → **Activate payments**. Sole proprietor is fine.
      You will need your SSN, a bank account for payouts, and a website — use
      your sending domain; it goes live in step 9.
- [ ] Product catalogue → three products, each with a **recurring monthly
      price**: Starter $499, Growth $997, Managed $1,997.
- [ ] Payment Links → New → one link per price. Copy all three.
- [ ] Developers → API keys → **Create restricted key**: Checkout Sessions =
      Read, Subscriptions = Read, everything else None. It starts `rk_`.
      Never paste the `sk_` secret key anywhere — it can move money.

Stripe keeps 2.9% + 30¢ per charge plus 0.7% for subscriptions — about $36 of
a $997 month. The bookkeeper already counts it.

### 6. AI credits — 10 min

- [ ] platform.openai.com → Billing → add **$35** → API keys → new key.
      Every check searches the web the way ChatGPT answers a customer: about
      5.5 cents per business checked, 20 a day by default (about $33 a month).
- [ ] Recommended: serper.dev → free account → API key. It is how the system
      finds local businesses and reads Google's AI Overviews.

### 7. Postal address — 10 min

Every commercial email must carry a postal address. It does **not** have to
be your home:

- [ ] Reserve a **USPS PO Box** online (collect the keys at the post office),
      or sign up for a **virtual mailbox** (needs USPS Form 1583, notarised —
      most services do that online).
- [ ] Or use your home address for now and change it later. Nothing cold goes
      out for a few days anyway (see DKIM), so there is time for the box.

### 8. Keys — 10 min

- [ ] AnswerRank button → **2 Keys and settings**. It asks, in plain words, for the mailbox, the
      app password, whether to read replies automatically (say yes), the AI
      keys, the Stripe key, the postal address, your first name and callback
      number (for the call script), **your trade and up to 3 cities** (what the
      system searches for your call list), and the three payment links.
      It tests the mailbox before saving. Press Enter to keep anything already
      saved — it is safe to run again.

### 9. Server and phone console — 30 min, some of it waiting

The unsubscribe link in every email has to work from the public internet, all
the time. A laptop cannot do that, so this $6/month server is needed before
the first email, not after the first client. Every screen is in
[`deploy/SERVER.md`](../deploy/SERVER.md).

- [ ] AnswerRank button → **5 Make the server setup file**. **Save the console
      link it prints. It is your login.** The file opens in Notepad for you.
- [ ] DigitalOcean → Create → Droplets → Ubuntu 24.04, Basic, **$6/month** →
      Advanced Options → Add Initialization scripts → paste the whole
      `server-setup-….sh` file → Create. Note the IP address.
- [ ] At your registrar: an **A record**, name `@`, value = that IP address.
- [ ] After ~15 minutes, open the console link on your phone → **Add to Home
      Screen**. Then delete the server-setup file from the laptop.

### 10. Check — 10 min

- [ ] AnswerRank button → **4 What still needs doing**. Tonight, expect **DKIM** (and
      possibly the unsubscribe link, while HTTPS finishes) to be the only red.
- [ ] Optional: AnswerRank button → **6 Practice run** to watch a month of the business
      run with made-up clients. Nothing real is sent.

### 11. Pilots — 10 min

- [ ] Write down 2–3 local trades businesses you, or someone you know, can
      reach directly. Tomorrow, offer them three free months in return for
      being measured and written up. That before-and-after is what sells the
      service to strangers. You add them on the phone with **Add a business you
      know** (Pipeline tab).

---

## What has to wait, and why

| What | How long | Why |
| --- | --- | --- |
| DKIM key | 24–72 hours after Gmail is on, then up to 48 hours to start signing | Google's rule for new accounts. Nothing cold goes out until it passes — the doctor blocks it. |
| HTTPS on the server | Minutes to an hour after the A record | The certificate can only be issued once DNS points at the server. |
| First cold email | Usually day 3–5 | The day the doctor is all green. Until then, send a few real, personal emails a day from the new address. |
| Full sending volume | About a month | The system starts at 10 a day and climbs by itself: 20 from day 4, 40 from day 8, 70 from day 15, 100 from day 22. Do not raise it. |
| First Stripe payout | 7–14 days after the first live payment | Stripe's standard for new accounts. After that, a few days per charge. |
| A case study | 45+ days after a pilot starts | AI engines pick up changes when they next crawl. `run.py case-study` says "too early" until it is not. |

---

## The first 30 days

| When | What |
| --- | --- |
| Day 1 | Call or message your 2–3 pilots. In the console: Pipeline → **Add a business you know** → Sign them up → **Free pilot**. Free, starts at once, and never sent cold email. |
| Day 1–3 | DKIM: admin.google.com → Apps → Google Workspace → Gmail → Authenticate email → Generate new record (2048-bit) → paste at registrar → Start authentication. Then AnswerRank button → 3 Email domain until it says ready. |
| Day 3–5 | **First send.** Console → Review drafts → read every one → approve → Send approved. |
| Every weekday | The 10 minutes below. |
| Week 2+ | Replies arrive. The Concierge drafts each answer; you read and send within two hours. Book the call. |
| On a yes | Console → find them → **Sign them up** → pick the plan. The payment link goes out. Approve the welcome email the day they pay. |
| Day 30 | Console → money view. Fix only the earliest broken step: not delivered → DNS; no replies → subject and targeting; no calls → report; no closes → the call. |

### Every weekday — work down Up next

The morning briefing email arrives at 7am with the day's list. Open the
console: **Up next** has the same list, most urgent first, and tapping an
item does it:

- **Someone ready to buy** → their drafted answer, with the payment link.
- **A walkthrough soon** → their report and your notes.
- **Call back / Call N businesses** → a calling session: dial, talk, tap what
  happened, and the next business opens. Call backs come back at the time
  you agreed; a booked walkthrough gives you an *Add to my calendar* button
  and drafts a confirmation with their report.
- **Answers to people who asked**, then **first emails and follow-ups** →
  read, approve. You never tap Send: approved emails go out on their own
  (answers 7am–9pm, cold emails weekdays 8am–5pm), within every cap.
- **Someone hasn't paid**, **Save a client** → the Clients tab.

When Up next is empty, you're done. Alerts arrive by email the moment someone
is ready to buy or pays, so nothing waits for tomorrow.

**Automatic** (Today tab) has two more switches for when you trust the
drafts: approve follow-ups automatically, and send reports people asked for
without waiting. Both start off.

---

## The gates

Each gate opens when something happens, not on a date, and is paid for by the
thing that opened it.

| Gate | Opens when | Adds | Running cost |
| --- | --- | --- | --- |
| **0 — Prove the channel** | Tonight | Domain, mailbox, AI credits, server | $47 once, **$48.40/month** |
| **1 — First client** | Someone pays | LLC (~$150), contract review (~$350), registered agent, accounting | $500 once, **$78.40/month** |
| **2 — Three clients** | ~$2,000 a month | Insurance (E&O + liability), a second sending domain | **$176.40/month** |
| **3 — Bringing someone on** | 4+ paying clients, or fixes piling up uninstalled | A fulfilment helper, paid per client | Scales with revenue |

Six clients is the $5,000 target.

---

## Bringing someone on

**Who first:** a *fulfilment* helper, not a salesperson. The time that grows
with every client is installing the fixes on client websites, updating
Google Business Profiles, listings and review requests. The system drafts all
of it and gives a step-by-step guide per website platform; a careful helper
can do the installing. Keep the sales conversations yourself until you have
closed five or so and know what works — that is where you learn the business.

**When:** four or more paying clients, or when the console keeps flagging
clients whose fixes still are not live because you have not had the evenings.

**How to pay:** a flat amount **per client per month** (for example $100), plus
a one-off amount per new client set-up. Their pay then rises and falls with
revenue, and at $997 a client you keep about 90%.

**On paper:**

- A written **contractor agreement**, signed by your LLC (gate 1 comes first):
  scope, per-client rate, confidentiality, that the work belongs to you, and
  that they will not take your clients.
- Get a **W-9** from them before the first payment. If you pay them **$2,000 or
  more in a year** (the threshold for payments from 2026 on), you file a
  **1099-NEC** by 31 January.
- Keep them a contractor for real: paid per result, their own hours, their own
  computer. If you set their hours and how they work, the IRS can treat them
  as an employee.

**Access — only what the job needs:**

| Thing | How they get in | Never |
| --- | --- | --- |
| Email | Their own Google Workspace seat (`name@yourdomain`, $8.40/month) | Your password or app password |
| Client websites | The client invites them as their own user, with enough access to add code (on WordPress that means Administrator, because it takes a plugin), and removes it after the install | A client's password |
| Google Business Profiles | The client adds them as a **Manager** | Owner access |
| Stripe | Not needed. If ever, a team member with a limited role | The secret key |
| The console | Not yet — see below | Your console link |
| The server, `keys.env` | Not needed | Ever |

**What the software does not do yet:** the console has one login, and whoever
holds the link can do everything — approve cold email, mark clients paid,
see the money. There are no per-person accounts and no record of who did
what. Before a second person uses it, it needs a **helper login** that sees
only the fulfilment work (which clients need what installed, their files and
guides, whether it is live yet), and an **activity log**. Until that exists,
send them the files and install guides by email instead.
