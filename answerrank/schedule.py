"""Generates an .ics calendar file you can import straight into a phone.

Built around one constraint: you have a 9-5. Every recurring block sits
before work, at lunch, in the evening, or on a Saturday. Sunday is
deliberately left empty — a schedule with no rest day gets abandoned in
week three, and an abandoned schedule grows nothing.

Each event's description carries the exact commands and checklist for that
block, so the calendar entry alone tells you what to do. No second document
to go and find at 6:30am.

Output is RFC 5545 with floating local times: 6:30am stays 6:30am wherever
you are, with no timezone database to get wrong.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

DEFAULT_BRAND = "AnswerRank"


def _prodid(brand: str) -> str:
    return f"-//{brand}//Operator Schedule//EN"


# ---------------------------------------------------------------------------
# ICS primitives
# ---------------------------------------------------------------------------

def _escape(text: str) -> str:
    """Escape per RFC 5545 §3.3.11."""
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """Fold to 75 octets per line, continuation lines start with a space."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    out, start = [], 0
    limit = 75
    while start < len(raw):
        end = min(start + limit, len(raw))
        # Do not split a multi-byte character.
        while end > start and (raw[end - 1] & 0xC0) == 0x80 and end < len(raw):
            end -= 1
        chunk = raw[start:end].decode("utf-8", errors="ignore")
        out.append(chunk if start == 0 else " " + chunk)
        start = end
        limit = 74  # continuation lines lose one octet to the leading space
    return "\r\n".join(out)


def _dt(d: date, t: time) -> str:
    return datetime.combine(d, t).strftime("%Y%m%dT%H%M%S")


def _uid(seed: str) -> str:
    return f"{hashlib.sha1(seed.encode()).hexdigest()[:20]}@answerrank.local"


@dataclass
class Event:
    summary: str
    start: datetime
    minutes: int
    description: str = ""
    rrule: str = ""
    alarm_minutes: int = 10
    categories: str = DEFAULT_BRAND

    def to_ics(self, stamp: str) -> list[str]:
        end = self.start + timedelta(minutes=self.minutes)
        lines = [
            "BEGIN:VEVENT",
            _fold(f"UID:{_uid(self.summary + self.start.isoformat())}"),
            f"DTSTAMP:{stamp}",
            f"DTSTART:{self.start.strftime('%Y%m%dT%H%M%S')}",
            f"DTEND:{end.strftime('%Y%m%dT%H%M%S')}",
            _fold(f"SUMMARY:{_escape(self.summary)}"),
            _fold(f"CATEGORIES:{_escape(self.categories)}"),
        ]
        if self.description:
            lines.append(_fold(f"DESCRIPTION:{_escape(self.description)}"))
        if self.rrule:
            lines.append(f"RRULE:{self.rrule}")
        if self.alarm_minutes:
            lines += [
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                _fold(f"DESCRIPTION:{_escape(self.summary)}"),
                f"TRIGGER:-PT{self.alarm_minutes}M",
                "END:VALARM",
            ]
        lines.append("END:VEVENT")
        return lines


# ---------------------------------------------------------------------------
# The recurring operating rhythm
# ---------------------------------------------------------------------------

MORNING_OPS = """Your 10 minutes that keep the business moving. All on the phone.

The briefing email has the day's list. Open the console and work down
Up next: it is the same list, most urgent first, and tapping an item
does it.

- Someone ready to buy: approve the drafted answer with the pay link.
- Calls: tap to start a session. Log each call and the next one opens.
- Drafts: one at a time; Approve, Skip or Edit, and Undo if you slip.
  Approved emails send themselves in sending hours; you never tap Send.
- After a walkthrough: tap how it went. Signed up sends the pay link.

When Up next is empty, you're done.

If you only ever do this one block, the business still runs."""

LUNCH_CHECK = """10 minutes. Replies only.

Console -> Replied - waiting on you. The Concierge has already drafted
an answer to each one, and the report email for anyone who asked for it.
Read it, change anything that doesn't sound like you, approve, send.

Speed matters more than polish - a reply inside an hour converts far
better than a perfect one tomorrow."""

SALES_WINDOW = """Owners of home service businesses are reachable now -
off the tools, not yet at dinner. This is the best calling window you have.

Per business/02_SALES_PLAYBOOK.md:
  0-2 min   "How do people find you today when they don't know you?"
  2-8 min   Share the report. Walk the test log. Stop at the competitor row.
            THEN SAY NOTHING. Let the silence work.
  8-12 min  The three causes: schema, answer-shaped content, GBP + citations.
  12-15 min The offer. $997/mo. Send the payment link while you're talking.

Do not offer to "send a proposal". That is where these deals die.

Closed one? Console -> Got a reply? Find them -> Sign them up -> plan.
The payment link goes out; the work starts the day they pay."""

DEEP_WORK = """Two hours. The only long block in your week - protect it.

1. Console -> Open the money view. Where are you against $5k?
   Which funnel step is weakest?

2. By stage: is the pile of audited prospects thinning? The Explorer
   tops it up by itself - check that it has.

3. Open one client report that went out this week. Would YOU pay $997
   for it? Health - worst first: anything red gets a phone call.

4. Fix the weakest funnel number - and only that one:
     not delivered  -> DNS/reputation. Stop sending. Fix SPF/DKIM/DMARC.
     no replies     -> subject line and targeting.
     no calls       -> report is not landing. Lead with the competitor gap.
     no closes      -> talk less, show the test log, ask for the card.

5. Ten minutes: write down what you learned about your trade this week.
   That accumulates into the expertise you sell."""

MONTHLY_CLOSE = """Monthly close - 45 minutes. Do not skip this one.

1. Console -> money view. On the laptop:  python run.py budget

2. Check the ledger against your bank and Stripe. Stripe pays out to
   your bank a few days after each charge; the first payout takes
   7-14 days.

3. MOVE 30% OF PROFIT TO THE TAX ACCOUNT. Today, not later.
   Money that sits in the main account gets spent.

4. python run.py budget --profit <this month's profit>
   Follow the split it gives you.

5. Any client whose score is flat two months running: call them.
   They churn quietly, and always before they complain.

6. Re-read one report you sent as if you were the client."""

WARMUP = """10 minutes. Warm the new mailbox by hand.

Send 5-10 real, personal emails from the new address today - to
yourself, to friends, to anyone who will write back. Replies are what
build a new domain's reputation.

No cold email goes out until DKIM is on and the doctor is clean - the
system will not let it. From the first send it starts at 10 a day and
climbs to 100 over about a month by itself. Do not raise that: a burned
domain is abandoned, not repaired."""

REST = """Deliberately empty.

The plan assumes you take this day off. Six days a week is sustainable
for a year; seven is sustainable for about a month, and this business
needs the year."""


def recurring_events(start: date, ops_from: date | None = None,
                     deep_from: date | None = None,
                     brand: str = DEFAULT_BRAND) -> list[Event]:
    """The permanent weekly rhythm.

    ``ops_from`` is when daily operations become meaningful (first send) and
    ``deep_from`` is when Saturdays stop being consumed by launch tasks.
    Starting these on day 1 would put empty blocks in the calendar for two
    weeks, which is how a schedule loses credibility.
    """
    ops_start = ops_from or start
    deep_start = deep_from or start
    monday = ops_start + timedelta(days=(0 - ops_start.weekday()) % 7)
    saturday = deep_start + timedelta(days=(5 - deep_start.weekday()) % 7)
    sunday = start + timedelta(days=(6 - start.weekday()) % 7)
    _month_start = (deep_start.replace(day=1) + timedelta(days=32)).replace(day=1)
    first_saturday = _month_start + timedelta(days=(5 - _month_start.weekday()) % 7)

    return [
        Event(
            f"{brand}: Morning ops",
            datetime.combine(monday, time(6, 30)), 20,
            MORNING_OPS, "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", categories=brand, alarm_minutes=5,
        ),
        Event(
            f"{brand}: Reply check",
            datetime.combine(monday, time(12, 15)), 10,
            LUNCH_CHECK, "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", categories=brand, alarm_minutes=5,
        ),
        Event(
            f"{brand}: Sales calls",
            datetime.combine(monday + timedelta(days=1), time(17, 30)), 90,
            SALES_WINDOW, "FREQ=WEEKLY;BYDAY=TU,TH", categories=brand, alarm_minutes=15,
        ),
        Event(
            f"{brand}: Weekly deep work",
            datetime.combine(saturday, time(9, 0)), 120,
            DEEP_WORK, "FREQ=WEEKLY;BYDAY=SA", categories=brand, alarm_minutes=30,
        ),
        Event(
            f"{brand}: Rest day - no business work",
            datetime.combine(sunday, time(10, 0)), 30,
            REST, "FREQ=WEEKLY;BYDAY=SU", categories=brand, alarm_minutes=0,
        ),
        Event(
            # First Saturday, not the 1st: BYMONTHDAY=1 lands on the rest day
            # one month in seven, and a block scheduled on a rest day is a
            # block that gets skipped.
            f"{brand}: Monthly close + tax reserve",
            datetime.combine(first_saturday, time(11, 15)), 45,
            MONTHLY_CLOSE, "FREQ=MONTHLY;BYDAY=1SA", categories=brand, alarm_minutes=60,
        ),
    ]


# ---------------------------------------------------------------------------
# The 30-day launch sequence
# ---------------------------------------------------------------------------

#: (earliest_day_offset, summary, minutes, description)
#: Heavy tasks (>=90 min) are placed on a Saturday; short ones take a weekday
#: evening. A sequential allocator assigns real dates so tasks never collide,
#: never reorder, and never land on the Sunday rest day.
LAUNCH: list[tuple[int, str, int, str]] = [
    (0, "LAUNCH 1: Mailbox and DNS", 60, """Setup, part one. The full list is business/04_LAUNCH_CHECKLIST.md.

1. workspace.google.com -> Business Starter, 1 user, on your SENDING
   domain (buy one there if you have none - never your main domain).
   Make hello@yourdomain and verify the domain when it asks.
2. Desktop button -> 3 Email domain. Press Enter, pick Google.
   Paste the MX, SPF and DMARC rows it prints at your registrar.
3. DKIM will NOT be ready tonight. Google only lets you make the key
   24-72 hours after Gmail is switched on. That is LAUNCH 4.
4. myaccount.google.com -> Security -> 2-Step Verification ON. Then
   myaccount.google.com/apppasswords -> make one called Mail.
   Copy the 16 letters.

Spend so far: domain ~$12/yr, Workspace $8.40/mo (14 days free)."""),

    (0, "LAUNCH 2: Stripe, AI credits, keys", 60, """Setup, part two.

1. stripe.com -> sign up -> Activate payments (business details, bank
   account for payouts). Sole proprietor is fine.
2. Product catalogue -> three products, each a RECURRING monthly price:
   Starter $499, Growth $997, Managed $1,997.
   Payment Links -> New -> one link per price. Copy each.
3. Developers -> API keys -> Create restricted key:
   Checkout Sessions = Read, Subscriptions = Read, everything else None.
   It starts rk_. Never paste the sk_ secret key anywhere.
4. platform.openai.com -> Billing -> add $35. API keys -> new key.
5. Desktop button -> 2 Keys and settings. It asks for all of it in
   plain words: mailbox, app password, AI key, Stripe key, postal
   address, your trade and cities, payment links - then tests the
   mailbox.

The postal address goes at the foot of every email. A USPS PO Box or a
virtual mailbox keeps your home address off them."""),

    (0, "LAUNCH 3: Server and phone console", 45, """Setup, part three. deploy/SERVER.md has every screen.

1. Desktop button -> 5 Make the server setup file.
   SAVE the console link it prints. It is your login.
2. digitalocean.com -> Create -> Droplets -> Ubuntu 24.04, Basic,
   $6/month. Advanced Options -> Add Initialization scripts -> paste
   the whole server-setup file. Create. Note the IP address.
3. At your registrar: A record, name @, value = that IP address.
4. After ~15 minutes open the console link on your phone and Add to
   Home Screen. Delete the server-setup file from the laptop.
5. Desktop button -> 4 What still needs doing. Expect DKIM to be
   the only thing still red."""),

    (2, "LAUNCH 4: DNS - turn on DKIM", 20, """24-72 hours after Gmail was switched on.

1. admin.google.com -> Apps -> Google Workspace -> Gmail ->
   Authenticate email -> Generate new record -> 2048-bit.
2. Paste it at your registrar as a TXT record (desktop button ->
   3 Email domain shows the exact name and value).
3. Wait an hour, then back in Google Admin -> Start authentication.
   It can take up to 48 hours to show as authenticating.
4. Desktop button -> 3 Email domain, again, until it says ready.
   Then 4 What still needs doing: all green means you can send.

Until then: send a few real emails a day from the new address."""),

    (3, "LAUNCH 5: Line up 2-3 pilots", 45, """Nothing sells this service like a real before-and-after.

Think of 2-3 local trades businesses you or someone you know can reach
directly - a friend's plumber, a cousin's roofing crew. Offer:
"Free for three months, in return for letting me measure it and
write it up."

Console -> Pipeline -> Add a business you know. Then Sign them up ->
Free pilot. It starts at once, costs them nothing, and they are never
sent cold email. After 45 days, open Before & after on their client
card. It tells you honestly whether there is anything worth publishing.

These don't need the cold-email channel, so they can start today."""),

    (4, "LAUNCH 6: Pick your trade and market", 90, """Decide, then commit. Specificity is what makes the email land.

Pick ONE trade and 2-3 mid-size metros - less competition than the big
cities, same budgets. HVAC has the highest urgency and the worst AI
visibility; the system knows 22 trades if you'd rather another.

Desktop button -> 6 Practice run (nothing real is sent) shows a
month of the business run end to end.

Then open three audits on the console and read them critically.
Would you pay $997/mo for that? If not, say what's wrong - that is
the most useful thing you can do this week."""),

    (5, "LAUNCH 7: FIRST SEND", 30, """The day the doctor is all green. Not before.

  Console -> Needs you now -> Review drafts. READ ALL OF THEM.
  Approve the ones you'd put your name to. Send approved.

The system sends 10 today and climbs by itself: 20 from day 4, 40 from
day 8, 70 from day 15, 100 from day 22. Do not raise it.

The first 50 emails are a test, not a campaign. If nobody replies, the
problem is the subject line or the targeting - not the volume."""),

    (8, "LAUNCH 8: First-week check", 30, """Two numbers, every day from now on:
  bounces    must stay under 2%
  complaints must stay under 0.1%

The system pauses cold sending by itself if bounces reach 2%. Complaints
it cannot measure, so watch for them: an angry reply or a spam report
means slow down and look at who you are emailing. Deliverability is the
one thing you cannot buy back.

Replies should be starting. Every one gets an answer within two hours
during the day. The Concierge drafts it; you read it and send."""),

    (14, "LAUNCH 9: Deliver to anyone who said yes", 60, """Someone signed? Here is the whole of it:

1. They pay through the link. The console moves them to active (or tap
   They paid).
2. Approve the welcome email THE SAME DAY. The gap between paying and
   hearing from you is where second thoughts live.
3. The Fixer drafts their files and a step-by-step install guide for
   their website platform. Send it, or install it for them.
4. The site check tells you when the fixes are really live on their
   site. The monthly report goes out by itself.

Review the first three clients' reports by hand before they go."""),

    (28, "LAUNCH 10: Diagnose, do not guess", 120, """Thirty days. Be honest about the numbers.

Console -> money view.

Targets:    250 audited / 400 sent / 8-15 replies / 4-8 calls / 2-3 clients
Acceptable: 150 audited / 250 sent / 4 replies   / 2 calls   / 1 client

ONE client by day 30 puts you on the pessimistic curve - which still
clears $5k inside a year. That is a win, not a disappointment.

ZERO clients is a signal, not a failure. Diagnose which step broke and
fix ONLY the earliest broken one:

  not delivered -> DNS/reputation. Everything else is wasted until fixed.
  no replies    -> subject line, then targeting.
  no calls      -> report not landing. Lead with the competitor gap.
  no closes     -> talk less. Show the test log. Ask for the card.

Fixing the pitch while your email lands in spam wastes a month."""),
]

#: Saturday start times available for long blocks, and the weekday evening slot.
SATURDAY_SLOTS = (time(9, 0), time(13, 0))
WEEKDAY_EVENING = time(18, 0)


def launch_events(start: date, brand: str = DEFAULT_BRAND) -> list[Event]:
    """Assign real dates sequentially so nothing collides or runs out of order.

    Rules: long blocks (>=90 min) need a Saturday; short ones take a weekday
    evening; Sunday is never used; each task starts no earlier than its
    stated offset and no earlier than the task before it.
    """
    events: list[Event] = []
    used: set[tuple[date, time]] = set()
    cursor = start

    for offset, summary, minutes, desc in LAUNCH:
        day = max(cursor, start + timedelta(days=offset))
        placed: datetime | None = None

        # Walk forward day by day until a suitable free slot appears.
        for _ in range(60):
            weekday = day.weekday()
            if weekday == 6:  # Sunday is the rest day, always
                day += timedelta(days=1)
                continue

            if minutes >= 90:
                if weekday == 5:  # Saturday
                    for slot in SATURDAY_SLOTS:
                        if (day, slot) not in used:
                            placed = datetime.combine(day, slot)
                            break
            elif weekday < 5 and (day, WEEKDAY_EVENING) not in used:
                placed = datetime.combine(day, WEEKDAY_EVENING)

            if placed:
                break
            day += timedelta(days=1)

        if not placed:  # pragma: no cover - 60 days is always enough
            placed = datetime.combine(day, WEEKDAY_EVENING)

        used.add((placed.date(), placed.time()))
        cursor = placed.date()
        events.append(Event(summary, placed, minutes, desc,
                            alarm_minutes=30, categories=f"{brand} Launch"))
    return events


def warmup_events(dns_done: date, first_send: date,
                  brand: str = DEFAULT_BRAND) -> list[Event]:
    """Daily warmup reminders, from the day after DNS until the first send.

    Warming a domain before SPF/DKIM/DMARC exist trains the wrong reputation,
    so this is anchored to the DNS task's real date, not a fixed offset.
    """
    begin = dns_done + timedelta(days=1)
    return [Event(
        f"{brand}: Email warmup (10 min)",
        datetime.combine(begin, time(19, 30)), 10, WARMUP,
        f"FREQ=DAILY;UNTIL={_dt(first_send, time(19, 30))}",
        alarm_minutes=5, categories=f"{brand} Launch",
    )]


def build_calendar(start: date, include_launch: bool = True,
                   brand: str = DEFAULT_BRAND) -> str:
    # ``utcnow`` returns a naive datetime and is deprecated from 3.12; the
    # DTSTAMP it feeds is required to be UTC, so say so explicitly.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{_prodid(brand)}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        _fold(f"X-WR-CALNAME:{brand} - Business Schedule"),
        _fold("X-WR-CALDESC:Daily operating rhythm and 30-day launch plan."),
    ]
    if include_launch:
        launch = launch_events(start, brand)
        first_send = next(e.start.date() for e in launch if "FIRST SEND" in e.summary)
        dns_done = next(e.start.date() for e in launch if "DNS" in e.summary)
        last_launch = max(e.start.date() for e in launch)
        events = (
            launch
            + warmup_events(dns_done, first_send, brand)
            + recurring_events(start, ops_from=first_send,
                               deep_from=last_launch + timedelta(days=1), brand=brand)
        )
    else:
        events = list(recurring_events(start, brand=brand))
    for ev in events:
        lines += ev.to_ics(stamp)
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
