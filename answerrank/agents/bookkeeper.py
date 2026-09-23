"""Bookkeeper — bills clients, books costs, and measures the $5k target.

Everything the operator needs to answer "am I winning?" comes from here.
Bills are idempotent per calendar month, so the agent can run every hour for
a year without double-charging anyone.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..models import LedgerEntry
from .base import Agent

# Fixed monthly stack. Deliberately small — this is the whole point of an
# agent-run business. Update these to match real invoices.
FIXED_COSTS = {
    "tooling": 89.0,     # email sending, hosting, domain, scheduling
    "software": 49.0,    # accounting, e-sign, payment processing base fees
}

# Payment processor take: Stripe's 2.9% + $0.30 per card charge, plus the
# 0.7% Stripe Billing adds to every subscription — and a recurring payment
# link is a subscription.
PROCESSOR_PCT = 0.036
PROCESSOR_FLAT = 0.30


def bill_month(store, client, month: str = "") -> bool:
    """Book one client's fee for one month, once. True if it was new.

    Every recurring charge carries a key naming exactly what it is and which
    month it belongs to, and the database refuses a second one. The
    check-then-insert this replaced was two separate connections: a console
    action landing while the tick ran could bill the same client twice,
    which shows up as revenue that was never collected.

    Only a client who has paid is billed — a client awaiting payment is a
    promise, and counting promises is how a P&L starts lying.
    """
    if client.mrr <= 0 or client.status != "active":
        return False
    month = month or datetime.now(timezone.utc).strftime("%Y-%m")
    wrote = store.add_ledger_once(
        LedgerEntry(
            kind="revenue", category="subscription", amount=client.mrr,
            description=f"{client.plan} plan — {client.business.name} ({month})",
            client_id=client.id,
        ),
        dedupe_key=f"subscription:{client.id}:{month}",
    )
    if wrote:
        fee = round(client.mrr * PROCESSOR_PCT + PROCESSOR_FLAT, 2)
        store.add_ledger_once(
            LedgerEntry(
                kind="cost", category="processing", amount=fee,
                description=f"payment processing — {client.business.name}",
                client_id=client.id,
            ),
            dedupe_key=f"processing:{client.id}:{month}",
        )
    return wrote


class BookkeeperAgent(Agent):
    name = "bookkeeper"
    description = ("Confirms payments, chases unpaid clients, bills paying ones, "
                   "and reports progress to target.")
    # Every two hours rather than daily: it now confirms payments, and a
    # client who paid this morning should be welcomed this morning. Billing
    # is idempotent per month, so running more often cannot double-charge.
    interval = 2 * 3600

    def execute(self) -> tuple[int, str]:
        from .. import payments

        month = datetime.now(timezone.utc).strftime("%Y-%m")
        billed = 0
        billed_amount = 0.0

        collections = payments.reconcile(self.store, self.settings)
        collections += payments.chase(self.store, self.settings)

        for client in self.store.get_clients("active"):
            if bill_month(self.store, client, month):
                billed += 1
                billed_amount += client.mrr

        for category, amount in FIXED_COSTS.items():
            self.store.add_ledger_once(
                LedgerEntry(
                    kind="cost", category=category, amount=amount,
                    description=f"fixed monthly {category} ({month})",
                ),
                dedupe_key=f"fixed:{category}:{month}",
            )

        kpis = self.kpis()
        waiting = self.store.get_clients("awaiting_payment")
        summary = (
            f"billed {billed} clients (${billed_amount:,.0f}); MRR ${kpis['mrr']:,.0f}; "
            f"30d profit ${kpis['profit']:,.0f}; "
            f"{kpis['pct_to_target']:.0f}% of ${kpis['target']:,.0f} target"
        )
        if waiting:
            summary += f" | {len(waiting)} signed, not yet paid"
        if collections:
            summary += " | " + "; ".join(collections[:4])
        return billed, summary

    def kpis(self) -> dict[str, float]:
        pnl = self.store.pnl(30)
        mrr = self.store.mrr()
        clients = self.store.get_clients("active")
        target = self.settings.profit_target_monthly
        pricing = self.settings.pricing

        # Unit contribution at the mid-tier, used for the "how many more?" answer.
        unit_price = pricing.growth_monthly
        unit_cost = pricing.delivery_cost_monthly + unit_price * PROCESSOR_PCT + PROCESSOR_FLAT
        unit_margin = unit_price - unit_cost

        fixed = sum(FIXED_COSTS.values())
        clients_needed = max(0, -(-int((target + fixed) // max(unit_margin, 1)) // 1))
        gap = max(0.0, target - pnl["profit"])

        return {
            "mrr": round(mrr, 2),
            "arr": round(mrr * 12, 2),
            "active_clients": float(len(clients)),
            "revenue_30d": pnl["revenue"],
            "cost_30d": pnl["cost"],
            "profit": pnl["profit"],
            "margin": pnl["margin"],
            "target": target,
            "pct_to_target": round(100 * pnl["profit"] / target, 1) if target else 0.0,
            "profit_gap": round(gap, 2),
            "unit_margin": round(unit_margin, 2),
            "clients_needed_at_growth": float(clients_needed),
            "more_clients_needed": float(max(0, -(-int(gap) // max(int(unit_margin), 1)))),
            "arpu": round(mrr / len(clients), 2) if clients else 0.0,
        }
