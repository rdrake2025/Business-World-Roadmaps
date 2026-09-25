#!/usr/bin/env bash
# Domain setup for macOS and Linux. Companion to the Windows menu's Email domain option.
#
# Separate from start.sh on purpose: DNS takes minutes to hours to appear, so
# this is something you run, go and add a record, and run again. Burying it in
# the launcher would mean restarting the server to re-check.
set -uo pipefail
cd "$(dirname "$0")"

echo
echo "  ================================================================"
echo "    ANSWERRANK - SENDING DOMAIN SETUP"
echo "  ================================================================"
echo

if [ ! -x ".venv/bin/python" ]; then
  echo "  [X] Setup has not been run yet."
  echo "      Run ./start.sh first and let it finish, then come back."
  echo
  exit 1
fi
VPY=".venv/bin/python"

DOMAIN="${1:-}"
if [ -z "$DOMAIN" ]; then
  echo "    Type the domain you bought and press Enter."
  echo "    Just the domain - no https, no www.    Example: getanswerrank.com"
  echo
  read -r -p "    Domain: " DOMAIN
fi
if [ -z "$DOMAIN" ]; then
  echo
  echo "  [X] No domain entered. Nothing was changed."
  exit 1
fi

PROVIDER="${2:-}"
if [ -z "$PROVIDER" ]; then
  echo
  echo "    Where is your email mailbox?"
  echo
  echo "      1  Google Workspace     (about \$7/month - recommended)"
  echo "      2  Zoho Mail            (about \$1/month)"
  echo "      3  Microsoft 365        (about \$6/month)"
  echo "      4  Fastmail             (about \$5/month)"
  echo "      5  Not set up yet / something else"
  echo
  read -r -p "    Choose 1-5 [1]: " CHOICE
  case "${CHOICE:-1}" in
    1) PROVIDER="google" ;;
    2) PROVIDER="zoho" ;;
    3) PROVIDER="microsoft" ;;
    4) PROVIDER="fastmail" ;;
    *) PROVIDER="" ;;
  esac
fi

echo
echo "  ----------------------------------------------------------------"
echo

if [ -n "$PROVIDER" ]; then
  "$VPY" run.py domain "$DOMAIN" --provider "$PROVIDER"
else
  "$VPY" run.py domain "$DOMAIN"
fi
RESULT=$?

echo
echo "  ================================================================"
if [ "$RESULT" -eq 0 ]; then
  echo "    DOMAIN IS READY"
  echo "  ================================================================"
  echo
  echo "    Next: run ./start.sh and read the doctor output."
else
  echo "    NOT FINISHED YET"
  echo "  ================================================================"
  echo
  echo "    Add the records shown above at your registrar, wait a few"
  echo "    minutes, then run this again. It is safe to repeat."
fi
echo
