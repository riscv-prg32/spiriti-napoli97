# Validation status — 2.0.0

## Verified

- `./test.sh`: static checks, strict C99, and the host harness. A bot plays all seven jobs to the good ending in 5499 frames; the ESP32-C6 and QEMU display models show identical pixels in every frame without a fade or flash; overheating, an escaped spirit, giving up, the empty till, PK overload, slime, espresso, lane changes, a press between steps and slow frames are each asserted. At most 203 sprite and 283 primitive draws per frame.
- The source compiles against the public headers of PRG32 `main` at `a8669e5`.
- `./build.sh` against that commit: 38348 bytes of code, 38800 bytes of memory, 4264 bytes of audio; each Store cartridge is 55794 bytes of the 65536 allowed.
- The Cartridge Store's intake code (`_prepare_bundle`) accepts `dist/spiriti-napoli97-2.0.0-store.zip` and rebuilds both architectures.
- QEMU: the firmware loads the cartridge from `cart0`; title, map, drive, capture, result and the return to the map were played through the UART keyboard, the capture by a bot that reads the picture. `preview.mp4` (27 s, 640x400 H.264, 22050 Hz mono AAC) and `screenshot.png` come from that run; the soundtrack is audible throughout and does not clip. The QEMU frames were compared by eye with the harness renders of the same screens.
- `tools/generate_assets.py` and `tools/generate_audio.py` reproduce `assets.h` and `audio.json` byte for byte.

## Not verified

- **Physical ESP32-C6.** Colours, frame rate and stereo panning on two MAX98357A boards have not been checked on hardware. The colour match with QEMU is established on a model of the firmware's palette code, not on the panel. Every frame redraws the whole screen, so the frame rate is bounded by the full-screen SPI transfer; the game logic keeps its pace regardless.
- QEMU's audio is mono, so stereo panning was exercised only in the harness.
- In QEMU only the first job was played; the other districts and the endings were played in the harness.

## Note on the QEMU firmware build

PRG32 `main` at `a8669e5` did not build for QEMU with ESP-IDF v5.4: `components/prg32` includes `esp_crt_bundle.h` without requiring `mbedtls`. The test firmware was built from a scratch copy with `mbedtls` added to the component's `PRIV_REQUIRES`. The cartridge itself is built with the unmodified tools.

## Reproduce

```sh
export PRG32_REPO=/path/to/PRG32
./build.sh
(cd "$PRG32_REPO" && python3 -m prg32 qemu build)
python3 tools/qemu_capture.py
./build.sh          # embeds the new screenshot
```
