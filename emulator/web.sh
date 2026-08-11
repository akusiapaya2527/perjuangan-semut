#!/usr/bin/env bash
# Play Perjuangan Semut in a browser tab.
# Streams the ADL game window (ScreenCaptureKit) over MJPEG and relays
# pointer/keyboard input back to the game (CGEvent). The game client keeps
# running under AIR/ADL — nothing about the SWF changes.
#
# First run requires two macOS permissions for your terminal app:
#   System Settings > Privacy & Security > Screen Recording   (else black stream)
#   System Settings > Privacy & Security > Accessibility      (else clicks ignored)
# After granting, restart the terminal and run this again.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SDK="$HERE/sdk/AIRSDK51"
ADL="$SDK/bin/adl"
RUNTIME="$SDK/runtimes/air/mac"
BRIDGE="$HERE/bridge/streamer"
SRC="$HERE/bridge/streamer.swift"
PORT="${WEBBRIDGE_HTTP:-8095}"
FRAME_PORT="${WEBBRIDGE_VIDEO:-8096}"
INPUT_PORT="${WEBBRIDGE_INPUT:-8097}"

# 1) build the bridge if missing or stale
if [ ! -x "$BRIDGE" ] || [ "$SRC" -nt "$BRIDGE" ]; then
  echo "[web] building streamer bridge..."
  bash "$HERE/bridge/build.sh" || { echo "[web] build failed"; exit 1; }
fi

# 2) emulator up?
if ! curl -s --max-time 2 "http://127.0.0.1:8080/antwarsmobile/version/facebookid/ChangerLog.xml" >/dev/null 2>&1; then
  echo "[web] starting emulator..."
  python3 "$HERE/emulator.py" > "$HERE/emu.log" 2>&1 &
  for _ in $(seq 1 30); do
    curl -s --max-time 2 "http://127.0.0.1:8080/antwarsmobile/version/facebookid/ChangerLog.xml" >/dev/null 2>&1 && break
    sleep 0.3
  done
fi

# 3) game client running?
CLIENT_PID="$(pgrep -f 'adl.*runtime/app.xml' | head -1 || true)"
if [ -n "$CLIENT_PID" ]; then
  echo "[web] client already running (pid $CLIENT_PID)"
else
  echo "[web] launching client (seed + main)..."
  "$ADL" -runtime "$RUNTIME" -profile desktop "$HERE/seed/app.xml" >/dev/null 2>&1
  ( cd "$HERE/runtime" && exec "$ADL" -runtime "$RUNTIME" -profile desktop "$HERE/runtime/app.xml" ) \
    > "$HERE/adl.log" 2>&1 &
  CLIENT_PID=$!
  echo "[web] client pid $CLIENT_PID"
fi

# 4) webbridge up?
if ! curl -s --max-time 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
  echo "[web] starting webbridge..."
  python3 "$HERE/webbridge.py" > "$HERE/web.log" 2>&1 &
fi

# 5) streamer (capture + input)
"$BRIDGE" "$CLIENT_PID" "$FRAME_PORT" "$INPUT_PORT" > "$HERE/streamer.log" 2>&1 &
STREAMER_PID=$!
trap 'kill "$STREAMER_PID" 2>/dev/null' EXIT

for _ in $(seq 1 20); do
  grep -q "capture started" "$HERE/streamer.log" 2>/dev/null && break
  sleep 0.5
done

if grep -q "capture started" "$HERE/streamer.log" 2>/dev/null; then
  echo "[web] stream live at http://127.0.0.1:$PORT"
  open "http://127.0.0.1:$PORT"
else
  echo "[web] streamer did not start — check $HERE/streamer.log:"
  tail -5 "$HERE/streamer.log"
  echo "[web] tip: grant Screen Recording + Accessibility to your terminal, restart it, re-run."
fi

echo "[web] streaming (Ctrl-C to stop streaming; game client stays running)."
wait "$STREAMER_PID"
