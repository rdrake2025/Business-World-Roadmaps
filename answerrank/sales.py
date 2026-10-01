"""Signing someone up: one path, whoever does it.

The phone's Sign them up button, the Concierge hearing "sign us up" on
Autopilot, and a payment that arrives from someone who bought straight from
their report all make a client the same way. Three copies of this would be
three ways for a new client to be counted twice, billed wrongly or never
welcomed.
"""

from __future__ import annotations

from typing import Any

from .models import Client, OutreachMessage, Prospect, now_iso


def plan_for_prospect(settings, prospect: Prospect) -> str:
    """The plan this trade is quoted, which is the plan they are sold."""
    return settings.pricing.plan_for(settings.quote_for(prospect.business.vertical)) \
        or "growth"


def sign_up(store, settings, prospect: Prospect, plan: str = "growth",
            send_link: bool = True) -> dict[str, Any]:
    """They said yes. A client is created *awaiting payment* (a pilot is
    free and starts at once), and the payment link goes to them unless it
    already has. Returns what happened, or ``{"error": ...}``."""
    from . import payments, sending

    if prospect.stage == "won":
        return {"error": f"{prospect.business.name} is already a client"}
    plan = (plan or "growth").lower()
    if plan not in settings.pricing.PLANS:
        return {"error": f"unknown plan {plan!r}"}
    price = settings.pricing.plan_price(plan)
    pilot = plan == "pilot"

    client = Client(business=prospect.business, plan=plan, mrr=price,
                    status="active" if pilot else "awaiting_payment")
    client_id, created = store.start_client(client)
    if not created:
        return {"error": f"{prospect.business.name} is already on the books"}
    client.id = client_id

    prospect.stage = "won"
    prospect.notes = (prospect.notes or "") + f" | won on {plan} at ${price:,.0f}"
    store.upsert_prospect(prospect)
    store.withdraw_cold(prospect.id)
    store.record_outcome(prospect_id=prospect.id, vertical=prospect.business.vertical,
                         step=prospect.touches, kind="won", note=f"{plan} ${price:,.0f}")

    link = "" if pilot else payments.link_for(
        settings, plan, payments.reference_for(prospect, client), prospect.business.email)
    email = prospect.business.email
    # They just said yes: the link goes now, not after another visit to the
    # inbox. It is the same fixed email every time.
    if send_link and link and not payments.link_already_sent(store, prospect, settings, plan):
        subject, body = payments.payment_email(prospect, client, settings)
        store.save_message(OutreachMessage(
            prospect_id=prospect.id, subject=subject, body=body, kind="invoice",
            sequence_step=0, status="approved" if email else "drafted",
            scheduled_for=now_iso()))
        if email:
            sending.kick(store, settings, delay=5)
    return {"client_id": client_id, "client": client, "plan": plan, "mrr": price,
            "status": client.status, "payment_link": link, "pilot": pilot,
            "email": email}


# ---------------------------------------------------------------------------
# The end of a free pilot
# ---------------------------------------------------------------------------

#: How long a free pilot lasts: the offer in PILOTS.md and the Pilot Kit.
PILOT_DAYS = 90
#: How many days before the end the offer is written.
PILOT_NOTICE_DAYS = 7


def pilot_ends(client) -> str:
    """The date (YYYY-MM-DD) a free pilot's three months are up."""
    from datetime import datetime, timedelta, timezone
    try:
        start = datetime.fromisoformat((client.started_at or "").replace("Z", "+00:00"))
    except ValueError:
        start = datetime.now(timezone.utc)
    return (start + timedelta(days=PILOT_DAYS)).date().isoformat()


def offer_plan(settings, vertical: str) -> str:
    """What a pilot is offered: their trade's plan, but never Managed, which
    means hands-on work on their site; that's a conversation, not an email."""
    plan = settings.pricing.plan_for(settings.quote_for(vertical)) or "growth"
    return "growth" if plan == "managed" else plan


def pilot_offer(store, settings, client) -> tuple[str, str]:
    """The email near the end of a free pilot: where they stand, honestly,
    the price, and the choice. A result inside the noise is called that."""
    from datetime import date

    from . import casestudy, payments, playbook

    ev = casestudy.evidence(store, client)
    prospect = store.prospect_for_business(client.business)
    plan = offer_plan(settings, client.business.vertical)
    price = settings.pricing.plan_price(plan)
    ends = date.fromisoformat(pilot_ends(client)).strftime("%B %d").replace(" 0", " ")
    q = ev.questions or 10
    counts = f"{ev.named_before} of {q} questions at the start and {ev.named_after} of {q} now"
    if ev.verdict == "moved":
        stand = (f"The numbers moved: you were named in {counts}, and your visibility "
                 f"score went from {ev.score_before:.0f} to {ev.score_after:.0f} out of 100.")
    elif ev.verdict == "flat":
        stand = (f"Honestly, it hasn't moved enough yet to count: you were named in "
                 f"{counts}. AI answers vary from day to day, and this is inside that."
                 + ("" if ev.fixes_live else " The changes aren't live on your site yet, "
                    "and that's the first thing to fix."))
    elif ev.verdict == "worse":
        stand = (f"It went the wrong way: you were named in {counts}. I'd rather tell "
                 f"you that than sell you more of it.")
    else:
        stand = ("It's still early to judge: the engines pick changes up when they next "
                 "read your site, and that can take weeks.")
    link = payments.link_for(settings, plan, payments.reference_for(prospect, client),
                             prospect.business.email if prospect else "")
    keep = (f"To keep going it's ${price:,.0f} a month, no contract, cancel any time"
            + (f": {link}" if link else ". Reply and I'll send the details."))
    body = playbook.email_body(
        "Hi,",
        f"Your free three months end on {ends}. Here's where things stand.",
        stand, keep,
        "If you'd rather stop there, that's completely fine: reply and I'll stop "
        "measuring. Either way, thank you for trying it, and for the feedback.",
        f"{settings.brand}\n{settings.website}".strip())
    return f"Your free pilot ends {ends}", body


def convert_pilot(store, settings, client, plan: str = "") -> dict[str, Any]:
    """A pilot said yes to a paid plan. The same client, now awaiting payment;
    the payment link goes to them as for any sign-up."""
    from . import payments, sending

    if client.plan != "pilot":
        return {"error": f"{client.business.name} isn't on a free pilot"}
    plan = (plan or offer_plan(settings, client.business.vertical)).lower()
    if plan not in ("starter", "growth", "managed"):
        return {"error": f"unknown plan {plan!r}"}
    price = settings.pricing.plan_price(plan)
    client.plan, client.mrr, client.status = plan, price, "awaiting_payment"
    store.upsert_client(client)
    prospect = store.prospect_for_business(client.business)
    store.record_outcome(prospect_id=prospect.id if prospect else client.id,
                         vertical=client.business.vertical, kind="won",
                         note=f"pilot converted: {plan} ${price:,.0f}")
    email = prospect.business.email if prospect else ""
    link = payments.link_for(settings, plan, payments.reference_for(prospect, client), email)
    if link and prospect and not payments.link_already_sent(store, prospect, settings, plan):
        subject, body = payments.payment_email(prospect, client, settings)
        store.save_message(OutreachMessage(
            prospect_id=prospect.id, subject=subject, body=body, kind="invoice",
            sequence_step=0, status="approved" if email else "drafted",
            scheduled_for=now_iso()))
        if email:
            sending.kick(store, settings, delay=5)
    return {"client_id": client.id, "name": client.business.name, "plan": plan,
            "mrr": price, "status": client.status, "payment_link": link, "email": email}
