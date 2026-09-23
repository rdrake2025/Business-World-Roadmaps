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

MORNING_OPS = """Your 20 minutes that keep the business moving.

1. python3 run.py agents
   -> any ERR twice in a row? investigate before anything else.

2. python3 run.py inbox --full
   -> READ every draft. They go out under your name.

3. python3 run.py approve
   python3 run.py send --limit 40

4. Check the reply inbox. Anything in there beats everything else today.

If you only ever do this one block, the business still runs."""

LUNCH_CHECK = """10 minutes. Replies only.

Answer anyone who responded. Speed matters more than polish -
a reply inside an hour converts far better than a perfect one tomorrow.

If they asked for the report:
  python3 run.py audit "<Business>" <City> --state <ST> \\
      --vertical <vertical> --website <url> --report

Send it with one line: "Here it is - happy to walk you through it,
20 minutes this week?" """

SALES_WINDOW = """Owners of home service businesses are reachable now -
off the tools, not yet at dinner. This is the best calling window you have.

Per business/02_SALES_PLAYBOOK.md:
  0-2 min   "How do people find you today when they don't know you?"
  2-8 min   Share the report. Walk the test log. Stop at the competitor row.
            THEN SAY NOTHING. Let the silence work.
  8-12 min  The three causes: schema, answer-shaped content, GBP + citations.
  12-15 min The offer. $997/mo. Ask for the card ON THE CALL.

Do not offer to "send a proposal". That is where these deals die.

Closed one?  python3 run.py win "<Business>" --plan growth"""

DEEP_WORK = """Two hours. The only long block in your week - protect it.

1. python3 run.py dashboard
   Where are you against $5k? Which funnel step is weakest?

2. python3 run.py prospects --stage audited --limit 30
   Top up the list if it is thinning.

3. Review any client report that went out. Would YOU pay $997 for it?

4. Fix the weakest funnel number - and only that one:
     not delivered  -> DNS/reputation. Stop sending. Fix SPF/DKIM/DMARC.
     no replies     -> subject line and targeting.
     no calls       -> report is not landing. Lead with the competitor gap.
     no closes      -> talk less, show the test log, ask for the card.

5. Ten minutes: write down what you learned about your vertical this week.
   That accumulates into the expertise you sell."""

MONTHLY_CLOSE = """Monthly close - 45 minutes. Do not skip this one.

1. python3 run.py dashboard
   python3 run.py budget

2. Reconcile the ledger against your bank and Stripe.

3. MOVE 30% OF PROFIT TO THE TAX ACCOUNT. Today, not later.
   Money that sits in the main account gets spent.

4. python3 run.py budget --profit <this month's profit>
   Follow the split it gives you.

5. Any client whose score is flat two months running: call them.
   They churn quietly, and always before they complain.

6. Re-read one report you sent as if you were the client."""

WARMUP = """10 minutes. Keep the sending domain warming.

Send 5-10 real, personal emails from the sending address today - to
yourself, to friends, to anyone who will reply. Replies are the signal
that builds reputation.

Do NOT start cold outreach until day 18. Sending cold from a cold domain
burns it permanently, and a burned domain is abandoned, not repaired."""

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
    (0, "LAUNCH 1: Install and prove it works", 120, """Nothing costs money today.

1. git clone the repo onto your laptop
2. pip install -r requirements.txt
3. python3 -m unittest discover -s tests     (expect 43 passing)
4. python3 run.py tick --force               (watch the fleet run)
5. python3 run.py budget-init                (then edit budget.yml with
   YOUR real numbers - guesses give you a runway you cannot trust)

6. Audit three businesses you personally know:
   python3 run.py audit "<Name>" <City> --state <ST> --vertical hvac \\
       --website <url> --report

READ THOSE REPORTS CRITICALLY. Would you pay $997/mo for that?
If not, that is today's real work - fix it before a stranger sees one."""),

    (0, "LAUNCH 2: Pick your vertical and market", 90, """Decide, then commit. Specificity is what makes the email land.

Pick ONE vertical: hvac, plumbing, roofing, dental, or legal.
Pick 2-3 metros. Mid-size beats huge - less competition, same budgets.

Suggested: HVAC. Highest urgency, highest ticket ($6-12k jobs),
and the worst AI visibility of any vertical tested.

Then run 20 audits in it and look for the pattern:
what do the VISIBLE businesses have that the invisible ones don't?

Write that down. That is your expertise, and it is what you say on calls."""),

    (3, "LAUNCH 3: Buy the sending domain ($12)", 45, """First money spent. Twelve dollars.

1. Buy a SEPARATE sending domain - never your main one.
   If it burns, your real domain and client email survive.
   Pattern: <brand>-mail.com, get<brand>.com, <brand>hq.com

2. Set up Google Workspace Business Starter ($7.20/mo, 1 seat).
   You need real authenticated sending, not a free inbox.

Running total: $12 one-time, $7.20/mo. That is the whole spend so far."""),

    (4, "LAUNCH 4: DNS - SPF, DKIM, DMARC", 60, """The most important hour of the whole launch.

In your domain's DNS:
  SPF    TXT  @         v=spf1 include:_spf.google.com ~all
  DKIM   TXT  (Google Admin generates this - enable it and paste)
  DMARC  TXT  _dmarc    v=DMARC1; p=quarantine; rua=mailto:you@domain

p=none is NOT enough in 2026. It must be quarantine or reject.

Verify:
  dig +short TXT yourdomain.com
  dig +short TXT _dmarc.yourdomain.com

Compliant senders see ~89% inbox placement. Non-compliant see 22-34%
filtered or rejected outright. This hour is the difference.

WARMUP STARTS TOMORROW and runs two weeks. It gates everything else."""),

    (5, "LAUNCH 5: API keys + first real audits", 45, """Put $15 of credit on the APIs. It goes further than you expect -
a full 10-prompt, 4-engine audit costs about $0.06.

  export OPENAI_API_KEY=...
  export ANTHROPIC_API_KEY=...
  export SERPER_API_KEY=...        (free tier is plenty to start)

Then re-run an audit and compare it to the simulated one from day 1.
This is the first time you see REAL data about a real business.

Running total: $27 one-time, $12.20/mo."""),

    (6, "LAUNCH 6: Build the prospect list", 120, """Target 200-300 qualified prospects in your vertical and metros.

  python3 run.py tick --force
  python3 run.py prospects

Qualification bar - all four must be true:
  1. Visibility score under 55       (there is a real problem)
  2. A competitor is beating them    (there is a real threat)
  3. They have a website             (there is something to fix)
  4. They already spend on marketing (truck wraps, ads, real GBP)

Number 4 you check by hand. A business with no website and no marketing
spend is not a cheap client - it is a client who never pays.

Let the auditor run overnight."""),

    (7, "LAUNCH 7: One-page site + unsubscribe", 120, """Keep it to one page. A logo is not what closes a $997 deal.

  - What it is, who it is for, the three tiers, a booking link
  - Privacy policy and terms (templates are fine)
  - THE UNSUBSCRIBE ENDPOINT AT /unsubscribe

That last one is legally required and blocks sending until it works.
Wire it to the suppression list.

Free hosting is fine: GitHub Pages, Netlify, Cloudflare Pages."""),

    (9, "LAUNCH 8: Stripe + booking link", 45, """  - Stripe account, verified
  - Payment links for all four tiers: $297, $499, $997, $1997
  - A calendar booking link (Cal.com free tier works)

Put the booking link in your email signature today."""),

    (13, "LAUNCH 9: Mid-warmup check", 30, """Halfway through warmup.

  python3 run.py send --dry-run

Confirm: DNS passes, no preflight errors, physical address set in
answerrank.yml. If anything is red, fix it now - you send in four days.

Still warming. Do not start cold outreach yet."""),

    (17, "LAUNCH 10: FIRST SEND - 20 emails", 60, """The business starts today.

  python3 run.py send --dry-run     (confirm clean)
  python3 run.py inbox --full       (READ ALL 20. Every word.)
  python3 run.py approve
  python3 run.py send --limit 20

Twenty. Not two hundred.

The first 50 emails are a test, not a campaign. If nobody replies, the
problem is the subject line or the targeting - not the volume. Find that
out for 50 emails, not 500."""),

    (18, "LAUNCH 11: Ramp to 40/day", 30, """  python3 run.py send --limit 40

Watch two numbers daily from here:
  bounces    must stay under 2%
  complaints must stay under 0.1%

Either one drifts up -> STOP SENDING. Verify the list. Re-warm.
Deliverability is the one resource you cannot buy back."""),

    (21, "LAUNCH 12: Ramp to 60-100/day", 30, """  python3 run.py send --limit 60

Replies should be appearing by now. Every reply gets an answer within
two hours during the day.

Expected at this point: 1-3% reply rate. On 200 sent, that is 2-6 replies."""),

    (24, "LAUNCH 13: Deliver to anyone who said yes", 90, """Send the full report to everyone who asked, and offer the 20-minute call.

  python3 run.py audit "<Business>" <City> --state <ST> \\
      --vertical <v> --website <url> --report

Review the report by hand before it goes. Every time, for your first
three prospects. After that, trust the fleet."""),

    (28, "LAUNCH 14: Diagnose, do not guess", 120, """Thirty days. Be honest about the numbers.

  python3 run.py dashboard
  python3 run.py budget

Targets:   250 audited / 400 sent / 8-15 replies / 4-8 calls / 2-3 clients
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
