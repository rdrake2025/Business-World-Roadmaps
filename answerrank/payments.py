"""Getting paid, and knowing that you have been.

Until this module the sale ended at "I'll send the invoice over today" — and
nothing sent one. Tapping Won made the client active on the spot, so they
were welcomed, audited and delivered to, and the Bookkeeper counted their fee
as revenue, whether or not any money had arrived.

Now a yes becomes a client **awaiting payment**. The close email carries a
Stripe payment link for their plan; the link is a recurring monthly price, so
Stripe charges every month after that without anyone sending an invoice.
Revenue counts from the day payment is confirmed, and onboarding starts then.

Confirming a payment happens one of two ways:

* **Automatically**, if a read-only Stripe key is saved (``run.py keys``).
  The system asks Stripe which checkout sessions completed, matches each to
  the client by the ``client_reference_id`` the link carried, and later
  checks each subscription is still paying. No webhook is needed, which
  matters: a webhook needs a public server, and this may be running on a
  laptop.
* **By hand**, by tapping Paid in the console when the money lands.

Either way, a client who has not paid gets one friendly reminder carrying the
link again, and is flagged to the operator if they still have not.

Stripe facts this relies on, checked against Stripe's documentation:
payment links accept ``client_reference_id`` (letters, digits, dashes and
underscores, up to 200 characters) and ``prefilled_email`` as URL
parameters, including for recurring prices; completed sessions report
``status``, ``payment_status``, ``client_reference_id`` and ``subscription``;
and a restricted key can be limited to reading Checkout Sessions and
Subscriptions.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .models import Client, OutreachMessage, Prospect, now_iso

log = logging.getLogger("answerrank.payments")

STRIPE_API = "https://api.stripe.com/v1"
_REF_OK = re.compile(r"^[A-Za-z0-9_-]{1,200}$")

#: What a Stripe subscription status means for the client record.
SUBSCRIPTION_STATUS = {
    "active": "active", "trialing": "active",
    "past_due": "past_due", "unpaid": "past_due",
    "canceled": "churned", "incomplete_expired": "churned",
}


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

def base_link(settings, plan: str) -> str:
    return (getattr(settings, "payment_links", None) or {}).get((plan or "").lower(), "").strip()


def link_for(settings, plan: str, reference: str = "", email: str = "") -> str:
    """The plan's payment link, carrying who it is for.

    ``client_reference_id`` is what lets a completed payment be matched to
    the client without anyone typing anything. Stripe silently drops a value
    with characters it does not allow, so an invalid one is not sent at all
    rather than sent and lost.
    """
    base = base_link(settings, plan)
    if not base:
        return ""
    parts = urlparse(base)
    query = dict(parse_qsl(parts.query))
    if reference and _REF_OK.match(reference):
        query["client_reference_id"] = reference
    if email and "@" in email:
        query["prefilled_email"] = email
    return urlunparse(parts._replace(query=urlencode(query)))


def reference_for(prospect: Prospect | None, client: Client | None = None) -> str:
    """One id that exists before the client does: the prospect's.

    The close email is written when they say "sign us up", before anyone has
    tapped Won, so the client id does not exist yet. The prospect id does,
    and survives into the client through the business it points at.
    """
    if prospect is not None:
        return prospect.id
    return client.id if client is not None else ""


def link_already_sent(store, prospect: Prospect, settings, plan: str,
                      days: int = 14) -> bool:
    """Whether this plan's payment link went (or is going) out to them.

    The plan matters. The close email carries the link for the plan quoted;
    if the operator then signs them on a different one, "a link was sent"
    is not good enough — they would pay the wrong price.
    """
    base = base_link(settings, plan)
    if not base:
        return False
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    recent = [m for m in store.messages_for(prospect.id)
              if m.status in {"drafted", "approved", "sent"} and m.created_at >= cutoff]
    # A payment email, or the last thing they got (the answer to "sign us
    # up"). A link further back, in the report, doesn't count: someone who
    # has just said yes should get it in front of them again.
    if any(m.kind == "invoice" and base in (m.body or "") for m in recent):
        return True
    return bool(recent) and base in (recent[-1].body or "")


def payment_email(prospect: Prospect, client: Client, settings, reminder: bool = False) -> tuple[str, str]:
    from . import playbook

    link = link_for(settings, client.plan, reference_for(prospect, client),
                    prospect.business.email)
    price = f"${client.mrr:,.0f}/month"
    if reminder:
        subject = f"Getting {playbook.short_name(prospect.business.name, 28)} started"
        opening = ("Just making sure the payment link reached you. Nothing starts "
                   "until it's set up, and I'd rather not lose the week.")
    else:
        subject = f"Your link to get {playbook.short_name(prospect.business.name, 28)} started"
        opening = f"Great to have {prospect.business.name} on board."
    body = playbook.email_body(
        "Hi,",
        opening,
        f"Here's the link to set up the {price} payment. It renews monthly and "
        f"you can cancel any time:",
        link,
        "As soon as it's through you'll get a short welcome note with the two "
        "things I need from you, and I start on the fixes from your report.",
        f"{settings.brand}\n{settings.website}")
    return subject, body


# ---------------------------------------------------------------------------
# Confirming payment
# ---------------------------------------------------------------------------

def mark_paid(store, client: Client, reference: str = "", when: str = "") -> Client:
    """The money arrived. The client becomes active, and this month counts.

    Books the month's revenue immediately under the same key the Bookkeeper
    uses, so a later Bookkeeper run cannot count it a second time.
    """
    if client.status == "active" and client.paid_at:
        return client
    client.status = "active"
    client.paid_at = when or now_iso()
    if reference:
        client.payment_ref = reference
    store.upsert_client(client)
    store.record_outcome(prospect_id=client.id, vertical=client.business.vertical,
                         kind="paid", note=f"{client.plan} ${client.mrr:,.0f}"
                                           + (f" ({reference})" if reference else ""))
    if client.mrr > 0:
        from .agents.bookkeeper import bill_month
        bill_month(store, client)
    return client


def _stripe_get(key: str, path: str, params: dict[str, Any] | None = None,
                timeout: int = 20) -> dict[str, Any]:
    import requests
    resp = requests.get(f"{STRIPE_API}/{path}", params=params or {},
                        auth=(key, ""), timeout=timeout)
    if resp.status_code == 401:
        raise PermissionError("Stripe refused the key")
    if resp.status_code == 403:
        raise PermissionError("the Stripe key cannot read this — give it "
                              "Read on Checkout Sessions and Subscriptions")
    resp.raise_for_status()
    return resp.json()


def completed_sessions(key: str, days: int = 60,
                       get: Callable[..., dict] = _stripe_get) -> list[dict[str, Any]]:
    """Checkout sessions completed in the last ``days``, newest first."""
    since = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
    out: list[dict[str, Any]] = []
    params: dict[str, Any] = {"status": "complete", "limit": 100, "created[gte]": since}
    for _page in range(5):
        data = get(key, "checkout/sessions", params)
        rows = data.get("data") or []
        out.extend(rows)
        if not data.get("has_more") or not rows:
            break
        params["starting_after"] = rows[-1]["id"]
    return out


def _plan_from_session(settings, session: dict[str, Any]) -> str:
    """Which plan a checkout was for: the price paid, or the link used."""
    amount = (session.get("amount_total") or 0) / 100
    plan = settings.pricing.plan_for(amount) if amount else ""
    if plan:
        return plan
    link = str(session.get("payment_link") or "")
    for name, url in (getattr(settings, "payment_links", None) or {}).items():
        if link and link in url:
            return name
    return "growth"


def _self_serve(store, settings, session: dict[str, Any]) -> str:
    """Someone paid straight from a link in their report, with nobody having
    signed them up. Make them a client and mark them paid. Returns their name,
    or "" if the payment isn't theirs to claim.

    Before this, a payment from anyone not already on the waiting list was
    ignored: the money arrived and nothing happened, which on Autopilot is
    the most expensive silence there is.
    """
    from .sales import sign_up

    ref = str(session.get("client_reference_id") or "")
    email = str((session.get("customer_details") or {}).get("email")
                or session.get("customer_email") or "").lower()
    prospects = store.get_prospects(limit=10_000)
    prospect = next((p for p in prospects if ref and p.id == ref), None) or \
        next((p for p in prospects if email and (p.business.email or "").lower() == email),
             None)
    if prospect is None:
        return ""
    if prospect.stage == "won":
        return ""
    done = sign_up(store, settings, prospect, _plan_from_session(settings, session),
                   send_link=False)
    if done.get("error"):
        return ""
    mark_paid(store, done["client"], session.get("subscription") or session.get("id", ""))
    return prospect.business.name


def reconcile(store, settings, get: Callable[..., dict] | None = None) -> list[str]:
    """Match Stripe's payments to clients. Returns what changed, in words.

    Does nothing without a key. Never raises: an unreachable Stripe is a
    reason to check again later, not a reason for the Bookkeeper to fail.
    """
    key = settings.api_key("stripe")
    if not key:
        return []
    get = get or _stripe_get
    lines: list[str] = []
    try:
        sessions = [s for s in completed_sessions(key, get=get)
                    if s.get("payment_status") in {"paid", "no_payment_required"}]
        paid = {}
        for s in sessions:
            if s.get("client_reference_id"):
                paid.setdefault(s["client_reference_id"], s)
        used: set[str] = set()
        for client in store.get_clients("awaiting_payment"):
            prospect = store.prospect_for_business(client.business)
            session = paid.get(client.id) or (paid.get(prospect.id) if prospect else None)
            if session:
                used.add(session.get("id", ""))
                mark_paid(store, client, session.get("subscription") or session.get("id", ""))
                lines.append(f"{client.business.name} paid")
        known = {c.payment_ref for s in ("active", "past_due", "churned")
                 for c in store.get_clients(s) if c.payment_ref}
        for s in sessions:
            if s.get("id", "") in used or (s.get("subscription") or s.get("id")) in known:
                continue
            name = _self_serve(store, settings, s)
            if name:
                lines.append(f"{name} bought straight from their report")

        for client in store.get_clients("active") + store.get_clients("past_due"):
            if not (client.payment_ref or "").startswith("sub_"):
                continue
            sub = get(key, f"subscriptions/{client.payment_ref}")
            status = SUBSCRIPTION_STATUS.get(sub.get("status", ""), "")
            if status and status != client.status:
                client.status = status
                if status == "churned":
                    client.churned_at = now_iso()
                store.upsert_client(client)
                store.record_outcome(prospect_id=client.id,
                                     vertical=client.business.vertical,
                                     kind=f"payment_{status}", note=sub.get("status", ""))
                lines.append(f"{client.business.name}: payment {sub.get('status')}")
    except PermissionError as exc:
        lines.append(f"Stripe: {exc}")
    except Exception as exc:  # noqa: BLE001 - checked again next run
        log.warning("Stripe check failed: %s", exc)
        lines.append(f"Stripe could not be reached ({type(exc).__name__}); will retry")
    return lines


# ---------------------------------------------------------------------------
# Chasing
# ---------------------------------------------------------------------------

def days_waiting(client: Client) -> int:
    try:
        started = datetime.fromisoformat(client.started_at)
    except ValueError:
        return 0
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - started).days)


def chase(store, settings) -> list[str]:
    """One reminder, then a flag. Never a second reminder.

    A client who said yes and has not paid has usually just not got round to
    it; one note with the link again is a courtesy. Repeating it is pressure,
    and at that point it is a conversation for the operator, not the system.
    """
    lines = []
    for client in store.get_clients("awaiting_payment"):
        waited = days_waiting(client)
        prospect = store.prospect_for_business(client.business)
        if prospect is None:
            continue
        if waited >= settings.payment_reminder_days and base_link(settings, client.plan) \
                and not store.has_outcome(client.id, "payment_reminder"):
            subject, body = payment_email(prospect, client, settings, reminder=True)
            from . import automation
            store.save_message(OutreachMessage(
                prospect_id=prospect.id, subject=subject, body=body, kind="invoice",
                sequence_step=0,
                status="approved" if automation.auto_approve(store, "invoice") else "drafted",
                scheduled_for=now_iso()))
            store.record_outcome(prospect_id=client.id, vertical=client.business.vertical,
                                 kind="payment_reminder", note=f"day {waited}")
            lines.append(f"reminder drafted for {client.business.name}")
        if waited >= settings.payment_overdue_days \
                and not store.has_outcome(client.id, "payment_overdue"):
            store.record_outcome(prospect_id=client.id, vertical=client.business.vertical,
                                 kind="payment_overdue", note=f"{waited} days unpaid")
            lines.append(f"{client.business.name} has not paid in {waited} days — call them")
    return lines


def waiting_summary(store, settings) -> list[dict[str, Any]]:
    """Signed but not paid, longest wait first — for the console."""
    rows = []
    for client in store.get_clients("awaiting_payment"):
        prospect = store.prospect_for_business(client.business)
        rows.append({
            "id": client.id, "name": client.business.name, "plan": client.plan,
            "mrr": client.mrr, "days": days_waiting(client),
            "overdue": days_waiting(client) >= settings.payment_overdue_days,
            "link": link_for(settings, client.plan, reference_for(prospect, client),
                             prospect.business.email if prospect else ""),
        })
    return sorted(rows, key=lambda r: -r["days"])
