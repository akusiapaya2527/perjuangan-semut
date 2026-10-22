#!/usr/bin/env bash
# Patch SWF client agar base URL HTTP menunjuk ke domain publik,
# menggantikan http://127.0.0.1:8080/antwarsmobile/ bawaan spike lokal.
#
# Cara kerja (meniru rebuild_ruffle.sh pemilik repo, versi Linux):
#   1. Export skrip dari SWF spike (emulator/spike-ruf) memakai FFDec.
#   2. Ubah SATU baris di Constants.as (getter IpAddress, cabang isLocal).
#   3. Import kembali hanya file itu ke SWF -> web/antwarsmobilestarling.swf.
# Alamat socket game TIDAK diubah: emulator memang menyuruh client connect
# ke 127.0.0.1:9001-9003 dan Ruffle socketProxy di web/index.html
# mencegatnya lalu meneruskan via wss ke ws_bridge.
#
# Prasyarat: Java 17+ dan FFDec (ffdec-cli.jar). Atur lewat env:
#   FFDEC_JAR=/path/ffdec-cli.jar  PUBLIC_BASE=https://perjuangansemut.akusiapaya.web.id/antwarsmobile/
set -euo pipefail

PUBLIC_BASE="${PUBLIC_BASE:-https://perjuangansemut.akusiapaya.web.id/antwarsmobile/}"
FFDEC_JAR="${FFDEC_JAR:?set FFDEC_JAR ke lokasi ffdec-cli.jar}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC_SWF="$ROOT/emulator/spike-ruf/antwarsmobilestarling.swf"
WORK="$(mktemp -d)"

java -jar "$FFDEC_JAR" -export script "$WORK/export" "$SRC_SWF"
mkdir -p "$WORK/import_src"
cp "$WORK/export/scripts/Constants.as" "$WORK/import_src/Constants.as"
sed -i "s|http://127.0.0.1:8080/antwarsmobile/|$PUBLIC_BASE|" "$WORK/import_src/Constants.as"
grep -q "$PUBLIC_BASE" "$WORK/import_src/Constants.as"

java -jar "$FFDEC_JAR" -importScript "$SRC_SWF" "$WORK/antwars_online.swf" "$WORK/import_src"
cp "$WORK/antwars_online.swf" "$ROOT/web/antwarsmobilestarling.swf"
cp "$WORK/import_src/Constants.as" "$ROOT/deploy/swf-src/Constants.as"
echo "OK: web/antwarsmobilestarling.swf sekarang memakai base $PUBLIC_BASE"
