#!/usr/bin/env bash
# Boot the Perjuangan Semut client against the localhost emulator.
# 1) starts emulator.py (HTTP :8080, GAME :9001, BATTLE :9002) if not running
# 2) launches the patched SWF via the AIR debug launcher (adl)
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SDK="$HERE/sdk/AIRSDK51"
ADL="$SDK/bin/adl"
RUNTIME="$SDK/runtimes/air/mac"

# emulator already up?
if ! curl -s --max-time 2 "http://127.0.0.1:8080/antwarsmobile/version/facebookid/ChangerLog.xml" >/dev/null 2>&1; then
  echo "[run] starting emulator..."
  python3 "$HERE/emulator.py" > "$HERE/emu.log" 2>&1 &
  EMUPID=$!
  for i in $(seq 1 30); do
    curl -s --max-time 2 "http://127.0.0.1:8080/antwarsmobile/version/facebookid/ChangerLog.xml" >/dev/null 2>&1 && break
    sleep 0.3
  done
  echo "[run] emulator pid $EMUPID (log: $HERE/emu.log)"
else
  echo "[run] emulator already running"
fi

if [ ! -x "$ADL" ]; then
  echo "[run] ERROR: adl not found at $ADL — extract the AIR SDK first."
  exit 1
fi

# seed the login SharedObject (same app id + swf name => same store). Writes
# Antwars/LoginData {sid:"seed_auto_login",method:1} then exits (~2s). The
# patched LoginData.init reads it even with debug=false => auto-login, no click.
# Idempotent; run every launch so a fresh machine always auto-logs in.
"$ADL" -runtime "$RUNTIME" -profile desktop "$HERE/seed/app.xml" >/dev/null 2>&1

cd "$HERE/runtime"
exec "$ADL" -runtime "$RUNTIME" -profile desktop "$HERE/runtime/app.xml"