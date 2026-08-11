#!/usr/bin/env bash
# Compile the ScreenCaptureKit window-streamer bridge.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
swiftc -O -parse-as-library -swift-version 5 \
  -framework ScreenCaptureKit \
  -framework CoreMedia -framework CoreVideo -framework CoreImage \
  -framework CoreGraphics -framework ImageIO -framework ApplicationServices \
  "$HERE/streamer.swift" -o "$HERE/streamer"
echo "built $HERE/streamer"
