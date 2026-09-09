# Validation status — 1.2.0

## Completed in this package

- Strict host C syntax check (`clang -std=c11 -Wall -Wextra -Werror`) against the cartridge API stub.
- JSON validation for `audio.json`, `metadata.json`, `manifest.json`, and `colophon.json`.
- Deterministic regeneration of `assets.h` from checked-in `assets-src/` PNGs.
- Official portable cartridge build: 26,216 bytes of code and 26,320 bytes of runtime memory, within the 32 KiB runtime slot.
- Complete two-architecture Store bundle: approximately 113.0 KiB, within the 128 KiB distribution ceiling.
- 4-bpp indexed generation for the Fiat, hunter, six ghosts, boss and repeated props.
- Coherent 24-colour tile-engine generation for the Naples overview map and five district background families.
- Portable-code review: no hard-coded firmware addresses and no global/static sprite descriptor containing pointers to other cartridge objects.
- Metadata declares `esp32c6` and `qemu` Store architectures.
- Music/SFX are procedural SID-like descriptors; no copyrighted recording or Ghostbusters soundtrack melody is bundled.

## Completed with PRG32 `development-c6`

The official compiler and packer produced both `esp32c6` and `qemu` packages, inspected their metadata, and packed the Store bundle. QEMU smoke-test results are recorded below. Physical ESP32-C6 hardware validation remains required before publication.

The QEMU firmware booted, initialized its 320x240 framebuffer and audio stream, and autoloaded the cartridge from `cart0`. The runtime reported the expected 26,216-byte code, 26,320-byte memory and 2,904-byte audio sizes. Injected title/game controls produced no panic or runtime fault during the smoke window.

From a current `development-c6` checkout:

```sh
source "$HOME/esp-idf/export.sh"
cd /path/to/PRG32
python3 -m prg32 doctor
cd cartridges/spiriti-napoli97
./build.sh
```

Reproduce the package checks with:

```sh
python3 -m prg32 cartridge summary dist/store/spiriti-napoli97-esp32c6.prg32
python3 -m prg32 store inspect-metadata dist/store/spiriti-napoli97-esp32c6.prg32
python3 -m prg32 cartridge summary dist/store/spiriti-napoli97-qemu.prg32
cd "$PRG32_REPO"
python3 -m prg32 qemu upload ../spiriti-napoli97/dist/store/spiriti-napoli97-qemu.prg32
python3 -m prg32 qemu run
```

On physical ESP32-C6, exercise title -> tile map -> driving -> capture -> result -> map, all six districts, the boss, scoreboard, mono/stereo audio fallback, abort/restart, and prolonged beam/drive rendering.
