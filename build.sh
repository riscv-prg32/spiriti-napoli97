#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${PRG32_REPO:-"$HERE/../PRG32"}"
if [ ! -f "$ROOT/tools/prg32audio_pack.py" ]; then
  echo "Set PRG32_REPO to a current PRG32 main checkout." >&2; exit 2
fi
BUILD="$HERE/build"; DIST="$HERE/dist"; STORE="$DIST/store"
mkdir -p "$BUILD" "$STORE"
cd "$ROOT"
python3 tools/prg32audio_pack.py "$HERE/audio.json" --out "$BUILD/spiriti-audio.block"
for arch in esp32c6 qemu; do
  python3 -m prg32 cartridge build "$HERE/game.c" \
    --portable --entry-prefix spiriti_napoli97 --name spiriti-napoli97 \
    --architecture "$arch" --audio-block "$BUILD/spiriti-audio.block" \
    --out "$BUILD/spiriti-$arch.raw.prg32"
  python3 -m prg32 store attach-metadata "$BUILD/spiriti-$arch.raw.prg32" \
    --metadata "$HERE/metadata.json" --icon "$HERE/icon.png" \
    --screenshot "$HERE/screenshot.png" --colophon "$HERE/colophon.json" \
    --architecture "$arch" --out "$STORE/spiriti-napoli97-$arch.prg32"
done
cp "$HERE/manifest.json" "$HERE/icon.png" "$HERE/screenshot.png" "$HERE/colophon.json" "$STORE/"
python3 -m prg32 cartridge summary "$STORE/spiriti-napoli97-esp32c6.prg32"
python3 -m prg32 store inspect-metadata "$STORE/spiriti-napoli97-esp32c6.prg32"
python3 -m prg32 store pack-bundle --manifest "$STORE/manifest.json" --out "$DIST/spiriti-napoli97-1.2.3-store.zip"
echo "Built store-ready ESP32-C6 and QEMU variants in $STORE"
