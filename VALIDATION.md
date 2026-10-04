# Validation status — 3.0.0

## Verified

- `./test.sh`: static checks, strict C99, and the host harness. A bot plays the whole night to the parade in 7049 frames: six districts, Villa Doria d'Angri, the omen, the run to the piazza, the giant, the ending. The ESP32-C6 and QEMU display models show identical pixels in every frame without a fade or flash. The rules are asserted one by one: venting, an escaped spirit, giving up, the empty till, PK overload, cleaning and missing puddles, espresso, a spirit sliming the car and missing it, lane changes, the guardian's fire, a lost villa fight called again from the map, the trap opened on an unbound giant and on a bound one, a press between steps, slow frames, and that the tempo moves.
- The source compiles against the public headers of PRG32 `main` at `a8669e5`.
- `./build.sh` against that commit: 45980 bytes of code, 46556 bytes of memory, 5272 bytes of audio; each Store cartridge is 59514 bytes of the 65536 allowed.
- The Cartridge Store's intake code (`_prepare_bundle`) accepts `dist/spiriti-napoli97-3.0.0-store.zip` and rebuilds both architectures.
- QEMU: `tools/qemu_capture.py` played the cartridge in the firmware from the title to the parade by looking at the frames; `release-artifacts/qemu/playthrough.txt` is the sequence of screens it saw. It lost the first fight in the piazza, was sent back to the map, drove there again and won. `preview.mp4` (160 s, 640x400 H.264, 22050 Hz mono AAC), `screenshot.png` and the frames in `release-artifacts/qemu/` come from that run; the soundtrack is audible throughout and does not clip.
- `tools/generate_assets.py` and `tools/generate_audio.py` reproduce `assets.h` and `audio.json` byte for byte.

## Not verified

- **Physical ESP32-C6.** Colours, frame rate and stereo panning on two MAX98357A boards have not been checked on hardware. The colour match with QEMU is established on a model of the firmware's palette code, not on the panel.
- **Frame rate on the board.** A landmark is drawn as up to about 2500 indexed rectangles per frame (the villa photograph is the largest), on top of the full-screen transfer every frame. This was not measured. The game logic keeps its pace in 33 ms steps whatever the frame rate, but the picture may be slow.
- QEMU's audio is mono, so stereo panning was exercised only in the harness. How the tempo changes sound was not judged by ear.

## Notes

- An earlier QEMU run froze 14 s in. The cause was the capture tool, not the cartridge: its audio socket had a 1 s timeout, a busy host stalled it, the tool stopped granting audio credits and the firmware waited for them. The socket no longer times out.
- PRG32 `main` at `a8669e5` did not build for QEMU with ESP-IDF v5.4: `components/prg32` includes `esp_crt_bundle.h` without requiring `mbedtls`. The test firmware was built from a scratch copy with `mbedtls` added to the component's `PRIV_REQUIRES`. The cartridge itself is built with the unmodified tools.

## Reproduce

```sh
export PRG32_REPO=/path/to/PRG32
./build.sh
(cd "$PRG32_REPO" && python3 -m prg32 qemu build)
python3 tools/qemu_capture.py
./build.sh          # embeds the new screenshot
```
