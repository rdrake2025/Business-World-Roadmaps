"""Reporter — renders the monthly client deliverable.

The report is the retention mechanism. A client renews when they can see the
number moving and know what to do next, so every report carries three things:
the score with its trend, the competitor gap that made them buy, and a
prioritised action list tied to the specific questions they lost.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..models import Audit, Deliverable, now_iso
from ..prompts import vertical_meta
from .. import method
from .fixer import FixerAgent
from ..scoring import ENGINE_LABELS, WEIGHTS, competitor_gap, grade, share_of_voice
from .base import Agent

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "report" / "templates"

# Acronyms that must not be title-cased into "Hvac".
ACRONYMS = {"hvac": "HVAC"}


def title_label(text: str) -> str:
    return " ".join(ACRONYMS.get(w.lower(), w.title()) for w in text.split())


GRADE_META = {
    "A": ("#0ca30c", "Strong presence"),
    "B": ("#0ca30c", "Competitive"),
    "C": ("#fab219", "Losing ground"),
    "D": ("#ec835a", "Largely invisible"),
    "F": ("#d03b3b", "Invisible to AI search"),
}

COMPONENT_NOTES = {
    "presence": "How often you are named at all, weighted by each engine's buyer traffic.",
    "prominence": "Where you land in the list. The first two or three names capture almost all clicks.",
    "citation": "Whether your own website is used as a source. The most durable signal.",
    "sentiment": "The quality of the context you appear in when you are named.",
}


def _actions(audit: Audit) -> list[dict[str, str]]:
    """Prioritised, specific next steps derived from this audit's weak spots."""
    subs = audit.subscores
    biz_label = str(vertical_meta(audit.vertical)["label"])
    actions: list[dict[str, str]] = []

    if subs.get("citation", 0) < 40:
        actions.append({
            "title": "Install the structured data we generated",
            "detail": (
                "Paste the LocalBusiness and FAQPage JSON-LD into your site's "
                "<head>. This is what makes your pages machine-readable, and it is "
                "the fastest single move on the citation score."
            ),
        })
    if subs.get("presence", 0) < 50:
        missed = [r.prompt for r in audit.results if not r.mentioned and not r.error][:2]
        detail = (
            "Publish the answer-shaped FAQ copy included with this report. Each "
            "answer is written against a question you are currently losing"
        )
        if missed:
            detail += f", such as: “{missed[0]}”"
        actions.append({"title": "Publish answer-shaped pages", "detail": detail + "."})

    top = audit.top_competitor
    if top:
        actions.append({
            "title": f"Close the gap on {top[0]}",
            "detail": (
                f"{top[0]} is named in {top[1]} of {len(audit.results)} answers. Work the "
                "Google Business Profile checklist: category depth, service "
                "descriptions and review velocity are what separate the named from "
                "the unnamed in local AI answers."
            ),
        })

    actions.append({
        "title": "Build directory corroboration",
        "detail": (
            "Work the citation list included with this report. AI engines "
            f"cross-check a {biz_label} across independent sources before naming it; "
            "identical name, address and phone everywhere is the requirement."
        ),
    })

    if any(r.sentiment == "negative" for r in audit.results):
        actions.insert(0, {
            "title": "Address negative context — do this first",
            "detail": (
                "At least one AI answer framed your business negatively. This "
                "outweighs visibility gains: being named badly is worse than not "
                "being named. Respond to recent negative reviews and request fresh "
                "ones from satisfied customers."
            ),
        })
    return actions


def render_report(audit: Audit, settings, history: list[Audit] | None = None,
                  deliverables: list[Deliverable] | None = None,
                  month: int = 1) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    tpl = env.get_template("report.html")

    total = len(audit.results) or 1
    mentions = sum(1 for r in audit.results if r.mentioned)
    g = grade(audit.score)
    grade_color, grade_label = GRADE_META[g]

    # Trend against the previous audit for this business, if there is one.
    trend = None
    trend_color = "#898781"
    prior = [h for h in (history or []) if h.id != audit.id]
    if prior:
        trend = round(audit.score - prior[0].score, 1)
        trend_color = "#0ca30c" if trend > 0 else ("#d03b3b" if trend < 0 else "#898781")

    sov = sorted(share_of_voice(audit).items(), key=lambda kv: -kv[1])[:6]
    sov_max = max((v for _, v in sov), default=1) or 1

    engines = sorted(
        ((ENGINE_LABELS.get(k, k), v) for k, v in audit.engine_breakdown.items()),
        key=lambda kv: -kv[1],
    )

    order = ["presence", "prominence", "citation", "sentiment"]
    components = [(k.title(), audit.subscores.get(k, 0.0), COMPONENT_NOTES[k]) for k in order]
    weights = [int(WEIGHTS[k] * 100) for k in order]

    top = audit.top_competitor

    return tpl.render(
        a=audit,
        brand=settings.brand,
        website=settings.website,
        vertical_label=title_label(str(vertical_meta(audit.vertical)["label"])),
        grade=g, grade_color=grade_color, grade_label=grade_label,
        trend=trend, trend_color=trend_color,
        mentions=mentions, total=total,
        gap=max(0, (top[1] if top else 0) - mentions),
        top_comp_name=top[0] if top else "None detected",
        top_comp_count=top[1] if top else 0,
        sov=sov, sov_max=sov_max,
        engines=engines, engine_count=len(audit.engine_breakdown) or 1,
        components=components, weights=weights,
        actions=_actions(audit),
        plan=method.plan(month, audit.vertical, audit),
        month=month,
        deliverables=[d.title.split(" — ")[0] for d in (deliverables or [])],
        results=sorted(audit.results, key=lambda r: (not r.mentioned, r.engine)),
    )


class ReporterAgent(Agent):
    name = "reporter"
    description = "Renders and files monthly client visibility reports."
    interval = 12 * 3600

    def execute(self) -> tuple[int, str]:
        out_dir = Path(self.settings.output_dir) / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        made = 0

        for client in self.store.get_clients("active"):
            history = self.store.audit_history(client.business.id, limit=6)
            if not history:
                continue
            audit = history[0]
            if client.last_report_at and client.last_report_at >= audit.created_at:
                continue  # already reported on this audit

            deliverables = self.store.get_deliverables(audit.id)
            month = FixerAgent.engagement_month(client)
            html = render_report(audit, self.settings, history, deliverables,
                                 month)

            stamp = datetime.now(timezone.utc).strftime("%Y-%m")
            slug = (client.business.domain or client.business.id).replace(".", "_")
            path = out_dir / f"{slug}_{stamp}.html"
            path.write_text(html, encoding="utf-8")

            self.store.save_deliverable(Deliverable(
                audit_id=audit.id, business_id=client.business.id, kind="report_html",
                title=f"AI Visibility Report — {client.business.name}",
                body=str(path), filename=path.name,
            ))
            client.last_report_at = now_iso()
            self.store.upsert_client(client)
            made += 1

        return made, f"rendered {made} client reports"
