#!/usr/bin/env bash
# One command to get AnswerRank running on your own machine.
#
#   ./start.sh
#
# Creates an isolated environment, installs dependencies, verifies the build,
# configures the business on first run, reports what is still blocking you,
# and serves the landing page and unsubscribe endpoint.
#
# Safe to re-run. Nothing here costs money or sends email.

set -euo pipefail

BOLD=$'\033[1m'; DIM=$'\033[2m'; GRN=$'\033[32m'; YEL=$'\033[33m'; RED=$'\033[31m'; OFF=$'\033[0m'
cd "$(dirname "$0")"

step() { printf '\n%s▸ %s%s\n' "$BOLD" "$1" "$OFF"; }
ok()   { printf '  %s✓%s %s\n' "$GRN" "$OFF" "$1"; }
warn() { printf '  %s!%s %s\n' "$YEL" "$OFF" "$1"; }
die()  { printf '\n  %s✗ %s%s\n\n' "$RED" "$1" "$OFF"; exit 1; }

# ---------------------------------------------------------------- python
step "Checking Python"
PY=""
for c in python3.13 python3.12 python3.11 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info>=(3,11) else 1)' 2>/dev/null; then
        PY="$c"; break
    fi
done
[ -n "$PY" ] || die "Python 3.11 or newer is required. Install it from python.org, then re-run ./start.sh"
ok "$($PY --version)"

# ---------------------------------------------------------------- venv
step "Setting up an isolated environment"
if [ ! -d .venv ]; then
    "$PY" -m venv .venv || die "Could not create a virtual environment."
    ok "created .venv"
else
    ok ".venv already present"
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
ok "dependencies installed"

# ---------------------------------------------------------------- verify
step "Verifying the build"
if python -m unittest discover -s tests >/tmp/answerrank-tests.log 2>&1; then
    ok "$(grep -oE 'Ran [0-9]+ tests' /tmp/answerrank-tests.log) — all passing"
else
    tail -25 /tmp/answerrank-tests.log
    die "Tests failed. Full log: /tmp/answerrank-tests.log"
fi

# ---------------------------------------------------------------- configure
if [ ! -f answerrank.yml ]; then
    step "First run — let's configure the business"
    printf '  %sSix questions. Nothing here costs money.%s\n' "$DIM" "$OFF"
    python run.py setup
else
    step "Configuration"
    ok "answerrank.yml found"
fi

if [ ! -f budget.yml ]; then
    python run.py budget-init >/dev/null 2>&1 || true
    warn "budget.yml created — edit it with your real numbers, then: python run.py budget"
fi

# ---------------------------------------------------------------- doctor
step "What is still blocking you"
set +e
python run.py doctor
DOCTOR=$?
set -e

# ---------------------------------------------------------------- calendar
step "Your schedule"
if python run.py schedule --out schedule/answerrank-schedule.ics >/dev/null 2>&1; then
    ok "schedule/answerrank-schedule.ics — email it to yourself and open it on your phone"
fi

# ---------------------------------------------------------------- go
step "Ready"
cat <<BANNER

  ${BOLD}Try these now — none of them cost anything:${OFF}

    ${DIM}# Audit a real business you know${OFF}
    python run.py audit "Some Local Business" YourCity --state ST \\
        --vertical hvac --website https://theirsite.com --report

    ${DIM}# See the whole pipeline run${OFF}
    python run.py tick --force

    ${DIM}# Where the business stands${OFF}
    python run.py dashboard
    python run.py budget
    python run.py forecast

  ${BOLD}On your phone:${OFF} same Wi-Fi as this laptop, open the link below,
  then add it to your home screen — it runs like an app.

  ${BOLD}Docs:${OFF} ANSWERRANK.md · business/04_LAUNCH_CHECKLIST.md

BANNER

if [ "$DOCTOR" -ne 0 ]; then
    warn "Sending email is blocked until the items above are fixed. That is deliberate."
fi

step "Starting the server"
printf '  %sThe link for your phone is printed below — scan or open it once.%s\n\n' "$DIM" "$OFF"

# Open the console on this laptop once the server is listening.
( sleep 2
  TOKEN="$(python - <<'PY' 2>/dev/null
import sys
sys.path.insert(0, ".")
from web.app import create_app
print(create_app().token)
PY
)"
  [ -n "$TOKEN" ] || exit 0
  for o in open xdg-open; do
      command -v "$o" >/dev/null 2>&1 && \
          "$o" "http://localhost:8000/app?t=$TOKEN" >/dev/null 2>&1 && break
  done ) &

exec python run.py web --port 8000
