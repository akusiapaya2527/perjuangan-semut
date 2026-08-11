#!/bin/zsh
# Rebuild Ruffle-patched SWF from /tmp/rufpatch/import_src onto pristine runtime SWF.
# Usage: ./rebuild_ruffle.sh   (edits emulator/runtime + spike-ruf in place)
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/emulator/runtime/antwarsmobilestarling.swf"
OUT="/tmp/rufpatch/swf/ruf_runtime3.swf"
FFDEC="/Applications/FFDec.app/Contents/Resources/ffdec-cli.jar"
IMPORTSRC="/tmp/rufpatch/import_src"

[ -f "$FFDEC" ] || { echo "ffdec-cli.jar not found"; exit 1; }
[ -d "$IMPORTSRC" ] || { echo "import_src missing: $IMPORTSRC"; exit 1; }

rm -f "$OUT"
java -jar "$FFDEC" -importScript "$SRC" "$OUT" "$IMPORTSRC"
cp "$OUT" "$ROOT/emulator/runtime/antwarsmobilestarling.swf"
cp "$OUT" "$ROOT/emulator/spike-ruf/antwarsmobilestarling.swf"
echo "deployed to emulator/runtime + spike-ruf: $OUT"
