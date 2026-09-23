"""A stretch of real selling, run end to end with nothing real touched.

    python run.py simulate                 # 30 sales, about 100 days
    python run.py simulate --sales 10 --days 60

**What is real:** every agent, the orchestrator, the database, the send path
with its warm-up cap, suppression and bounce handling, and the console API
the operator taps on their phone.

**What is simulated:** the clock, the mailbox, the answer engines, the
robots.txt reads — and the people on the other end, whose replies are made
up. Each one has a script and a true intent, so the system's reading of
every reply can be checked against what the person actually meant.

**The operator can only do what the console lets them do.** That is who is
running this: someone on a phone who approves every draft, taps Send, pastes
in the replies that reached their inbox, and taps Won when a customer says
yes. Anything the business needs that the console cannot do is reported as
a gap, never quietly done on the operator's behalf — a simulation that helps
the software over its own holes proves nothing about the software.

Nothing here reaches the network, the operator's real database, or a real
mailbox. It runs against a throwaway directory.
"""

from __future__ import annotations

import csv
import datetime as _dt_module
import os
import random
import re
import sys
import tempfile
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

_REAL_DATETIME = _dt_module.datetime
_REAL_DATE = _dt_module.date


# ---------------------------------------------------------------------------
# The clock
# ---------------------------------------------------------------------------

class SimClock:
    """The only clock anything reads while the simulation runs."""

    def __init__(self, start: _dt_module.datetime):
        self.now = start

    def advance(self, **kw) -> None:
        self.now = self.now + timedelta(**kw)

    def day(self, start: _dt_module.datetime) -> int:
        return (self.now - start).days


@contextmanager
def _frozen_time(clock: SimClock) -> Iterator[None]:
    """Point every clock read in the package at ``clock``.

    The agents schedule, bill, age and throttle off ``datetime.now()`` and
    ``date.today()``. Moving a sales cycle forward by weeks means moving
    those, everywhere, and putting them back afterwards.
    """

    class SimDatetime(_REAL_DATETIME):
        @classmethod
        def now(cls, tz=None):  # noqa: D401 - mirrors the stdlib signature
            t = clock.now
            return t.astimezone(tz) if tz else t.replace(tzinfo=None)

        @classmethod
        def utcnow(cls):
            return clock.now.replace(tzinfo=None)

        @classmethod
        def today(cls):
            return clock.now.replace(tzinfo=None)

    class SimDate(_REAL_DATE):
        @classmethod
        def today(cls):
            d = clock.now.date()
            return cls(d.year, d.month, d.day)

    patched: list[tuple[Any, str, Any]] = []
    for name, mod in list(sys.modules.items()):
        if not mod or not (name.startswith("answerrank") or name.startswith("web")):
            continue
        for attr, real, fake in (("datetime", _REAL_DATETIME, SimDatetime),
                                 ("date", _REAL_DATE, SimDate)):
            if getattr(mod, attr, None) is real:
                patched.append((mod, attr, real))
                setattr(mod, attr, fake)
    # Functions that import ``date`` locally read it off the module itself.
    patched.append((_dt_module, "date", _REAL_DATE))
    patched.append((_dt_module, "datetime", _REAL_DATETIME))
    _dt_module.date = SimDate
    _dt_module.datetime = SimDatetime
    try:
        yield
    finally:
        for mod, attr, real in reversed(patched):
            setattr(mod, attr, real)


# ---------------------------------------------------------------------------
# The people on the other end — every reply below is made up
# ---------------------------------------------------------------------------

REPLIES: dict[str, list[str]] = {
    "interested": [
        "Yes please, send it over.",
        "Sure, send it.",
        "yes",
        "Interested. What did you find?",
        "Please do. Calls have been slow this spring and I've wondered why.",
        "Ok send it",
        "Yeah go ahead, I'd like to see who's showing up instead of us",
        "Sounds good, send the report",
        "Send it. Curious what ChatGPT says about us.",
        "Yes. Is this really free?",
    ],
    "nudge": [
        "Any update on that report?",
        "Still waiting on the report you mentioned.",
    ],
    "objection": [
        "How much would it cost to fix this?",
        "We already pay an SEO company every month. Why haven't they fixed this?",
        "Is there a contract? I'd want my lawyer to look at it first.",
        "What would you actually do each month?",
        "How long before we'd see a difference?",
        "Seems expensive for something I can't see.",
        "My nephew built our website, can't he just do this?",
        "Do you guarantee results?",
        "We're slammed right now, can this wait until the fall?",
        "We already have someone doing our marketing. What would you do differently?",
    ],
    "buy": [
        "Ok, let's do it. How do we get started?",
        "Alright, sign us up.",
        "Deal. Send me the invoice.",
        "Let's go with the growth plan.",
        "We're in. What do you need from me?",
        "Fine, let's try it for a few months.",
        "Go ahead and start.",
        "OK you've convinced me. Where do I pay?",
    ],
    "client_update": [
        "Added you as a manager on our Google profile. Name, address and phone are right.",
        "Thanks. Our address on Google is old, we moved to 1400 Main St last year.",
        "Who do I send the website login to?",
        "Great, looking forward to the first report.",
    ],
    "not_interested": [
        "No thanks.",
        "Not interested.",
        "We're all set, thanks.",
        "Let's hold off for now, thanks.",
    ],
    "unsubscribe": [
        "Please remove me from your list.",
        "Unsubscribe",
        "Stop emailing me.",
    ],
    "hostile": [
        "This is spam. Stop.",
        "How did you get this address? Reporting you.",
    ],
    "referral": [
        "You'd want to talk to my office manager about this.",
        "Forward it to my marketing guy, he handles this stuff.",
    ],
}

#: What each true intent may acceptably be read as.
ACCEPTABLE_READING: dict[str, set[str]] = {
    "interested": {"interested"},
    "nudge": {"interested", "question"},
    "objection": {"question"},
    "buy": {"ready_to_buy"},
    "client_update": {"client_message"},
    "not_interested": {"not_interested"},
    "unsubscribe": {"unsubscribe", "hostile"},
    "hostile": {"hostile", "unsubscribe"},
    "referral": {"referral"},
}

STEMS = ["Apex", "Summit", "Ironclad", "BlueRidge", "Cornerstone", "Vanguard",
         "Beacon", "Redwood", "Northgate", "Sterling", "Copperfield", "Harbor",
         "Keystone", "Pinnacle", "Lakeside", "Granite", "Oakmont", "Riverbend",
         "Silverline", "Trailhead", "Evergreen", "Foxhall", "Hollister", "Meridian"]

TRADE_SUFFIX = {
    "hvac": "Heating & Air", "plumbing": "Plumbing", "roofing": "Roofing",
    "dental": "Family Dental", "legal": "Law Group", "medical": "Medical Clinic",
    "insurance": "Insurance", "electrical": "Electric", "pest_control": "Pest Control",
    "garage_door": "Garage Doors", "landscaping": "Landscaping",
    "veterinary": "Animal Hospital", "chiropractic": "Chiropractic",
    "med_spa": "Aesthetics", "orthodontics": "Orthodontics",
    "foundation_repair": "Foundation Repair", "restoration": "Restoration",
    "pool": "Pools", "solar": "Solar", "tree_service": "Tree Service",
    "appliance_repair": "Appliance Repair", "auto_repair": "Auto Repair",
}

CITIES = [("Austin", "TX"), ("Charlotte", "NC"), ("Phoenix", "AZ"), ("Tampa", "FL"),
          ("Nashville", "TN"), ("Columbus", "OH"), ("Raleigh", "NC"), ("Denver", "CO"),
          ("Kansas City", "MO"), ("Boise", "ID"), ("Greenville", "SC"), ("Tucson", "AZ")]


@dataclass
class Delivered:
    at: _dt_module.datetime
    subject: str
    body: str
    kind: str


@dataclass
class Person:
    """One made-up business owner, and everything that happened to them."""

    email: str
    business: str
    domain: str
    persona: str = ""                 #: assigned the first time they hear from us
    reply_on_touch: int = 1
    plan: str = "growth"
    prospect_id: str = ""
    stage: str = "cold"
    received: list[Delivered] = field(default_factory=list)
    #: (due, text, true intent) — replies they will send, not yet read.
    outbox: list[tuple[_dt_module.datetime, str, str]] = field(default_factory=list)
    replies_sent: int = 0
    last_reply_at: _dt_module.datetime | None = None
    asked_report_at: _dt_module.datetime | None = None
    nudged: bool = False
    won_at: _dt_module.datetime | None = None
    lost_reason: str = ""
    stall_since: _dt_module.datetime | None = None

    @property
    def cold_received(self) -> int:
        return sum(1 for d in self.received if d.kind == "cold")


def classify_outbound(subject: str, body: str) -> str:
    """What kind of email this is, read the way the recipient would."""
    s, b = subject or "", body or ""
    if "visibility report" in s.lower():
        return "report"
    if s.startswith("You're in"):
        return "welcome"
    if (s.startswith(("Closing the loop", "One last thing"))
            or "Following up on the AI visibility check" in b
            or "Reply \"yes\" and it's yours" in b
            or "Reply “yes” and it’s yours" in b):
        return "cold"
    return "reply"


def _is_sales_pitch(body: str) -> bool:
    return bool(re.search(r"first report is free|report is still free|"
                          r"no charge, no call|Want the report\?", body or "", re.I))


# ---------------------------------------------------------------------------
# The world
# ---------------------------------------------------------------------------

@dataclass
class Issue:
    day: int
    kind: str
    who: str
    detail: str


class World:
    """Holds the fake mailbox, the people, and everything worth reporting."""

    def __init__(self, clock: SimClock, start: _dt_module.datetime, rng: random.Random):
        self.clock = clock
        self.start = start
        self.rng = rng
        self.people: dict[str, Person] = {}
        self.persona_bag: list[str] = []
        self.issues: list[Issue] = []
        self.sent_by_day: Counter[int] = Counter()
        self.cold_by_day: Counter[int] = Counter()
        self.bounced: set[str] = set()
        self.bounce_addresses: set[str] = set()
        self.console_gaps: set[str] = set()
        self.misreads: list[tuple[str, str, str, str]] = []  # who, true, read, text
        self.response_hours: list[float] = []
        self.awaiting_response: dict[str, _dt_module.datetime] = {}
        self.won: list[Person] = []

    def day(self) -> int:
        return self.clock.day(self.start)

    def issue(self, kind: str, who: str, detail: str) -> None:
        self.issues.append(Issue(self.day(), kind, who, detail))

    # ---- the mailbox ----

    def deliver(self, to_email: str, subject: str, body: str) -> tuple[bool, str]:
        email = to_email.lower()
        if email in self.bounce_addresses:
            self.bounced.add(email)
            return False, "bounced: recipient refused (550 no such user)"
        self.sent_by_day[self.day()] += 1
        person = self.people.get(email)
        if person is None:
            self.issue("mail_to_unknown", email, f"'{subject}' went to an address "
                                                 f"no simulated person owns")
            return True, "sent"
        kind = classify_outbound(subject, body)
        if kind == "cold":
            self.cold_by_day[self.day()] += 1
        person.received.append(Delivered(self.clock.now, subject, body, kind))
        self._react(person, subject, body, kind)
        return True, "sent"

    def _schedule(self, person: Person, intent: str, days: tuple[int, int] = (1, 2),
                  text: str | None = None) -> None:
        due = self.clock.now + timedelta(days=self.rng.randint(*days),
                                         hours=self.rng.randint(0, 6))
        person.outbox.append((due, text or self.rng.choice(REPLIES[intent]), intent))

    def _react(self, p: Person, subject: str, body: str, kind: str) -> None:
        if not p.persona:
            p.persona = self.persona_bag.pop() if self.persona_bag else "silent"
            if p.persona == "buyer":
                p.reply_on_touch = self.rng.choices([1, 2, 3], weights=[50, 30, 20])[0]
                p.plan = self.rng.choices(["growth", "starter", "managed"],
                                          weights=[60, 25, 15])[0]

        # Whatever the persona, some emails are wrong to send at all.
        if p.stage in {"unsubscribed", "hostile", "declined"}:
            self.issue("mailed_after_opt_out", p.business,
                       f"'{subject}' sent after they said: {p.stage}")
        if p.replies_sent and kind == "cold":
            self.issue("cold_after_reply", p.business,
                       f"cold-sequence email '{subject}' sent to someone who had "
                       f"already replied")
        if p.won_at and (kind == "cold" or _is_sales_pitch(body)):
            self.issue("pitched_a_client", p.business,
                       f"'{subject}' — a sales email to a paying client")

        if p.email in self.awaiting_response and kind in {"reply", "report", "welcome"}:
            asked = self.awaiting_response.pop(p.email)
            self.response_hours.append((self.clock.now - asked).total_seconds() / 3600)

        persona = p.persona
        if persona == "silent" or p.stage in {"unsubscribed", "hostile", "declined", "lost"}:
            return

        if persona in {"unsubscribe", "hostile", "not_interested", "referral"}:
            if kind == "cold" and p.stage == "cold":
                self._schedule(p, persona)
                p.stage = "replying"   # final stage is set once the reply is read
            return

        # --- a buyer ---
        if p.stage == "cold" and kind == "cold" and p.cold_received >= p.reply_on_touch:
            self._schedule(p, "interested")
            p.stage = "asked_for_report"
        elif p.stage in {"asked_for_report", "nudged"} and kind == "report":
            self._schedule(p, "objection")
            p.stage = "objected"
        elif p.stage == "objected_waiting" and kind in {"reply", "report"}:
            self._schedule(p, "buy")
            p.stage = "buying"
        elif p.stage == "client" and kind == "welcome":
            self._schedule(p, "client_update")
            p.stage = "client_engaged"

    def replies_due(self) -> list[tuple[Person, str, str, _dt_module.datetime]]:
        out = []
        for p in self.people.values():
            ready = [r for r in p.outbox if r[0] <= self.clock.now]
            p.outbox = [r for r in p.outbox if r[0] > self.clock.now]
            for due, text, intent in ready:
                out.append((p, text, intent, due))
        return sorted(out, key=lambda row: row[3])

    def daily_checks(self) -> None:
        """What a real buyer does when nothing arrives."""
        for p in self.people.values():
            if p.persona != "buyer" or p.stage in {"lost", "client", "client_engaged"}:
                continue
            waited = (self.clock.now - p.last_reply_at).days if p.last_reply_at else 0
            if p.stage == "asked_for_report" and waited >= 4 and not p.nudged:
                self._schedule(p, "nudge", (0, 0))
                p.nudged = True
                p.stage = "nudged"
            elif p.stage in {"asked_for_report", "nudged"} and p.asked_report_at and \
                    (self.clock.now - p.asked_report_at).days >= 10:
                p.stage, p.lost_reason = "lost", "asked for the free report; it never arrived"
            elif p.stage == "objected_waiting" and waited >= 8:
                p.stage, p.lost_reason = "lost", "asked a question before buying; never got an answer"
            elif p.stage == "buying_waiting" and waited >= 8:
                p.stage, p.lost_reason = "lost", "said yes; nobody closed the sale"


class _SimMailer:
    """Stands in for SMTP. Delivers into the world instead of the internet."""

    world: World | None = None

    def __init__(self, settings, config=None):
        self.settings = settings

    def send(self, to_email: str, subject: str, body: str) -> tuple[bool, str]:
        assert self.world is not None
        return self.world.deliver(to_email, subject, body)


# ---------------------------------------------------------------------------
# Running it
# ---------------------------------------------------------------------------

def _seed_businesses(world: World, n: int, verticals: list[str], path: Path) -> None:
    rng = world.rng
    rows = []
    used: set[str] = set()
    for i in range(n):
        vertical = verticals[i % len(verticals)]
        city, state = CITIES[(i // len(verticals)) % len(CITIES)]
        while True:
            stem = rng.choice(STEMS)
            name = f"{stem} {TRADE_SUFFIX.get(vertical, 'Services')}"
            slug = re.sub(r"[^a-z]", "", f"{stem}{vertical}{city}".lower())[:28]
            domain = f"{slug}{rng.randint(10, 99)}.com"
            if domain not in used:
                used.add(domain)
                break
        local = rng.choice(["owner", "office", "info", "hello", "info+web"])
        email = f"{local}@{domain}"
        rows.append({"name": name, "city": city, "state": state, "vertical": vertical,
                     "website": f"https://{domain}", "email": email,
                     "phone": f"555-01{i:02d}"})
        world.people[email] = Person(email=email, business=name, domain=domain)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _persona_bag(rng: random.Random, sales: int) -> list[str]:
    bag = (["buyer"] * sales + ["not_interested"] * max(4, sales // 3)
           + ["unsubscribe"] * max(3, sales // 4) + ["hostile"] * max(1, sales // 10)
           + ["referral"] * max(2, sales // 6))
    bag += ["silent"] * (len(bag) * 3)
    rng.shuffle(bag)
    return bag


def run(sales: int = 30, days: int = 100, seed: int = 7,
        tick_hours: int = 2, say: Callable[[str], None] | None = None,
        keep: bool = False) -> dict[str, Any]:
    """Run the simulation and return the scorecard.

    ``keep`` leaves the throwaway database and rendered reports on disk to
    be inspected; otherwise they are removed when the run ends.
    """
    say = say or (lambda _line: None)

    # Import everything the fleet touches before patching the clock.
    from . import crawlers, sending
    from .agents.scout import defensible_verticals
    from .config import Settings
    from .orchestrator import Orchestrator
    from .store import Store
    from web.api import Api

    rng = random.Random(seed)
    work = Path(tempfile.mkdtemp(prefix="answerrank-sim-"))
    start = _REAL_DATETIME(2026, 10, 5, 8, 0, tzinfo=timezone.utc)
    clock = SimClock(start)
    world = World(clock, start, rng)

    settings = Settings()
    settings.demo_mode = True                   # mock answer engines, no API calls
    settings.database_path = str(work / "sim.db")
    settings.output_dir = str(work / "out")
    settings.physical_address = "1 Simulation Way, Austin, TX 78701"
    settings.website = "https://answerrank.example"
    settings.from_email = "hello@answerrank.example"
    settings.outreach.min_seconds_between_sends = 0
    Path(settings.output_dir).mkdir(parents=True, exist_ok=True)

    verticals = defensible_verticals(settings.pricing.growth_monthly,
                                     settings.pricing.ladder())[:8]
    bag = _persona_bag(rng, sales)
    seed_file = work / "seed.csv"
    _seed_businesses(world, int(len(bag) * 1.4), verticals, seed_file)
    world.persona_bag = bag
    # About 1.3% of addresses dead — a realistic rate for addresses read off
    # business contact pages, and inside the 2% ceiling overall. Whether the
    # brake trips then depends on how they cluster, which is the real risk.
    for p in rng.sample(list(world.people.values()), max(1, len(world.people) // 75)):
        world.bounce_addresses.add(p.email)

    # robots.txt: no network. Everyone's site lets the engines in.
    def _no_network_access(website, timeout=10):
        return crawlers.Access(domain=website.split("//")[-1].split("/")[0])

    patches = [(crawlers, "check_access", _no_network_access),
               (sending, "Mailer", _SimMailer)]
    originals = [(obj, name, getattr(obj, name)) for obj, name, _ in patches]
    for obj, name, value in patches:
        setattr(obj, name, value)
    _SimMailer.world = world
    old_seed = os.environ.get("ANSWERRANK_SEED_FILE")
    os.environ["ANSWERRANK_SEED_FILE"] = str(seed_file)

    try:
        with _frozen_time(clock):
            store = Store(settings.database_path)
            api = Api(store, settings)
            orch = Orchestrator(store, settings)
            by_prospect: dict[str, Person] = {}

            def link_people() -> None:
                for pr in store.get_prospects(limit=10_000):
                    person = world.people.get((pr.business.email or "").lower())
                    if person and not person.prospect_id:
                        person.prospect_id = pr.id
                        by_prospect[pr.id] = person

            total_ticks = days * 24 // tick_hours
            last_session = None
            for t in range(total_ticks):
                orch.tick()
                clock.advance(hours=tick_hours)
                link_people()

                # The operator's session: once a day, first thing, phone in hand.
                if clock.now.hour >= 9 and last_session != clock.now.date():
                    last_session = clock.now.date()
                    world.daily_checks()
                    _operator_session(world, api, store, by_prospect, say)

                if t % (24 // tick_hours * 10) == 0:
                    say(f"  day {world.day():>3}: {len(world.won)} sales, "
                        f"{sum(world.sent_by_day.values())} emails sent")

            card = _scorecard(world, store, settings, sales, days, work)
            if not keep:
                card["work_dir"] = ""
            return card
    finally:
        for obj, name, value in originals:
            setattr(obj, name, value)
        _SimMailer.world = None
        if not keep:
            import shutil
            shutil.rmtree(work, ignore_errors=True)
        if old_seed is None:
            os.environ.pop("ANSWERRANK_SEED_FILE", None)
        else:
            os.environ["ANSWERRANK_SEED_FILE"] = old_seed


def _operator_session(world: World, api, store, by_prospect: dict[str, Person],
                      say: Callable[[str], None]) -> None:
    """Everything the operator does, using only what the console offers."""
    # 1. Paste in every reply that reached the inbox since yesterday.
    for person, text, intent, written_at in world.replies_due():
        if not person.prospect_id:
            world.issue("reply_from_unknown", person.business,
                        "replied, but no prospect record could be found for them")
            continue
        result = api.log_reply(person.prospect_id, text)
        if "error" in result:
            world.issue("reply_rejected", person.business,
                        f"console refused the reply: {result['error']}")
            continue
        read = result.get("intent", "")
        if read not in ACCEPTABLE_READING.get(intent, {intent}):
            world.misreads.append((person.business, intent, read, text))
        person.replies_sent += 1
        person.last_reply_at = world.clock.now
        if intent in {"interested", "nudge", "objection", "buy", "client_update",
                      "referral"} and result.get("draft"):
            # Timed from when they wrote, not from when the operator read it:
            # the wait the customer experiences is the one that matters.
            world.awaiting_response.setdefault(person.email, written_at)
        elif intent in {"interested", "nudge", "objection", "buy"}:
            world.issue("no_reply_drafted", person.business,
                        f"they wrote “{text}” and nothing was drafted to answer it")

        opted_out = {"unsubscribe": "unsubscribed", "hostile": "hostile",
                     "not_interested": "declined", "referral": "referred"}
        if intent in opted_out:
            person.stage = opted_out[intent]
        elif intent == "interested":
            person.asked_report_at = person.asked_report_at or world.clock.now
        elif intent == "objection":
            person.stage = "objected_waiting"
        elif intent == "buy":
            person.stage = "buying_waiting"
            # The customer said yes. The operator taps Won.
            won = api.win(person.prospect_id, person.plan)
            if "error" in won:
                world.issue("win_failed", person.business, won["error"])
            else:
                person.stage, person.won_at = "client", world.clock.now
                world.won.append(person)

    # 2. Approve every draft — a busy operator trusts the drafts.
    drafts = api.inbox("drafted", 100)["items"]
    while drafts:
        api.approve([d["id"] for d in drafts])
        drafts = api.inbox("drafted", 100)["items"]

    # 3. Tap Send.
    result = api.send(100)
    reasons = "; ".join(result.get("reasons", []))
    if "paused" in reasons:
        world.issue("cold_sending_paused", "operator", reasons)
    elif result.get("blocked") and "cap" not in reasons and "No approved" not in reasons:
        world.issue("send_blocked", "operator", reasons)


# ---------------------------------------------------------------------------
# The scorecard
# ---------------------------------------------------------------------------

def _scorecard(world: World, store, settings, sales: int, days: int,
               work: Path) -> dict[str, Any]:
    buyers = [p for p in world.people.values() if p.persona == "buyer"]
    lost = [p for p in buyers if p.stage == "lost"]
    stuck = [p for p in buyers if not p.won_at and p.stage != "lost"]
    clients = store.get_clients("active")
    client_ids = {c.id for c in clients}

    # Billing: each client once for every calendar month it was active.
    ledger_rows = []
    with store.conn() as cx:
        ledger_rows = [dict(r) for r in cx.execute("SELECT * FROM ledger")]
    revenue_by_client: dict[str, float] = defaultdict(float)
    bills_by_client_month: Counter[tuple[str, str]] = Counter()
    for row in ledger_rows:
        if row["kind"] == "revenue" and row["category"] == "subscription":
            revenue_by_client[row["client_id"]] += row["amount"]
            bills_by_client_month[(row["client_id"], row["occurred_at"][:7])] += 1
    double_billed = [k for k, n in bills_by_client_month.items() if n > 1]
    unbilled = [c for c in clients if c.id not in revenue_by_client]

    # Onboarding, delivery, reporting.
    welcomes = Counter(p.email for p in world.won for d in p.received if d.kind == "welcome")
    no_welcome = [p.business for p in world.won if not welcomes.get(p.email)]
    extra_welcome = [p.business for p in world.won if welcomes.get(p.email, 0) > 1]
    no_deliverables, no_report = [], []
    audits_per_client: dict[str, int] = {}
    for c in clients:
        history = store.audit_history(c.business.id, limit=100)
        audits_per_client[c.business.name] = len(history)
        if not any(store.get_deliverables(a.id) for a in history):
            no_deliverables.append(c.business.name)
        if not c.last_report_at:
            no_report.append(c.business.name)

    # Pipeline integrity: a paying client's record should still say so.
    stage_of = {p.id: p.stage for p in store.get_prospects(limit=10_000)}
    demoted = [p.business for p in world.won
               if stage_of.get(p.prospect_id) not in {"won", None}]

    # Retention: false alarms on clients who are plainly talking to us.
    from .agents.retention import RetentionAgent
    health = RetentionAgent(store, settings).portfolio()
    engaged = {p.business for p in world.won if p.stage == "client_engaged"}
    false_alarms = [h.name for h in health
                    if h.name in engaged and any("No contact on record" in s
                                                 for s in h.signals)]

    # Compliance and sending. The warm-up cap governs cold volume; answers
    # to people who wrote to us are deliberately outside it.
    cap_breaches = []
    first_send_day = min(world.sent_by_day) if world.sent_by_day else 0
    for day, n in sorted(world.cold_by_day.items()):
        cap = settings.outreach.warmup_cap(day - first_send_day)
        if n > cap:
            cap_breaches.append((day, n, cap))
    total_sent = sum(world.sent_by_day.values())
    bounce_rate = len(world.bounced) / max(1, total_sent + len(world.bounced))

    runs_failed = []
    with store.conn() as cx:
        runs_failed = [dict(r) for r in cx.execute(
            "SELECT agent, error FROM agent_runs WHERE status='error'")]

    issues_by_kind: dict[str, list[Issue]] = defaultdict(list)
    for i in world.issues:
        issues_by_kind[i.kind].append(i)

    rh = sorted(world.response_hours)
    return {
        "work_dir": str(work),
        "days": days,
        "target_sales": sales,
        "buyers_reached": len(buyers),
        "sales_closed": len(world.won),
        "lost": [(p.business, p.lost_reason) for p in lost],
        "stuck": [(p.business, p.stage) for p in stuck],
        "clients_on_books": len(clients),
        "mrr": round(store.mrr(), 2),
        "mrr_expected": round(sum(settings.pricing.plan_price(p.plan) for p in world.won), 2),
        "revenue_billed": round(sum(revenue_by_client.values()), 2),
        "double_billed": double_billed,
        "unbilled_clients": [c.business.name for c in unbilled],
        "welcome_missing": no_welcome,
        "welcome_duplicated": extra_welcome,
        "no_deliverables": no_deliverables,
        "no_report": no_report,
        "audits_per_client": audits_per_client,
        "clients_demoted_in_pipeline": demoted,
        "retention_false_alarms": false_alarms,
        "retention_bands": dict(Counter(h.band for h in health)),
        "emails_sent": total_sent,
        "bounces": len(world.bounced),
        "bounce_rate": round(bounce_rate, 4),
        "cap_breaches": cap_breaches,
        "misreads": world.misreads,
        "response_hours_median": rh[len(rh) // 2] if rh else None,
        "response_hours_worst": rh[-1] if rh else None,
        "issues": {k: [(i.day, i.who, i.detail) for i in v]
                   for k, v in issues_by_kind.items()},
        "agent_errors": runs_failed,
        "api_spend": round(sum(r["amount"] for r in ledger_rows
                               if r["kind"] == "cost" and r["category"] == "api"), 2),
    }


def render(card: dict[str, Any]) -> str:
    """The scorecard in plain English, worst news first."""
    lines: list[str] = []
    add = lines.append
    ok = lambda cond: "✓" if cond else "✗"  # noqa: E731

    add(f"\nSIMULATION — {card['target_sales']} buyers, {card['days']} days\n" + "=" * 68)
    add(f"  {ok(card['sales_closed'] == card['target_sales'])} Sales closed: "
        f"{card['sales_closed']} of {card['target_sales']} buyers")
    for name, why in card["lost"]:
        add(f"      lost  {name}: {why}")
    for name, stage in card["stuck"]:
        add(f"      stuck {name}: still at '{stage}' when the simulation ended")

    add(f"  {ok(card['mrr'] == card['mrr_expected'])} MRR ${card['mrr']:,.0f} "
        f"(should be ${card['mrr_expected']:,.0f})")
    add(f"  {ok(not card['double_billed'] and not card['unbilled_clients'])} Billing: "
        f"${card['revenue_billed']:,.0f} billed, {len(card['double_billed'])} double-billed, "
        f"{len(card['unbilled_clients'])} never billed")
    add(f"  {ok(not card['welcome_missing'] and not card['welcome_duplicated'])} Welcome emails: "
        f"{len(card['welcome_missing'])} missing, {len(card['welcome_duplicated'])} duplicated")
    add(f"  {ok(not card['no_deliverables'] and not card['no_report'])} Delivery: "
        f"{len(card['no_deliverables'])} clients with no deliverables, "
        f"{len(card['no_report'])} with no report")
    if card["audits_per_client"]:
        counts = sorted(card["audits_per_client"].values())
        add(f"      audits per client: {counts[0]}–{counts[-1]}")
    add(f"  {ok(not card['clients_demoted_in_pipeline'])} Paying clients shown as "
        f"something else in the pipeline: {len(card['clients_demoted_in_pipeline'])}")
    add(f"  {ok(not card['retention_false_alarms'])} Retention false alarms on clients "
        f"who are talking to us: {len(card['retention_false_alarms'])}  "
        f"(bands: {card['retention_bands']})")
    add(f"  {ok(not card['cap_breaches'])} Warm-up cap breaches: {len(card['cap_breaches'])}")
    add(f"  {ok(card['bounce_rate'] < 0.02)} Bounces: {card['bounces']} of "
        f"{card['emails_sent'] + card['bounces']} ({card['bounce_rate']:.1%})")
    add(f"  {ok(not card['misreads'])} Replies misread: {len(card['misreads'])}")
    for who, true, read, text in card["misreads"][:12]:
        add(f"      “{text}” — meant {true}, read as {read or 'nothing'}")
    if card["response_hours_median"] is not None:
        add(f"    Time to answer a reply: median {card['response_hours_median']:.0f}h, "
            f"worst {card['response_hours_worst']:.0f}h")
    add(f"  {ok(not card['agent_errors'])} Agent crashes: {len(card['agent_errors'])}")
    for row in card["agent_errors"][:5]:
        add(f"      {row['agent']}: {row['error'][:90]}")

    brakes = {k: v for k, v in card["issues"].items() if k in SAFETY_BRAKES}
    wrong = {k: v for k, v in card["issues"].items() if k not in SAFETY_BRAKES}
    if wrong:
        add("\n  WHAT WENT WRONG")
        for kind, rows in sorted(wrong.items(), key=lambda kv: -len(kv[1])):
            add(f"  \u2717 {kind} \u00d7{len(rows)}")
            for day, who, detail in rows[:3]:
                add(f"      day {day:>3} {who}: {detail[:110]}")
    for kind, rows in brakes.items():
        add(f"\n  SAFETY BRAKE \u2014 {SAFETY_BRAKES[kind]}")
        add(f"      fired on day {rows[0][0]} for {len(rows)} day(s): {rows[0][2][:120]}")
    add(f"\n  {card['emails_sent']} emails sent · ${card['api_spend']:.2f} simulated API spend")
    if card.get("work_dir"):
        add(f"  Scratch files: {card['work_dir']}")
    add("\n  The replies were made up and the answer engines were simulated. This")
    add("  shows whether the software handles a sale end to end, not whether a")
    add("  real market will buy.")
    return "\n".join(lines)


#: Things that stop sending on purpose. Reported, but not failures: a brake
#: firing on a real rate over the ceiling is the software working.
SAFETY_BRAKES = {
    "cold_sending_paused": "bounce rate reached the 2% ceiling, so cold "
                           "sending paused on its own while replies kept going",
}


def passed(card: dict[str, Any]) -> bool:
    """Whether the software handled every sale it was given."""
    tolerated = set(SAFETY_BRAKES)
    return (card["sales_closed"] == card["target_sales"]
            and card["mrr"] == card["mrr_expected"]
            and not card["double_billed"] and not card["unbilled_clients"]
            and not card["welcome_missing"] and not card["welcome_duplicated"]
            and not card["no_deliverables"] and not card["no_report"]
            and not card["clients_demoted_in_pipeline"]
            and not card["retention_false_alarms"]
            and not card["cap_breaches"] and not card["misreads"]
            and not card["agent_errors"]
            and not (set(card["issues"]) - tolerated))
