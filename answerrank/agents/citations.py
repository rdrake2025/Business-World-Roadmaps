"""Citations — checks the sites the engines quote, for clients and hot prospects.

Presence on expert-curated "best of" lists is the strongest AI-visibility
factor in Whitespark's 2026 survey, and ChatGPT's most-cited local
directories are exactly those lists (BrightLocal). This agent turns that
into two things the business can use:

* for each client, once a month, where they stand on the sites the engines
  cite for their trade and town — and where the competitor that was named
  instead stands — which the Fixer hands over as that month's list;
* for the hottest prospects, whether the competitor is on a curated list
  they are not, which is the most concrete sentence a sales call can open
  with.

It costs site-restricted searches, so it is budgeted: a handful of
prospects a day, each client once a month. Without a search key it does
nothing and says so.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .. import citations, qualify
from .base import Agent


class CitationAgent(Agent):
    name = "citations"
    description = "Checks the sites AI engines quote, for clients and hot prospects."
    interval = 24 * 3600

    #: Prospects checked per run. Each costs four searches (two curated lists,
    #: the prospect and its competitor).
    PROSPECTS_PER_RUN = 5
    CLIENT_EVERY_DAYS = 30

    def __init__(self, store, settings, search=None, places=None):
        super().__init__(store, settings)
        key = settings.api_key("serper")
        self.search = search or (lambda q: citations.serper_search(q, key))
        self.places = places or (lambda q: citations.serper_places(q, key))
        self.enabled = bool(search) or bool(key)

    def _due(self, business_id: str, days: int) -> bool:
        last = self.store.citation_checks(business_id, limit=1)
        if not last:
            return True
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        return last[0].get("checked_at", "") < cutoff

    def _latest(self, business_id: str):
        history = self.store.audit_history(business_id, limit=3)
        return history, (history[0] if history else None)

    def execute(self) -> tuple[int, str]:
        if not self.enabled:
            return 0, "no search key, so the sites the engines quote were not checked"
        clients = prospects = 0

        for client in self.store.get_clients("active"):
            biz = client.business
            if not self._due(biz.id, self.CLIENT_EVERY_DAYS):
                continue
            history, latest = self._latest(biz.id)
            if latest is None:
                continue
            top = latest.top_competitor[0] if latest.top_competitor else ""
            result = citations.check(biz, top, citations.cited_domains(history, biz.website),
                                     self.search)
            result["reviews"] = citations.google_reviews(biz.name, biz.city, self.places)
            self.store.save_citation_check(biz.id, result)
            clients += 1

        candidates = []
        for stage in ("audited", "queued", "contacted", "following_up"):
            for p in self.store.get_prospects(stage, 2000):
                if p.business.phone or p.business.email:
                    candidates.append(p)
        candidates.sort(key=lambda p: -qualify.priority(
            p.business, p.score, p.competitor_gap,
            self.settings.quote_for(p.business.vertical)))
        for p in candidates:
            if prospects >= self.PROSPECTS_PER_RUN:
                break
            if not self._due(p.business.id, 60):
                continue
            history, latest = self._latest(p.business.id)
            if latest is None or not latest.top_competitor:
                continue
            result = citations.check(p.business, latest.top_competitor[0],
                                     citations.cited_domains(history, p.business.website),
                                     self.search, only=("curated",))
            self.store.save_citation_check(p.business.id, result)
            prospects += 1

        return clients + prospects, (f"checked where {clients} client(s) and "
                                     f"{prospects} prospect(s) stand on the sites "
                                     f"the engines quote")
