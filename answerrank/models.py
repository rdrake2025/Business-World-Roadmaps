"""Domain models for the AnswerRank platform.

Plain dataclasses, deliberately free of an ORM: the whole system needs to be
readable by a non-engineer operator and portable to any host.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# --------------------------------------------------------------------------
# Pipeline vocabulary
# --------------------------------------------------------------------------

# Prospect lifecycle. The outreach agent only ever advances one step at a time.
PROSPECT_STAGES = [
    "discovered",    # Scout found it
    "audited",       # Auditor ran a free mini-audit
    "queued",        # Outreach drafted, awaiting send window
    "contacted",     # First touch sent
    "following_up",  # In the follow-up sequence
    "replied",       # Human takes over here
    "won",           # Converted to client
    "lost",          # Explicit no
    "suppressed",    # Unsubscribed / bounced / do-not-contact
]

CLIENT_STATUSES = ["trialing", "active", "past_due", "churned"]


@dataclass
class Business:
    """A local service business — either a prospect or a paying client."""

    name: str
    city: str
    state: str = ""
    vertical: str = "home_services"  # hvac, dental, legal, roofing, ...
    website: str = ""
    email: str = ""
    phone: str = ""
    id: str = field(default_factory=lambda: new_id("biz"))

    @property
    def market(self) -> str:
        return f"{self.city}, {self.state}".strip(", ")

    @property
    def domain(self) -> str:
        site = self.website.replace("https://", "").replace("http://", "")
        return site.split("/")[0].lower().removeprefix("www.")


@dataclass
class Prospect:
    business: Business
    stage: str = "discovered"
    score: float | None = None          # their visibility score, 0-100
    competitor_gap: float | None = None  # best local competitor score minus theirs
    last_audit_id: str = ""
    touches: int = 0
    last_touch_at: str = ""
    next_action_at: str = ""
    notes: str = ""
    created_at: str = field(default_factory=now_iso)
    id: str = field(default_factory=lambda: new_id("pros"))

    @property
    def is_hot(self) -> bool:
        """Hot = demonstrably invisible while a competitor is visible.

        This is the entire sales thesis in one property: we only pitch
        businesses where we can prove a gap they are losing money to.
        """
        return (
            self.score is not None
            and self.score < 40
            and (self.competitor_gap or 0) >= 25
        )


@dataclass
class Client:
    business: Business
    plan: str = "starter"
    mrr: float = 0.0
    status: str = "active"
    started_at: str = field(default_factory=now_iso)
    churned_at: str = ""
    last_report_at: str = ""
    id: str = field(default_factory=lambda: new_id("cli"))


@dataclass
class Probe:
    """One buyer-intent question asked of one answer engine."""

    prompt: str
    engine: str
    intent: str = "discovery"  # discovery | comparison | emergency | trust
    id: str = field(default_factory=lambda: new_id("prb"))


@dataclass
class ProbeResult:
    probe_id: str
    engine: str
    prompt: str
    answer_text: str
    mentioned: bool
    cited: bool                       # brand's own domain appeared as a source
    position: int | None              # 1-based rank among named businesses
    competitors: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    sentiment: str = "neutral"        # positive | neutral | negative | absent
    latency_ms: int = 0
    error: str = ""
    created_at: str = field(default_factory=now_iso)
    id: str = field(default_factory=lambda: new_id("res"))


@dataclass
class Audit:
    """A full visibility sweep for one business at one point in time."""

    business_id: str
    business_name: str
    market: str
    vertical: str
    results: list[ProbeResult] = field(default_factory=list)
    score: float = 0.0
    subscores: dict[str, float] = field(default_factory=dict)
    competitors: dict[str, int] = field(default_factory=dict)  # name -> mentions
    engine_breakdown: dict[str, float] = field(default_factory=dict)
    findings: list[str] = field(default_factory=list)
    is_free_teaser: bool = False
    created_at: str = field(default_factory=now_iso)
    id: str = field(default_factory=lambda: new_id("aud"))

    @property
    def mention_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.mentioned) / len(self.results)

    @property
    def top_competitor(self) -> tuple[str, int] | None:
        if not self.competitors:
            return None
        return max(self.competitors.items(), key=lambda kv: kv[1])

    def headline(self) -> str:
        """The one sentence that sells the deal."""
        shown = sum(1 for r in self.results if r.mentioned)
        total = len(self.results) or 1
        from .knowledge import get as _vertical
        trade = _vertical(self.vertical).label
        line = (f"{self.business_name} appears in {shown} of {total} AI answers "
                f"for {trade}s in {self.market}.")
        top = self.top_competitor
        if top and top[1] > shown:
            line += f" {top[0]} appears in {top[1]}."
        return line


@dataclass
class Deliverable:
    """A concrete artifact we hand the client — this is what they pay for."""

    audit_id: str
    business_id: str
    kind: str          # schema_jsonld | faq_content | gbp_checklist | report_html
    title: str
    body: str
    filename: str = ""
    created_at: str = field(default_factory=now_iso)
    id: str = field(default_factory=lambda: new_id("dlv"))


@dataclass
class OutreachMessage:
    prospect_id: str
    subject: str
    body: str
    sequence_step: int = 1
    status: str = "drafted"  # drafted | approved | sent | replied | bounced | suppressed
    scheduled_for: str = ""
    sent_at: str = ""
    created_at: str = field(default_factory=now_iso)
    id: str = field(default_factory=lambda: new_id("msg"))


@dataclass
class LedgerEntry:
    """Every dollar in or out. The Bookkeeper agent reads only this table."""

    kind: str          # revenue | cost
    category: str      # subscription | audit | api | tooling | ads | contractor
    amount: float
    description: str = ""
    client_id: str = ""
    occurred_at: str = field(default_factory=now_iso)
    id: str = field(default_factory=lambda: new_id("led"))


@dataclass
class AgentRun:
    """An execution record. Every agent writes one, success or failure."""

    agent: str
    status: str = "running"  # running | ok | error
    started_at: str = field(default_factory=now_iso)
    finished_at: str = ""
    items_processed: int = 0
    summary: str = ""
    error: str = ""
    id: str = field(default_factory=lambda: new_id("run"))


def to_json(obj: Any) -> str:
    return json.dumps(asdict(obj) if hasattr(obj, "__dataclass_fields__") else obj, default=str)
