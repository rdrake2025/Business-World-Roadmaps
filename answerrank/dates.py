"""The dates ahead for each client, and a calendar file to keep them.

A pilot has four dates to plan around: its next measurement, the day the
before-and-after is ready, the day the offer is written and the day the
free months end. Measurements only happen while AnswerRank is open, so on a
laptop a forgotten month is a measurement missed and a before-and-after
pushed back. The vault's Dashboard lists the dates; the calendar file puts
them on your phone with a reminder on the morning.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

#: What happens on each kind of date. ``{who}`` is the client's name, or a
#: link to their note in the vault.
SAYS = {
    "first": "{who}'s first measurement. Open AnswerRank and leave it ten minutes.",
    "measure": "{who} measured again. Open AnswerRank and leave it ten minutes.",
    "case": "{who}'s before-and-after is ready to show (it says honestly whether it worked).",
    "offer": "{who}'s offer is written for you (Inbox). Send it.",
    "end": "{who}'s free pilot ends. If they said yes: **They said yes: start paid plan** "
           "on the Pilots card.",
}

#: The calendar's short titles.
TITLES = {
    "first": "AnswerRank: measure {who} (open it for 10 minutes)",
    "measure": "AnswerRank: measure {who} (open it for 10 minutes)",
    "case": "AnswerRank: {who}'s before-and-after is ready",
    "offer": "AnswerRank: send {who} their offer",
    "end": "AnswerRank: {who}'s free pilot ends",
}

#: Days between measurements, as on the Pilots card.
REMEASURE_DAYS = 28


def _day(iso: str, plus: int = 0) -> str:
    try:
        d = datetime.fromisoformat((iso or "").replace("Z", "+00:00")) + timedelta(days=plus)
    except ValueError:
        return (iso or "")[:10]
    return d.strftime("%Y-%m-%d")


def ahead(store, client, now: datetime | None = None,
          days: int = 100) -> list[tuple[str, str]]:
    """One client's dated steps from today, as (YYYY-MM-DD, kind), soonest
    first. A measurement that is overdue is due today; other dates that have
    passed are left out."""
    from .casestudy import MIN_DAYS
    from .sales import PILOT_NOTICE_DAYS, pilot_ends

    if client.status != "active":
        return []
    now = now or datetime.now(timezone.utc)
    today = now.date().isoformat()
    horizon = (now + timedelta(days=days)).date().isoformat()
    audits = store.audit_history(client.business.id, limit=24, comparable=True)
    out = []
    if audits:
        out.append((max(_day(audits[0].created_at, REMEASURE_DAYS), today), "measure"))
    else:
        out.append((today, "first"))
    if client.plan == "pilot":
        start = (audits[-1].created_at if audits else client.started_at) or now.isoformat()
        out.append((_day(start, MIN_DAYS), "case"))
        end = pilot_ends(client)
        out.append((_day(end, -PILOT_NOTICE_DAYS), "offer"))
        out.append((end, "end"))
    return sorted((d, k) for d, k in out if today <= d <= horizon)


def _escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\n", "\\n"))


def _fold(line: str) -> list[str]:
    """Lines over 75 octets continue on the next, after one space (RFC 5545)."""
    out, raw = [], line.encode("utf-8")
    while len(raw) > 75:
        cut = 75 if not out else 74
        while cut and (raw[cut] & 0xC0) == 0x80:   # never split a character
            cut -= 1
        out.append(raw[:cut].decode("utf-8"))
        raw = raw[cut:]
    out.append(raw.decode("utf-8"))
    return [out[0]] + [" " + part for part in out[1:]]


def calendar(store, now: datetime | None = None) -> str:
    """Every active pilot's dates as an iCalendar file: all-day events with a
    9am reminder, on any phone or computer calendar. Importing it again
    updates the events rather than adding them twice."""
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//AnswerRank//Pilot dates//EN",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "X-WR-CALNAME:AnswerRank pilots"]
    for c in store.get_clients("active"):
        if c.plan != "pilot":
            continue
        who = c.business.name
        for when, kind in ahead(store, c, now):
            day = date.fromisoformat(when)
            # A measurement's date moves each time one is taken, so each one
            # is its own event; the others are fixed and keep one each.
            uid = f"{c.id}-{kind}-{when}" if kind in {"first", "measure"} else f"{c.id}-{kind}"
            says = SAYS[kind].format(who=who).replace("**", "")
            lines += ["BEGIN:VEVENT", f"UID:{uid}@answerrank", f"DTSTAMP:{stamp}",
                      f"DTSTART;VALUE=DATE:{day:%Y%m%d}",
                      f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}",
                      f"SUMMARY:{_escape(TITLES[kind].format(who=who))}",
                      f"DESCRIPTION:{_escape(says)}", "TRANSP:TRANSPARENT",
                      "BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_escape(says)}",
                      "TRIGGER:PT9H", "END:VALARM", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(part for line in lines for part in _fold(line)) + "\r\n"
