#!/usr/bin/env bash
# Build Spiriti! Napoli '97: assets -> tests -> portable cartridge -> Store bundle.
#   PRG32_REPO=/path/to/PRG32 [CARTRIDGE_STORE_ROOT=/path/to/CartridgeStore] ./build.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${PRG32_REPO:-${PRG32_ROOT:-}}"
if [[ -z "$ROOT" && -d "$HERE/../PRG32/prg32" ]]; then ROOT="$(cd "$HERE/../PRG32" && pwd)"; fi
if [[ -z "$ROOT" || ! -f "$ROOT/tools/prg32audio_pack.py" ]]; then
  echo "Set PRG32_REPO to a checkout of https://github.com/riscv-prg32/PRG32 (main)" >&2
  exit 2
fi
# The RISC-V toolchain comes from ESP-IDF; use its install if not on PATH yet.
if ! command -v riscv32-esp-elf-gcc >/dev/null; then
  TC="$(ls -d "$HOME"/.espressif/tools/riscv32-esp-elf/*/riscv32-esp-elf/bin 2>/dev/null | tail -1 || true)"
  [[ -n "$TC" ]] && export PATH="$TC:$PATH"
fi
NAME=spiriti-napoli97
LIMIT=65536          # default PRG32 package limit (CONFIG_PRG32_CART_MAX_KIB=64)
python3 "$HERE/tools/generate_assets.py"
python3 "$HERE/tools/generate_audio.py"
"$HERE/test.sh"
VERSION="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["version"])' "$HERE/metadata.json")"
BUNDLE="$NAME-$VERSION-store.zip"
BUILD="$HERE/build"; DIST="$HERE/dist"; STORE="$DIST/store"
rm -rf "$BUILD" "$DIST"; mkdir -p "$BUILD" "$STORE"
cd "$ROOT"
python3 tools/prg32audio_pack.py "$HERE/audio.json" --out "$BUILD/spiriti-audio.block"
# 64 KiB of cartridge RAM is the default PRG32 profile on the ESP32-C6 and on QEMU.
python3 -m prg32 cartridge build "$HERE/game.c" --portable --cart-ram-kib 64 \
  --entry-prefix spiriti_napoli97 --name "$NAME" \
  --audio-block "$BUILD/spiriti-audio.block" --out "$BUILD/$NAME-base.prg32"
for arch in esp32c6 qemu; do
  python3 -m prg32 store attach-metadata "$BUILD/$NAME-base.prg32" --metadata "$HERE/metadata.json" \
    --icon "$HERE/icon.png" --screenshot "$HERE/screenshot.png" \
    --colophon "$HERE/colophon.json" --architecture "$arch" --out "$STORE/$NAME-$arch.prg32"
done
python3 "$HERE/tools/store_manifest.py" "$STORE/manifest.json"
cp "$HERE/icon.png" "$HERE/screenshot.png" "$STORE/"
python3 -m prg32 cartridge summary "$STORE/$NAME-esp32c6.prg32"
python3 -m prg32 store inspect-metadata "$STORE/$NAME-esp32c6.prg32" >/dev/null
python3 -m prg32 store pack-bundle --manifest "$STORE/manifest.json" --out "$DIST/$BUNDLE"
for f in "$STORE"/*.prg32; do
  size=$(wc -c < "$f"); echo "$(basename "$f"): $size / $LIMIT bytes"
  test "$size" -le "$LIMIT" || { echo "$f exceeds 64 KiB" >&2; exit 3; }
done
STORE_ROOT="${CARTRIDGE_STORE_ROOT:-}"
if [[ -z "$STORE_ROOT" && -d "$HERE/../CartridgeStore/cartridge_store" ]]; then STORE_ROOT="$HERE/../CartridgeStore"; fi
if [[ -n "$STORE_ROOT" ]]; then
  python3 "$HERE/tools/check_store_bundle.py" "$DIST/$BUNDLE" "$STORE_ROOT"
else
  echo "CARTRIDGE_STORE_ROOT not set: skipping Store intake check" >&2
fi
(cd "$DIST" && shasum -a 256 store/*.prg32 "$BUNDLE" > SHA256SUMS)
echo "Built portable cartridge and Store bundle: $DIST/$BUNDLE"
