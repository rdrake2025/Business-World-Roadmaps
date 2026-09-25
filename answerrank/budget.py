"""Personal + business budgeting for a bootstrapped operator.

Written for the realistic case: someone funding this from a day job with
limited slack, who needs to know three things at any moment —

1. Can I afford this month?
2. How long can I keep funding it if nothing sells? (runway)
3. When is it safe to leave the job?

Personal figures live in ``budget.yml`` (never committed — it is personal
financial data). Business figures come from the ledger the Bookkeeper agent
already maintains, so business spend is tracked automatically rather than
typed in twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

# ---------------------------------------------------------------------------
# Launch phases. The whole point: spend nothing until the channel is proven,
# then let each phase be funded by the revenue the previous phase produced.
# ---------------------------------------------------------------------------

PHASES: dict[str, dict[str, Any]] = {
    "0_test": {
        "label": "Phase 0 — Prove the channel",
        "trigger": "Start here. Before any entity or insurance.",
        "one_time": {
            "sending domain (1 yr)": 12.0,
            "API credits float": 15.0,
        },
        "monthly": {
            "Google Workspace (1 seat, month to month)": 8.40,
            "domain amortised": 1.00,
            "API usage": 4.00,
            "server for the unsubscribe link + 24/7 fleet": 6.00,
        },
        "notes": [
            "The $6 server is needed before the first email, not after the first "
            "client: every email's unsubscribe link has to work from the public "
            "internet, and a laptop cannot serve it. See deploy/SERVER.md.",
            "No LLC yet. Sole proprietor is legal to test with; form the entity "
            "when money is actually coming in.",
            "A full 10-prompt audit costs about $0.06, so $15 of credit covers "
            "hundreds of prospects.",
        ],
    },
    "1_first_client": {
        "label": "Phase 1 — First client signed",
        "trigger": "Triggered by your first paying client. Funded by their payment.",
        "one_time": {
            "LLC filing (state fee)": 150.0,
            "lawyer review of contract": 350.0,
        },
        "monthly": {
            "registered agent": 15.0,
            "accounting software": 15.00,
        },
        "notes": [
            "Your first client's payment covers all of this with room left over.",
            "Registered agent also supplies the business address CAN-SPAM requires, "
            "so your home address stays off every email you send.",
        ],
    },
    "2_scaling": {
        "label": "Phase 2 — Three or more clients",
        "trigger": "Triggered at 3 clients / roughly $2,000 MRR.",
        "one_time": {},
        "monthly": {
            "E&O + liability insurance": 60.0,
            "second sending domain": 8.00,
            "email warmup tooling": 30.00,
        },
        "notes": [
            "Insurance before client number four, not after the first complaint.",
            "A second sending domain protects the first if deliverability slips.",
        ],
    },
}

DEFAULT_PERSONAL = {
    "monthly_income": 2500.0,
    "income_is_take_home": True,
    "savings": 0.0,
    "expenses": {
        "rent": 250.0,
        "food_groceries": 350.0,
        "phone": 50.0,
        "transport": 200.0,
        "utilities_internet": 120.0,
        "personal_other": 200.0,
    },
}


@dataclass
class Personal:
    monthly_income: float = 2500.0
    income_is_take_home: bool = True
    savings: float = 0.0
    expenses: dict[str, float] = field(default_factory=dict)

    @property
    def total_expenses(self) -> float:
        return round(sum(self.expenses.values()), 2)

    @property
    def net_income(self) -> float:
        """Take-home. If the figure given was gross, apply a rough tax haircut."""
        if self.income_is_take_home:
            return self.monthly_income
        return round(self.monthly_income * 0.85, 2)

    @property
    def disposable(self) -> float:
        return round(self.net_income - self.total_expenses, 2)


class BudgetFileError(Exception):
    """budget.yml exists but cannot be parsed. Says so in plain words."""


def load_personal(path: str | Path = "budget.yml") -> Personal:
    data = dict(DEFAULT_PERSONAL)
    p = Path(path)
    if p.exists() and yaml is not None:
        # Explicit UTF-8: the template above is written as UTF-8 and this
        # reads it back. Python's default is the platform encoding, which on
        # Windows is cp1252 — so the em-dash in the first line comes back
        # mangled, and anything the operator types outside Latin-1 fails to
        # round-trip through their own budget file.
        try:
            loaded = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise BudgetFileError(
                f"{p} could not be read: {exc}. Fix the file or delete it to "
                f"start again from the template."
            ) from exc
        data.update(loaded.get("personal", loaded))
    return Personal(
        monthly_income=float(data.get("monthly_income", 2500.0)),
        income_is_take_home=bool(data.get("income_is_take_home", True)),
        savings=float(data.get("savings", 0.0)),
        expenses={k: float(v) for k, v in (data.get("expenses") or {}).items()},
    )


def write_template(path: str | Path = "budget.yml") -> Path:
    p = Path(path)
    p.write_text("""# Personal budget — YOUR real numbers. Never committed to git.
# Edit every line. Guesses here produce a runway number you cannot trust.
personal:
  monthly_income: 2500          # what actually lands in your account
  income_is_take_home: true     # false if the figure above is pre-tax
  savings: 0                    # cash you could put behind this today

  expenses:
    rent: 250
    food_groceries: 350
    phone: 50
    transport: 200
    utilities_internet: 120
    personal_other: 200         # everything else, honestly
""", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Phase costs
# ---------------------------------------------------------------------------

def phase_cost(phase_key: str) -> tuple[float, float]:
    """Return (one_time, monthly) for a phase."""
    ph = PHASES[phase_key]
    return (
        round(sum(ph["one_time"].values()), 2),
        round(sum(ph["monthly"].values()), 2),
    )


def cumulative_monthly(through_phase: str) -> float:
    """Recurring business cost once you have reached a given phase."""
    total = 0.0
    for key in PHASES:
        total += sum(PHASES[key]["monthly"].values())
        if key == through_phase:
            break
    return round(total, 2)


def runway_months(savings: float, monthly_burn: float,
                  monthly_surplus: float = 0.0) -> float:
    """Months you can fund the business before running out of money.

    Disposable income is recurring, not a one-time pot: if it already covers
    the burn, the runway is indefinite and savings are never touched. Only
    the shortfall eats into savings.
    """
    if monthly_burn <= 0:
        return float("inf")
    shortfall = monthly_burn - monthly_surplus
    if shortfall <= 0:
        return float("inf")
    if savings <= 0:
        return 0.0
    return round(savings / shortfall, 1)


# ---------------------------------------------------------------------------
# Reinvestment policy
# ---------------------------------------------------------------------------

def reinvestment_split(monthly_profit: float) -> dict[str, float]:
    """How to divide business profit, by stage.

    The bands get progressively less aggressive about reinvestment as the
    business stops being fragile. Early on, everything that is not tax goes
    back in — a business with no reserve dies to its first surprise.
    """
    if monthly_profit <= 0:
        return {"tax_reserve": 0.0, "business_reserve": 0.0, "reinvest": 0.0, "to_you": 0.0}

    if monthly_profit < 1000:
        pct = {"tax_reserve": 0.30, "business_reserve": 0.70, "reinvest": 0.0, "to_you": 0.0}
        note = "Build a $1,000 buffer first. Take nothing yet."
    elif monthly_profit < 3000:
        pct = {"tax_reserve": 0.30, "business_reserve": 0.20, "reinvest": 0.30, "to_you": 0.20}
        note = "Buffer is healthy. Start funding growth."
    elif monthly_profit < 5000:
        pct = {"tax_reserve": 0.30, "business_reserve": 0.10, "reinvest": 0.30, "to_you": 0.30}
        note = "Reinvest hard — this is the stretch that decides month 12."
    else:
        pct = {"tax_reserve": 0.30, "business_reserve": 0.05, "reinvest": 0.20, "to_you": 0.45}
        note = "Target met. Start paying yourself properly."

    out = {k: round(monthly_profit * v, 2) for k, v in pct.items()}
    out["_note"] = note  # type: ignore[assignment]
    return out


def quit_threshold(job_take_home: float) -> dict[str, float]:
    """When it is actually safe to leave the job.

    Business profit is pre-tax and variable; a job wage is after-tax and
    reliable. Matching them dollar for dollar is a pay cut. The standard rule
    is to require a real multiple, sustained, with a cash buffer behind it.
    """
    # 30% of business profit goes to tax, so profit must gross up.
    replacement = job_take_home / 0.70
    return {
        "job_take_home": round(job_take_home, 2),
        "profit_to_match_pay": round(replacement, 2),
        "safe_quit_profit": round(replacement * 1.5, 2),
        "sustained_months": 3.0,
        "cash_buffer_needed": round(job_take_home * 6, 2),
    }


def milestones(job_take_home: float) -> list[dict[str, Any]]:
    """The handful of moments that actually change your situation."""
    q = quit_threshold(job_take_home)
    return [
        {"profit": 0, "clients": 0,
         "meaning": "Costs about $12/mo. Funded from your job. This is the testing phase."},
        {"profit": 466, "clients": 1,
         "meaning": "First client. Business is now self-funding and pays for the LLC."},
        {"profit": 1400, "clients": 2,
         "meaning": "Buffer built. Proof the channel repeats — the hardest milestone."},
        {"profit": 2800, "clients": 4,
         "meaning": "Roughly matches your job take-home before tax. Do not quit yet."},
        {"profit": round(q["profit_to_match_pay"]), "clients": 5,
         "meaning": "After tax, this genuinely replaces your pay. Still do not quit."},
        {"profit": 5000, "clients": 6,
         "meaning": "Target. About $3,500/mo in your pocket."},
        {"profit": round(q["safe_quit_profit"]), "clients": 8,
         "meaning": f"Safe to leave the job — after {q['sustained_months']:.0f} consecutive "
                    f"months here, with ${q['cash_buffer_needed']:,.0f} banked."},
    ]
