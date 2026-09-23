#!/bin/bash
# AnswerRank server setup — runs once, as root, on a fresh Ubuntu 24.04 server.
#
# Do not run this template directly. `python run.py server-script --domain
# yourdomain.com` fills it in with your domain, settings and keys, and writes
# a file you paste into the server provider's "user data" box when creating
# the server. See deploy/SERVER.md.
#
# What it does, in order:
#   1. Installs Python, git and Caddy (which gets and renews the HTTPS
#      certificate by itself — Caddy's official apt repository).
#   2. Downloads AnswerRank to /opt/answerrank and installs its libraries.
#   3. Writes your answerrank.yml and keys.env.
#   4. Starts the web app (behind Caddy) and the agent fleet as services that
#      restart on failure and on reboot.
#   5. Opens only ports 22, 80 and 443.
#   6. Backs the database up nightly, and pulls updates from GitHub daily —
#      the same way start.bat updates the laptop.
set -euo pipefail
exec > >(tee -a /var/log/answerrank-setup.log) 2>&1

DOMAIN="__DOMAIN__"
REPO="__REPO__"
TOKEN="__TOKEN__"
APP=/opt/answerrank

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3-venv python3-pip git sqlite3 ufw curl gnupg \
    debian-keyring debian-archive-keyring apt-transport-https

curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    > /etc/apt/sources.list.d/caddy-stable.list
chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg \
    /etc/apt/sources.list.d/caddy-stable.list
apt-get update -y
apt-get install -y caddy

id answerrank >/dev/null 2>&1 || useradd --system --create-home \
    --home-dir /home/answerrank --shell /usr/sbin/nologin answerrank
if [ ! -d "$APP/.git" ]; then git clone --depth 50 "$REPO" "$APP"; fi
cd "$APP"
python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

echo "__CONFIG_B64__" | base64 -d > answerrank.yml
echo "__KEYS_B64__" | base64 -d > keys.env
mkdir -p data backups
chown -R answerrank:answerrank "$APP"
chmod 600 keys.env

# The console login printed on your laptop when this file was made.
sudo -u answerrank .venv/bin/python run.py console-link --set "$TOKEN" \
    --base "https://$DOMAIN" > /root/answerrank-console-link.txt

cp deploy/answerrank-web.service deploy/answerrank-fleet.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now answerrank-web answerrank-fleet

cat > /etc/caddy/Caddyfile <<CADDY
$DOMAIN {
    reverse_proxy 127.0.0.1:8000
}
CADDY
systemctl reload caddy || systemctl restart caddy

ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

cat > /etc/cron.d/answerrank <<CRON
# Nightly database backup, 30 days kept.
0 3 * * * answerrank $APP/deploy/backup.sh >> /var/log/answerrank-backup.log 2>&1
# Daily update from GitHub, then restart. Same as start.bat on the laptop.
30 4 * * * root cd $APP && sudo -u answerrank git pull --quiet --ff-only && sudo -u answerrank .venv/bin/pip install --quiet -r requirements.txt && systemctl restart answerrank-web answerrank-fleet >> /var/log/answerrank-update.log 2>&1
CRON
chmod +x "$APP/deploy/backup.sh"

echo "AnswerRank is running on https://$DOMAIN"
