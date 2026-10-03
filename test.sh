#!/usr/bin/env bash
# Host checks: static checks, strict C99, and a bot that plays the whole game
# on a model of both PRG32 display back ends. With PRG32_REPO set, the source
# is also checked against the real public headers of that checkout.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
python3 "$HERE/tests/source_checks.py"
"$HERE/tests/host_syntax.sh"
"$HERE/tests/run_harness.sh"
ROOT="${PRG32_REPO:-${PRG32_ROOT:-}}"
if [[ -z "$ROOT" && -f "$HERE/../PRG32/components/prg32/include/prg32.h" ]]; then ROOT="$HERE/../PRG32"; fi
if [[ -n "$ROOT" ]]; then
  "${CC:-cc}" -std=c11 -Wall -Wextra -Werror \
    -I"$ROOT/components/prg32/include" -I"$ROOT/components/prg32_audio/include" \
    -I"$HERE" -fsyntax-only "$HERE/game.c"
  echo "OK: game.c matches the public headers of $ROOT"
fi
