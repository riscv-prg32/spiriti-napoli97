#!/usr/bin/env bash
# Strict host compile of the cartridge source against the small API stub.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
CC="${CC:-cc}"
"$CC" -std=c99 -Wall -Wextra -Werror -pedantic -fsyntax-only -I"$HERE/stub" -I"$HERE/.." "$HERE/../game.c"
echo "OK: game.c is clean C99"
