"""Prospector — finds the address a discovered business publishes.

This sat between a working pipeline and a pipeline that could earn. The Scout
reads local search results, which give a name, a website and a phone number
and never an email. The Outreach agent requires one. So every real prospect
was silently filtered out as uncontactable, while the simulated fixtures —
which fabricate addresses — sailed through. The fleet looked healthy in every
dashboard and could not send a single message to a real business.

It runs immediately after the Scout, before the Auditor, so a business whose
contact cannot be found never consumes an audit. The same reasoning the
Strategist applied to verticals: rejecting at the point of discovery is
cheaper than rejecting at the point of sale.

Politeness is not decoration here. This reads a handful of pages a business
publishes precisely so people can contact them, at a few seconds apart, with
an honest user agent, and stops when robots.txt says to. The businesses being
read are the ones we then hope will reply.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from .. import contacts
from ..models import now_iso
from .base import Agent

#: Re-check a business with no published address after this long. Sites get
#: rebuilt and contact pages get added; crawling weekly would find nothing
#: and waste their bandwidth.
RECHECK_DAYS = 45


def _stale(stamp: str, days: int = RECHECK_DAYS) -> bool:
    if not stamp:
        return True
    try:
        when = datetime.fromisoformat(stamp)
    except ValueError:
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - when > timedelta(days=days)


class ProspectorAgent(Agent):
    name = "prospector"
    description = "Finds the published contact address for discovered businesses."
    interval = 2 * 3600

    def __init__(self, store, settings, budget: int = 25, pause_seconds: float = 2.0):
        super().__init__(store, settings)
        self.budget = budget
        #: Seconds between sites. Not a rate limit we are forced into — a
        #: courtesy to small businesses running on shared hosting.
        self.pause_seconds = pause_seconds

    def due(self) -> list:
        """Discovered businesses with a website, no email, and no recent check."""
        out = []
        for prospect in self.store.get_prospects("discovered", 500):
            biz = prospect.business
            if biz.email and "@" in biz.email:
                continue
            if not biz.website:
                continue
            if not _stale(prospect.contact_checked_at):
                continue
            out.append(prospect)
        return out[: self.budget]

    def execute(self) -> tuple[int, str]:
        queue = self.due()
        if not queue:
            return 0, "every discovered business already has a contact or was checked recently"

        try:
            import requests
            session = requests.Session()
        except ImportError:
            return 0, "requests is not installed — cannot read contact pages"

        found = blocked = missing = 0
        try:
            for i, prospect in enumerate(queue):
                if i:
                    time.sleep(self.pause_seconds)
                biz = prospect.business
                result = contacts.find_contact(biz.website, session=session)
                prospect.contact_checked_at = now_iso()

                if result.found:
                    biz.email = result.email
                    prospect.notes = (prospect.notes or "") + \
                        f" | contact: {result.email} ({result.confidence})"
                    found += 1
                elif "robots" in result.note:
                    prospect.notes = (prospect.notes or "") + " | contact: site asks not to be read"
                    blocked += 1
                else:
                    prospect.notes = (prospect.notes or "") + f" | contact: {result.note}"
                    missing += 1
                self.store.upsert_prospect(prospect)
        finally:
            session.close()

        parts = [f"found {found} of {len(queue)}"]
        if missing:
            parts.append(f"{missing} publish none")
        if blocked:
            parts.append(f"{blocked} declined by robots.txt")
        summary = ", ".join(parts)
        if missing or blocked:
            summary += " — those have a phone number; call them or add the address by hand"
        return found, summary
