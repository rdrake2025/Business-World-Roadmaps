"""Configuration loading for the AnswerRank platform.

Settings resolve in this order (highest priority first):

1. Environment variables (``ANSWERRANK_*`` and provider API keys).
2. ``answerrank.yml`` in the working directory (or ``$ANSWERRANK_CONFIG``).
3. The defaults defined here.

The platform is designed to boot and run a full pipeline with *no*
configuration at all: with no provider keys present it falls back to the
deterministic mock engine so the system is demonstrable offline.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - yaml ships with the base image
    yaml = None

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT / "answerrank.yml"

# Providers we know how to talk to, mapped to the env var holding their key.
PROVIDER_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "perplexity": "PERPLEXITY_API_KEY",
    "serper": "SERPER_API_KEY",  # powers Google AI Overview capture
    "stripe": "STRIPE_API_KEY",  # read-only: who has paid
}


@dataclass
class Pricing:
    """The productized pricing ladder. Every number here feeds the P&L."""

    audit_one_time: float = 297.0
    starter_monthly: float = 499.0
    growth_monthly: float = 997.0
    managed_monthly: float = 1997.0
    # Blended delivery cost per client per month (API calls + tooling share).
    delivery_cost_monthly: float = 18.0

    def plan_price(self, plan: str) -> float:
        return {
            "audit": self.audit_one_time,
            "starter": self.starter_monthly,
            "growth": self.growth_monthly,
            "managed": self.managed_monthly,
        }.get(plan.lower(), 0.0)

    #: Plans a client can be signed onto. ``pilot`` is free on purpose: the
    #: first few clients are how the service proves it works at all.
    PLANS = ("starter", "growth", "managed", "pilot")

    def plan_for(self, price: float) -> str:
        """The monthly plan charging this price, or "" if none does."""
        for plan in ("starter", "growth", "managed"):
            if abs(self.plan_price(plan) - float(price or 0)) < 0.5:
                return plan
        return ""

    def ladder(self) -> list[float]:
        """The recurring tiers, low to high. The one-off audit is not a tier."""
        return sorted({self.starter_monthly, self.growth_monthly,
                       self.managed_monthly})


@dataclass
class OutreachPolicy:
    """Guard rails so the outreach agent stays inside the 2026 sender rules.

    Google/Yahoo/Microsoft enforce spam complaints under 0.3% and bounces
    under 2%. These caps keep us far below those thresholds, which is the
    difference between ~89% inbox placement and getting domain-wide filtered.
    """

    max_emails_per_domain_per_day: int = 30
    max_emails_total_per_day: int = 120
    #: Warm-up ramp for a brand new sending domain, as (day, cap) steps. A
    #: domain with no sending history that opens at 120 a day is read as a
    #: compromised account, and the reputation damage is not recoverable —
    #: the domain is simply finished. Volume has to be earned over about a
    #: month. Each tuple is "from this day of sending, this many per day".
    warmup_steps: tuple = ((1, 10), (4, 20), (8, 40), (15, 70), (22, 100), (29, 0))
    min_seconds_between_sends: int = 90
    require_physical_address: bool = True
    require_unsubscribe: bool = True
    max_followups: int = 3
    followup_gap_days: int = 4
    # Hard stop: if measured bounce/complaint rate exceeds these, sending halts.
    bounce_rate_ceiling: float = 0.02
    complaint_rate_ceiling: float = 0.001
    suppress_after_days: int = 90

    def warmup_cap(self, days_sending: int) -> int:
        """The daily ceiling this far into the ramp. 0 days means day one.

        Returns the full cap once the ramp is complete, so an established
        domain is never throttled by a setting it has outgrown.
        """
        day = max(1, days_sending + 1)
        cap = self.max_emails_total_per_day
        for from_day, step_cap in self.warmup_steps:
            if day >= from_day:
                cap = step_cap or self.max_emails_total_per_day
        return min(cap, self.max_emails_total_per_day)

    def warmup_note(self, days_sending: int) -> str:
        day = max(1, days_sending + 1)
        cap = self.warmup_cap(days_sending)
        if cap >= self.max_emails_total_per_day:
            return f"Warm-up complete — full cap of {cap} a day."
        remaining = next((d - day for d, _ in self.warmup_steps if d > day), 0)
        return (f"Day {day} of warm-up: {cap} a day. "
                + (f"Next step up in {remaining} day(s)." if remaining else ""))


@dataclass
class Settings:
    brand: str = "AnswerRank"
    tagline: str = "Get found when customers ask AI."
    company_legal_name: str = "AnswerRank LLC"
    from_email: str = "hello@answerrank.io"
    physical_address: str = "SET_YOUR_REGISTERED_BUSINESS_ADDRESS"
    website: str = "https://answerrank.io"
    #: Which mailbox provider the sending domain uses. Decides the SPF include
    #: and the DKIM selector the readiness check looks for.
    email_provider: str = ""
    #: ISO date the domain started sending. Drives the warm-up ramp; empty
    #: means the ramp has not started and the first send sets it.
    warmup_start: str = ""
    #: Who is calling, and the number a voicemail asks them to ring back.
    #: Only the call script uses these.
    your_name: str = ""
    callback_phone: str = ""
    #: What to sell and where. Empty means every trade the price supports,
    #: across the Scout's default cities. Markets are "City, ST".
    trades: list[str] = field(default_factory=list)
    markets: list[str] = field(default_factory=list)

    # Which answer engines to probe. Unavailable ones are skipped gracefully.
    engines: list[str] = field(
        default_factory=lambda: ["openai", "anthropic", "perplexity", "google_aio"]
    )
    # Probes per audit. 10 buyer-intent prompts is enough signal to sell on
    # and cheap enough to run for free on cold prospects.
    prompts_per_audit: int = 10
    #: Each question asked this many times in a client (full) audit. AI
    #: answers change almost every run (SparkToro/Gumshoe, Jan 2026), so one
    #: run per question is noise; three gives a usable share. Teasers stay at
    #: one: they only open a conversation.
    probe_repeats: int = 3
    #: Engines a prospect's free teaser uses: ChatGPT (the assistant most
    #: people use) and Google. Perplexity and Claude are kept for client
    #: audits, where their cost is trivial next to the fee.
    teaser_engines: list[str] = field(
        default_factory=lambda: ["openai", "google_aio"])
    #: Prospects checked per day. A live-search teaser costs about five and a
    #: half cents, so this is the one dial on API spend: 20 a day (about $33 a
    #: month) keeps ten emails and a morning of calls supplied, since each
    #: business is called up to four times. Each extra 10 a day is ~$17/month.
    teaser_audits_per_day: int = 20
    request_timeout: int = 60
    max_retries: int = 3

    database_path: str = str(ROOT / "data" / "answerrank.db")
    output_dir: str = str(ROOT / "data" / "output")

    # Orchestrator cadence, in seconds.
    tick_seconds: int = 300
    demo_mode: bool = False

    pricing: Pricing = field(default_factory=Pricing)

    #: Stripe payment links, one per plan: {"growth": "https://buy.stripe.com/..."}.
    #: Make each one in Stripe > Payment Links as a *recurring monthly* price,
    #: so Stripe charges every month and nobody has to send an invoice.
    payment_links: dict[str, str] = field(default_factory=dict)
    #: A signed client who has not paid gets one friendly reminder after this
    #: many days, and is flagged to you after the second number.
    payment_reminder_days: int = 3
    payment_overdue_days: int = 10
    outreach: OutreachPolicy = field(default_factory=OutreachPolicy)

    # Business target that the Bookkeeper agent measures everything against.
    profit_target_monthly: float = 5000.0

    def quote_for(self, vertical: str) -> float:
        """What to charge this trade, rather than what to charge everyone.

        Quoting one price across every trade meant half the library was
        unsellable: a garage door company cannot defend $997 on a $450 ticket,
        so it was dropped — when it defends $297 comfortably. This is the one
        place that decision is made, so the Scout, the qualifier and the copy
        cannot disagree about what a prospect is being offered.
        """
        from . import knowledge

        recommended = knowledge.recommended_price(vertical, self.pricing.ladder())
        price = recommended.get("price")
        return float(price) if price else self.pricing.growth_monthly

    def available_engines(self) -> list[str]:
        """Engines we actually hold credentials for, else the mock engine."""
        if self.demo_mode:
            return ["mock"]
        live = []
        for name in self.engines:
            provider = "serper" if name == "google_aio" else name
            if os.environ.get(PROVIDER_ENV.get(provider, ""), "").strip():
                live.append(name)
        return live or ["mock"]

    def api_key(self, provider: str) -> str | None:
        return os.environ.get(PROVIDER_ENV.get(provider, ""), "").strip() or None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _coerce(settings: Settings, data: dict[str, Any]) -> Settings:
    """Apply a nested dict onto a Settings instance, ignoring unknown keys."""
    for key, value in (data or {}).items():
        if key == "pricing" and isinstance(value, dict):
            for pk, pv in value.items():
                if hasattr(settings.pricing, pk):
                    setattr(settings.pricing, pk, pv)
        elif key == "outreach" and isinstance(value, dict):
            for ok, ov in value.items():
                if hasattr(settings.outreach, ok):
                    setattr(settings.outreach, ok, ov)
        elif hasattr(settings, key):
            setattr(settings, key, value)
    return settings


#: Problems found while reading the config file. The doctor reports these;
#: nothing else needs to know, and nothing should crash over them.
CONFIG_PROBLEMS: list[str] = []


def load_settings(path: str | Path | None = None) -> Settings:
    settings = Settings()
    CONFIG_PROBLEMS.clear()

    # Keys first, so everything below — and every agent — sees them. A real
    # environment variable still wins over the file.
    try:
        from . import keys
        keys.apply(Path(os.environ.get("ANSWERRANK_KEYS") or keys.KEYS_FILE))
    except Exception as exc:  # noqa: BLE001 - a bad keys file must not stop startup
        CONFIG_PROBLEMS.append(f"keys.env could not be read: {exc}")

    config_path = Path(path or os.environ.get("ANSWERRANK_CONFIG") or DEFAULT_CONFIG_PATH)
    if config_path.exists() and yaml is not None:
        # UTF-8 explicitly. The wizard writes this file as UTF-8; reading it
        # back with the platform default garbles it on Windows.
        #
        # And a parse failure must not be a traceback. This module is
        # imported by every entry point and the file is one the operator is
        # told to hand-edit, so a stray tab in answerrank.yml used to take
        # down the whole application with a YAML stack trace and no hint of
        # which line was wrong. Defaults plus a plain warning keep the
        # console reachable, which is where the problem can be seen.
        try:
            raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            CONFIG_PROBLEMS.append(
                f"{config_path} could not be read ({exc.__class__.__name__}: "
                f"{str(exc).splitlines()[0]}). Running on defaults until it is fixed."
            )
            raw = {}
        if not isinstance(raw, dict):
            CONFIG_PROBLEMS.append(
                f"{config_path} does not contain a set of settings "
                f"(found {type(raw).__name__}). Running on defaults.")
            raw = {}
        settings = _coerce(settings, raw)

    # Env overrides win over the file.
    for key in ("brand", "from_email", "physical_address", "website",
                "database_path", "output_dir", "email_provider", "warmup_start"):
        env_val = os.environ.get(f"ANSWERRANK_{key.upper()}")
        if env_val:
            setattr(settings, key, env_val)
    if os.environ.get("ANSWERRANK_DEMO", "").lower() in {"1", "true", "yes"}:
        settings.demo_mode = True

    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    Path(settings.output_dir).mkdir(parents=True, exist_ok=True)
    return settings


SETTINGS = load_settings()
