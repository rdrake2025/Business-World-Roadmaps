"""Interactive first-run setup.

Asks for the handful of things the system cannot infer, writes both config
files, and hands over to the doctor. Designed so someone who does not write
code can get from a fresh clone to a working install without reading any
documentation first.

Every prompt has a sensible default and explains why it is being asked —
a setup step you do not understand is a setup step you get wrong.
"""

from __future__ import annotations

from pathlib import Path

from . import knowledge
from .budget import write_template as write_budget_template
from .config import Settings

#: Derived, never copied. A hand-maintained list here offered seven trades of
#: the twenty-two the system supports, and silently replaced anything else
#: the operator typed with "hvac" — so a plumber setting this up got an HVAC
#: install without being told. This is the fifth place that pattern appeared.
VERTICALS = list(knowledge.VERTICALS)


def ask(prompt: str, default: str = "", why: str = "", required: bool = False) -> str:
    if why:
        print(f"\n  \033[2m{why}\033[0m")
    suffix = f" [{default}]" if default else ""
    while True:
        try:
            answer = input(f"  {prompt}{suffix}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nSetup cancelled. Nothing was written.")
            raise SystemExit(1)
        value = answer or default
        if value or not required:
            return value
        print("  \033[31mThis one is required.\033[0m")


def ask_yes(prompt: str, default: bool = True) -> bool:
    d = "Y/n" if default else "y/N"
    try:
        answer = input(f"  {prompt} [{d}]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        # Same exit as `ask`. Without this, Ctrl-D at a yes/no prompt ended
        # setup in a traceback rather than a sentence.
        print("\n\nSetup cancelled. Nothing was written.")
        raise SystemExit(1) from None
    if not answer:
        return default
    return answer.startswith("y")


def ask_money(prompt: str, default: str, why: str = "") -> float:
    """A dollar figure, asked until it is one.

    ``float(ask(...))`` ends the whole wizard in a ValueError traceback if
    the operator types "$297" or "1,997" — losing everything they had
    already entered, at the first thing they ever run.
    """
    while True:
        raw = ask(prompt, default, why=why)
        cleaned = raw.replace("$", "").replace(",", "").replace("/mo", "").strip()
        try:
            value = float(cleaned)
        except ValueError:
            print(f"  \033[31m'{raw}' is not a number. Digits only, e.g. {default}.\033[0m")
            continue
        if value < 0:
            print("  \033[31mThat cannot be negative.\033[0m")
            continue
        return value


def run(settings: Settings, config_path: str = "answerrank.yml") -> int:
    print("\n" + "=" * 68)
    print("  ANSWERRANK SETUP")
    print("=" * 68)
    print("\n  Six questions. You can change any of it later by editing")
    print("  answerrank.yml, and nothing here costs money.")

    brand = ask("Business name", settings.brand,
                why="What clients will see. Keep it short.")

    legal = ask("Legal entity name", f"{brand} LLC",
                why="Goes in the footer of every email. If you have not formed an "
                    "entity yet, your own name is fine — you can trade as a sole "
                    "proprietor while you test.")

    domain = ask("Your sending domain", "",
                 why="The domain you will send email FROM. Use a separate one from "
                     "your main site — if it ever gets burned, your real domain "
                     "survives. Example: getanswerrank.com",
                 required=True).lower().lstrip("@").replace("https://", "").replace("http://", "").strip("/")

    from_email = ask("Send from", f"hello@{domain}")
    website = ask("Public website URL", f"https://{domain}",
                  why="Where the landing page and unsubscribe endpoint live.")

    address = ask("Business postal address", "",
                  why="LEGALLY REQUIRED in every commercial email (CAN-SPAM), but it "
                      "does NOT have to be your home. The FTC accepts a street "
                      "address, a USPS-registered PO Box, or a mailbox from a "
                      "commercial mail receiving agency. A registered agent "
                      "(~$15/mo) also works. Sending is blocked until this is set; "
                      "put your home address in for now and change it later in "
                      "answerrank.yml.",
                  required=True)

    # Twenty-two trades is too many to print on one line, so the prompt
    # shows a few and the answer is checked against all of them.
    sample = "/".join(VERTICALS[:6])
    while True:
        vertical = ask(f"Starting vertical ({sample}/… — {len(VERTICALS)} supported)",
                       "hvac",
                       why="Pick ONE. Specificity is what makes the cold email "
                           "land. HVAC has the highest urgency and the worst AI "
                           "visibility. Type `list` to see them all.").strip().lower()
        if vertical == "list":
            for key in VERTICALS:
                print(f"    {key:<22} {knowledge.get(key).label}")
            continue
        if vertical in VERTICALS:
            break
        print(f"  \033[31m'{vertical}' is not one of them. Type `list` to see "
              f"the options.\033[0m")

    print("\n" + "-" * 68)
    print("  PRICING — defaults are researched against the 2026 market.")
    print("-" * 68)
    if ask_yes("Use the default ladder ($297 / $499 / $997 / $1997)?"):
        audit, starter, growth, managed = 297, 499, 997, 1997
    else:
        audit = ask_money("One-time audit", "297")
        starter = ask_money("Starter monthly", "499")
        growth = ask_money("Growth monthly", "997")
        managed = ask_money("Managed monthly", "1997")

    target = ask_money("Monthly profit target", "5000",
                       why="What the dashboard measures you against.")

    path = Path(config_path)
    path.write_text(f"""# AnswerRank configuration — written by `run.py setup`
brand: "{brand}"
company_legal_name: "{legal}"
from_email: "{from_email}"
website: "{website}"

# CAN-SPAM: required in every commercial email. Sending is blocked without it.
physical_address: "{address}"

# What to sell and where. KEYS.bat can change both. Markets are "City, ST";
# leave empty to search the default twelve cities.
trades: ["{vertical}"]
markets: []

engines: [openai, anthropic, perplexity, google_aio]
prompts_per_audit: 10
tick_seconds: 300
profit_target_monthly: {target:g}

pricing:
  audit_one_time: {audit:g}
  starter_monthly: {starter:g}
  growth_monthly: {growth:g}
  managed_monthly: {managed:g}

# Stripe payment links, one per plan. In Stripe: Payment Links > New, with a
# RECURRING monthly price, so Stripe charges every month by itself. Paste the
# https://buy.stripe.com/... address for each plan you sell. Leave blank and
# you send invoices by hand and tap Paid when the money arrives.
payment_links:
  starter: ""
  growth: ""
  managed: ""

outreach:
  max_emails_total_per_day: 120
  max_emails_per_domain_per_day: 30
  min_seconds_between_sends: 90
  max_followups: 3
  followup_gap_days: 4
""", encoding="utf-8")
    print(f"\n  ✓ Wrote {path}")

    if not Path("budget.yml").exists() and ask_yes("\n  Set up personal budget tracking too?"):
        write_budget_template("budget.yml")
        print("  ✓ Wrote budget.yml — edit it with your real numbers")

    print("\n" + "=" * 68)
    print("  NEXT STEPS")
    print("=" * 68)
    print(f"""
  1. Add your DNS records on {domain}:
       SPF    TXT  @        v=spf1 include:_spf.google.com ~all
       DMARC  TXT  _dmarc   v=DMARC1; p=quarantine; rua=mailto:{from_email}
       DKIM   (enable in your mail provider, paste the record it gives you)

  2. Save your mailbox password and API keys (double-click KEYS.bat, or):
       python run.py keys
     It asks for each one in plain words and tests the mailbox.

  3. Check what is still blocking you:
       python3 run.py doctor

  4. Run your first audit:
       python3 run.py audit "Some Local Business" YourCity --state ST \\
           --vertical {vertical} --website https://theirsite.com --report

  5. Generate your calendar:
       python3 run.py schedule

  Sending stays blocked until the doctor is clean. That is deliberate.
""")
    return 0
