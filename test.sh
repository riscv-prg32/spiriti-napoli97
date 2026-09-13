#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${PRG32_REPO:-"$HERE/../PRG32"}"
if [ ! -f "$ROOT/components/prg32/include/prg32.h" ]; then
  echo "Set PRG32_REPO to a current PRG32 main checkout." >&2; exit 2
fi
clang -std=c11 -Wall -Wextra -Werror \
  -I"$ROOT/components/prg32/include" \
  -I"$ROOT/components/prg32_audio/include" \
  -I"$HERE" -fsyntax-only "$HERE/game.c"
python3 -m json.tool "$HERE/audio.json" >/dev/null
python3 -m json.tool "$HERE/metadata.json" >/dev/null
python3 -m json.tool "$HERE/manifest.json" >/dev/null
python3 -m json.tool "$HERE/colophon.json" >/dev/null
echo "Current PRG32 public-header syntax and JSON validation passed."
