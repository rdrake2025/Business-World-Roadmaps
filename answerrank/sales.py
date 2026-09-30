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
