#!/usr/bin/env bash
# Instalasi Perjuangan Semut di VPS (Ubuntu, user ubuntu + sudo).
# Dijalankan dari clone repo ini di server. Idempoten sebisanya:
# aman dijalankan ulang untuk update (git pull + restart service).
set -euo pipefail

APP_ROOT=/opt/perjuangansemut
WWW_ROOT=/var/www/perjuangansemut
REPO_URL=https://github.com/akusiapaya2527/perjuangan-semut.git
BRANCH=deploy-vps

echo "== 1. Kode aplikasi -> $APP_ROOT/app =="
if [ -d "$APP_ROOT/app/.git" ]; then
  git -C "$APP_ROOT/app" pull --ff-only
else
  sudo mkdir -p "$APP_ROOT"
  sudo chown "$(whoami)" "$APP_ROOT"
  git clone --branch "$BRANCH" "$REPO_URL" "$APP_ROOT/app"
fi

echo "== 2. Virtualenv + dependensi (websockets untuk ws_bridge) =="
python3 -m venv "$APP_ROOT/.venv"
"$APP_ROOT/.venv/bin/pip" install -q websockets

echo "== 3. File env (rahasia, di luar git) =="
if [ ! -f "$APP_ROOT/perjuangansemut.env" ]; then
  cp "$APP_ROOT/app/deploy/perjuangansemut.env.example" "$APP_ROOT/perjuangansemut.env"
  chmod 600 "$APP_ROOT/perjuangansemut.env"
  echo "PERHATIAN: isi ADMIN_EMAIL/ADMIN_PASSWORD di $APP_ROOT/perjuangansemut.env dulu!"
fi

echo "== 4. Unit systemd =="
sudo cp "$APP_ROOT/app/deploy/perjuangansemut-emulator.service" /etc/systemd/system/
sudo cp "$APP_ROOT/app/deploy/perjuangansemut-bridge.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now perjuangansemut-emulator perjuangansemut-bridge

echo "== 5. Front-end statis -> $WWW_ROOT =="
sudo mkdir -p "$WWW_ROOT"
sudo cp -r "$APP_ROOT/app/web/." "$WWW_ROOT/"
sudo chown -R www-data:www-data "$WWW_ROOT" 2>/dev/null || sudo chown -R caddy:caddy "$WWW_ROOT"

echo "== 6. Caddy =="
echo "Tempel deploy/Caddyfile.snippet ke /etc/caddy/Caddyfile bila belum ada blok"
echo "perjuangansemut.akusiapaya.web.id, lalu:"
echo "  sudo caddy validate --config /etc/caddy/Caddyfile"
echo "  sudo systemctl reload caddy"

echo "Selesai. Cek: systemctl status perjuangansemut-emulator perjuangansemut-bridge"
