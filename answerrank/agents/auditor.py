"""Auditor — runs visibility audits.

Handles both halves of the business:

* **Teaser audits** on ``discovered`` prospects, producing the proof that
  makes the cold email land.
* **Full audits** for paying clients on their monthly cycle.

Cold-prospect auditing is rate-limited per run so a runaway loop can never
burn a month of API budget in an afternoon.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..audit import estimate_cost, run_audit
from ..models import LedgerEntry
from ..scoring import competitor_gap
from .base import Agent


class AuditorAgent(Agent):
    name = "auditor"
    description = "Runs teaser audits on prospects and full audits for clients."
    interval = 3600

    def __init__(self, store, settings, teaser_budget: int = 20):
        super().__init__(store, settings)
        self.teaser_budget = teaser_budget

    def execute(self) -> tuple[int, str]:
        engine_count = len(self.settings.available_engines())
        processed = 0
        spend = 0.0
        blocked_sites = 0

        # --- 1. Teaser audits on freshly discovered prospects ---
        for prospect in self.store.due_prospects("discovered", self.teaser_budget):
            audit = run_audit(prospect.business, self.settings, depth="teaser",
                              check_crawlers=True)
            self.store.save_audit(audit)

            prospect.score = audit.score
            prospect.competitor_gap = competitor_gap(audit)
            prospect.last_audit_id = audit.id
            prospect.stage = "audited"
            # Outreach reads the first segment of notes as its evidence line.
            # A site that turns the engines away leads, because it is a
            # stronger and more checkable claim than a low score.
            blocked = (audit.crawler_access or {}).get("critical")
            prospect.notes = (f"{audit.crawler_access['headline']} | {audit.headline()}"
                              if blocked else audit.headline())
            self.store.upsert_prospect(prospect)

            if (audit.crawler_access or {}).get("critical"):
                blocked_sites += 1
            spend += estimate_cost("teaser", engine_count)
            processed += 1

        # --- 2. Full audits for clients due one ---
        # Keyed on the last *full audit*, not the last report. Keyed on the
        # report, a new client — who has no report until the Reporter's next
        # twelve-hourly run — was re-audited every hour until then, and every
        # client was re-audited hourly each month in the same window. That is
        # wasted spend, and worse, it filled the audit history Retention reads
        # its trend from with same-day duplicates, so "is it working?" was
        # answered by comparing this morning with this afternoon.
        clients_audited = 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=28)).isoformat(timespec="seconds")
        for client in self.store.get_clients("active"):
            recent = [a for a in self.store.audit_history(client.business.id, limit=5)
                      if not a.is_free_teaser and a.created_at > cutoff]
            if recent:
                continue
            audit = run_audit(client.business, self.settings, depth="full",
                              check_crawlers=True)
            self.store.save_audit(audit)
            spend += estimate_cost("full", engine_count)
            clients_audited += 1
            processed += 1

        if spend > 0:
            self.store.add_ledger(LedgerEntry(
                kind="cost", category="api", amount=round(spend, 4),
                description=f"{processed} audits ({engine_count} engines)",
            ))

        summary = (f"{processed - clients_audited} teaser audits, "
                   f"{clients_audited} client audits, ${spend:.2f} API spend")
        if blocked_sites:
            summary += (f" | {blocked_sites} site(s) block the answer engines in "
                        f"their own robots.txt \u2014 the strongest opener you have")
        return processed, summary
