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

from ..audit import MeasurementFailed, clear_outage, note_outage, run_audit
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
        from ..audit import NO_ENGINE
        from .scout import SIMULATED_MARKER

        # Real mode with no engine key would measure every prospect and client
        # with the made-up engine: invented scores in cold emails, in reports
        # and in a pilot's baseline. Nothing measured beats something invented.
        if not self.settings.can_measure():
            return 0, NO_ENGINE
        engine_count = len(self.settings.available_engines())
        processed = 0
        spend = 0.0
        blocked_sites = 0

        # --- 1. Teaser audits on freshly discovered prospects ---
        # Capped per day as well as per run. Each teaser is a live web search
        # on ChatGPT and Google now, about five cents, and twenty an hour
        # around the clock would be $25 a day for businesses nobody has time
        # to contact.
        midnight = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")
        room = max(0, int(getattr(self.settings, "teaser_audits_per_day", 30))
                   - self.store.teasers_since(midnight))
        # A measurement that mostly failed (no credit left, a bad key, no
        # internet) is not kept, and the run stops there: the next business
        # would fail the same way. The Today list says why until one works.
        stopped = ""
        for prospect in self.store.due_prospects("discovered", min(self.teaser_budget, room)):
            try:
                audit = run_audit(prospect.business, self.settings, depth="teaser",
                                  check_crawlers=True)
            except MeasurementFailed as exc:
                stopped = str(exc)
                break
            self.store.save_audit(audit)

            prospect.score = audit.score
            prospect.competitor_gap = competitor_gap(audit)
            prospect.last_audit_id = audit.id
            prospect.stage = "audited"
            # Outreach reads the first segment of notes as its evidence line.
            # A site that turns the engines away leads, because it is a
            # stronger and more checkable claim than a low score.
            blocked = (audit.crawler_access or {}).get("critical")
            fixture = SIMULATED_MARKER in (prospect.notes or "")
            prospect.notes = (f"{audit.crawler_access['headline']} | {audit.headline()}"
                              if blocked else audit.headline())
            # The marker is the only thing that keeps a made-up business out
            # of Outreach. Replacing the notes used to drop it, and every
            # invented business got a cold email drafted to its invented
            # address straight after its first audit.
            if fixture:
                prospect.notes += f" | {SIMULATED_MARKER}"
            self.store.upsert_prospect(prospect)

            if (audit.crawler_access or {}).get("critical"):
                blocked_sites += 1
            spend += audit.cost
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
        for client in [] if stopped else self.store.get_clients("active"):
            if client.plan == "pilot":
                # Three measurements, each timed for something (sales.py).
                from ..sales import pilot_due
                if not pilot_due(client, self.store.audit_history(
                        client.business.id, limit=24, comparable=True)):
                    continue
            elif [a for a in self.store.audit_history(client.business.id, limit=5)
                  if not a.is_free_teaser and a.created_at > cutoff]:
                continue
            try:
                audit = run_audit(client.business, self.settings, depth="full",
                                  check_crawlers=True)
            except MeasurementFailed as exc:
                stopped = str(exc)
                break
            self.store.save_audit(audit)
            spend += audit.cost
            clients_audited += 1
            processed += 1

        if spend > 0:
            self.store.add_ledger(LedgerEntry(
                kind="cost", category="api", amount=round(spend, 4),
                description=f"{processed} audits ({engine_count} engines)",
            ))

        if stopped:
            note_outage(self.store, stopped)
        elif processed:
            clear_outage(self.store)

        summary = (f"{processed - clients_audited} teaser audits, "
                   f"{clients_audited} client audits, ${spend:.2f} API spend")
        if stopped:
            summary += f" | stopped: {stopped}"
        if blocked_sites:
            summary += (f" | {blocked_sites} site(s) block the answer engines in "
                        f"their own robots.txt \u2014 the strongest opener you have")
        return processed, summary
