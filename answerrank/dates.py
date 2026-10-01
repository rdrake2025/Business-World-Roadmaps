"""The dates ahead for each client, and a calendar file to keep them.

A pilot is measured three times (at the start, for the before-and-after,
and for the offer; see sales.py), and has two more dates: the day the offer
is written and the day the free months end. Measurements only happen while
AnswerRank is open, so on a laptop a forgotten day is a measurement missed
and a before-and-after pushed back. The vault's Dashboard lists the dates;
the calendar file puts them on your phone with a reminder on the morning.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

#: What happens on each kind of date. ``{who}`` is the client's name, or a
#: link to their note in the vault.
SAYS = {
    "first": "{who}'s first measurement. Open AnswerRank and leave it ten minutes.",
    "measure": "{who} measured again. Open AnswerRank and leave it ten minutes.",
    "mid": "{who} measured for the before-and-after. Open AnswerRank and leave it ten "
           "minutes; the before-and-after is ready straight after (it says honestly "
           "whether it worked).",
    "final": "{who} measured one last time, for the offer. Open AnswerRank and leave it "
             "ten minutes.",
    "offer": "{who}'s offer is written for you (Inbox). Send it.",
    "end": "{who}'s free pilot ends. If they said yes: **They said yes: start paid plan** "
           "on the Pilots card.",
}

#: The calendar's short titles.
TITLES = {
    "first": "AnswerRank: measure {who} (open it for 10 minutes)",
    "measure": "AnswerRank: measure {who} (open it for 10 minutes)",
    "mid": "AnswerRank: measure {who} for the before-and-after",
    "final": "AnswerRank: measure {who} for the offer",
    "offer": "AnswerRank: send {who} their offer",
    "end": "AnswerRank: {who}'s free pilot ends",
}

#: Days between a paying client's measurements (a pilot's are in sales.py).
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
    from .sales import PILOT_FINAL_DAYS_LEFT, PILOT_NOTICE_DAYS, pilot_ends, pilot_next

    if client.status != "active":
        return []
    now = now or datetime.now(timezone.utc)
    today = now.date().isoformat()
    horizon = (now + timedelta(days=days)).date().isoformat()
    audits = store.audit_history(client.business.id, limit=24, comparable=True)
    out = []
    if client.plan != "pilot":
        out.append((max(_day(audits[0].created_at, REMEASURE_DAYS), today), "measure")
                   if audits else (today, "first"))
    else:
        nxt = pilot_next(client, audits, now)
        if nxt:
            out.append(nxt)
            if nxt[1] == "mid":
                # And the last one, for the offer, once the middle one is done.
                out.append((_day(pilot_ends(client), -PILOT_FINAL_DAYS_LEFT), "final"))
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
            # One event per kind: an overdue measurement's date moves to
            # today, and importing again moves the event rather than adding
            # another.
            uid = f"{c.id}-{kind}"
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
