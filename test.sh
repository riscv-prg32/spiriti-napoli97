#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
clang -std=c11 -Wall -Wextra -Werror -I"$HERE/tests/stub" -I"$HERE" -fsyntax-only "$HERE/game.c"
python3 -m json.tool "$HERE/audio.json" >/dev/null
python3 -m json.tool "$HERE/metadata.json" >/dev/null
python3 -m json.tool "$HERE/manifest.json" >/dev/null
python3 -m json.tool "$HERE/colophon.json" >/dev/null
echo "Host syntax and JSON validation passed."
