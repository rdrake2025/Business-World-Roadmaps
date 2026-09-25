"""Before and after, for the first clients — and the case study it earns.

Nothing in the simulation, and nothing in the code, can show that the work
actually moves a business up in AI answers. Only real businesses can. So the
first two or three are pilots: free, or nearly, in exchange for being
measured and written up. This is the measuring and the writing.

It is deliberately strict about what counts:

* **Like for like.** The baseline is the first *full* audit — never the free
  four-question teaser, which asks different questions and scores
  differently.
* **Enough time.** Structured data is picked up when engines next crawl, and
  reviews compound over months. Under 45 days between audits, the honest
  answer is "too early to say", and that is what it says.
* **Beyond the noise.** AI answers differ almost every run (SparkToro and
  Gumshoe, 2026), so a change only counts when it is bigger than the margin
  of error of the two measurements together.
* **No spin.** If the numbers did not move, the write-up says so and says
  not to publish it. A case study that overstates a result is found out by
  the first prospect who checks — and prospects in this business check.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import knowledge, method

MIN_DAYS = 45
MEANINGFUL_POINTS = 5.0


@dataclass
class Evidence:
    name: str
    trade: str
    market: str
    days: int = 0
    audits: int = 0
    score_before: float | None = None
    score_after: float | None = None
    named_before: int = 0
    named_after: int = 0
    questions: int = 0
    newly_answered: list[str] = field(default_factory=list)
    lost: list[str] = field(default_factory=list)
    top_rival_before: tuple[str, int] | None = None
    top_rival_after: tuple[str, int] | None = None
    fixes_live: bool = False
    platform: str = "unknown"
    #: Share of all answers naming the business, and its ± margin, each side.
    share_before: float = 0.0
    share_after: float = 0.0
    noise: float = 0.0

    @property
    def delta(self) -> float:
        if self.score_before is None or self.score_after is None:
            return 0.0
        return round(self.score_after - self.score_before, 1)

    @property
    def verdict(self) -> str:
        """too_early | moved | flat | worse"""
        if self.audits < 2 or self.days < MIN_DAYS:
            return "too_early"
        bar = max(MEANINGFUL_POINTS, self.noise)
        shift = self.share_after - self.share_before
        if shift > self.noise or self.delta >= bar:
            return "moved"
        if -shift > self.noise or self.delta <= -bar:
            return "worse"
        return "flat"


def _days_between(a: str, b: str) -> int:
    try:
        first, last = datetime.fromisoformat(a), datetime.fromisoformat(b)
    except ValueError:
        return 0
    first = first if first.tzinfo else first.replace(tzinfo=timezone.utc)
    last = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
    return abs((last - first).days)


def evidence(store, client) -> Evidence:
    biz = client.business
    ev = Evidence(name=biz.name, trade=knowledge.get(biz.vertical).label,
                  market=biz.market)
    history = list(reversed(store.audit_history(biz.id, limit=24, comparable=True)))
    ev.audits = len(history)
    checks = store.site_checks(biz.id, limit=1)
    if checks:
        ev.fixes_live = bool(checks[0].get("local_business")) and not checks[0].get("placeholders")
        ev.platform = checks[0].get("platform", "unknown")
    if not history:
        return ev
    first, last = history[0], history[-1]
    ev.days = _days_between(first.created_at, last.created_at)
    ev.score_before, ev.score_after = first.score, last.score

    def named(audit) -> dict[str, bool]:
        out: dict[str, bool] = {}
        for r in audit.results:
            if not r.error:
                out[r.prompt] = out.get(r.prompt, False) or r.mentioned
        return out

    from .scoring import presence_margin

    def share(audit) -> tuple[float, float]:
        ok = [r for r in audit.results if not r.error]
        hits = sum(1 for r in ok if r.mentioned)
        return (100 * hits / len(ok) if ok else 0.0), presence_margin(hits, len(ok))

    (ev.share_before, m1), (ev.share_after, m2) = share(first), share(last)
    ev.noise = round((m1 * m1 + m2 * m2) ** 0.5, 1)

    before, after = named(first), named(last)
    ev.questions = len(after)
    ev.named_before = sum(before.values())
    ev.named_after = sum(after.values())
    ev.newly_answered = [q for q, hit in after.items() if hit and not before.get(q)]
    ev.lost = [q for q, hit in before.items() if hit and not after.get(q, True)]
    ev.top_rival_before, ev.top_rival_after = first.top_competitor, last.top_competitor
    return ev


def write_up(store, client) -> tuple[Evidence, str]:
    """The case study as Markdown, and the evidence it rests on."""
    ev = evidence(store, client)
    months = max(1, round(ev.days / 30))
    done = []
    for month in range(1, months + 1):
        for lever in method.plan(month, client.business.vertical)["levers"]:
            if lever.name not in done:
                done.append(lever.name)

    lines = [f"# {ev.name}: AI search visibility, {ev.trade}, {ev.market}", ""]
    if ev.verdict == "too_early":
        lines += [
            f"**Too early to write up.** {ev.audits} comparable audit(s) over {ev.days} "
            f"days; this needs at least two, {MIN_DAYS} days apart. Structured data is "
            f"picked up when the engines next crawl, and that takes weeks.", ""]
        return ev, "\n".join(lines)

    lines += [
        "## The numbers",
        "",
        "| | Before | After |",
        "| --- | --- | --- |",
        f"| Visibility score | {ev.score_before:.0f}/100 | {ev.score_after:.0f}/100 |",
        f"| Named in AI answers | {ev.named_before} of {ev.questions} | "
        f"{ev.named_after} of {ev.questions} |",
        f"| Share of all answers naming them | {ev.share_before:.0f}% | "
        f"{ev.share_after:.0f}% |",
    ]
    if ev.top_rival_before:
        rb = ev.top_rival_before
        ra = ev.top_rival_after or ("—", 0)
        lines.append(f"| Most-named competitor | {rb[0]} ({rb[1]}) | {ra[0]} ({ra[1]}) |")
    lines += ["", f"Measured {ev.days} days apart with the same {ev.questions} questions "
                  f"on the same engines. AI answers vary from run to run; a change "
                  f"has to beat ±{ev.noise:.0f} points to count.", ""]

    if ev.newly_answered:
        lines += ["## Questions they now show up for", ""]
        lines += [f"- {q}" for q in ev.newly_answered[:8]] + [""]
    if ev.lost:
        lines += ["## Questions they dropped out of", ""]
        lines += [f"- {q}" for q in ev.lost[:5]] + [""]

    lines += ["## What was done", ""] + [f"- {d}" for d in done] + [""]
    lines.append("The business-details markup is verified live on their homepage."
                 if ev.fixes_live else
                 "Note: the business-details markup was not found live on their "
                 "homepage at the last check, so this result came without it.")
    lines += ["", "## In their words", "",
              "> Ask them: what did they notice — calls, a customer who said they "
              "found them through ChatGPT? Use their words, with permission, or "
              "leave this out.", ""]

    if ev.verdict == "moved":
        lines += ["## Verdict", "", f"Moved: {ev.delta:+.0f} points and "
                  f"{ev.named_after - ev.named_before:+d} answers. Worth publishing, "
                  f"with the dates and the method above attached.", ""]
    elif ev.verdict == "flat":
        lines += ["## Verdict", "", f"**Do not publish this.** The score moved "
                  f"{ev.delta:+.0f} points and the share of answers "
                  f"{ev.share_after - ev.share_before:+.0f}, inside the ±{ev.noise:.0f} "
                  f"that AI answers vary by on their own. Keep going, or find out why "
                  f"not (are the fixes live?).", ""]
    else:
        lines += ["## Verdict", "", f"**Do not publish this.** Visibility went down "
                  f"{abs(ev.delta):.0f} points. Work out why before selling this service "
                  f"on it — a competitor's push, a site change, or the work not landing.", ""]
    lines += ["---", "AI answers vary from run to run and no one can guarantee a "
              "placement in them. These are measurements, not promises."]
    return ev, "\n".join(lines)
