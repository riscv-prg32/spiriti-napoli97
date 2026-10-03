# Spiriti! Napoli '97 — PRG32 cartridge

An unofficial **Ghostbusters-inspired tribute game** for [PRG32](https://github.com/riscv-prg32/PRG32) `main`, set in Naples in 1997. Code, pixel art and music are original: the game evokes the 1984 paranormal-comedy arcade tradition without shipping the protected logo, soundtrack, dialogue or sprites.

![Twelve screens of the game](release-artifacts/spiriti-napoli97-contact-sheet.png)

[A capture recorded from the QEMU firmware, with its soundtrack](preview.mp4).

## The night shift

1. **Dispatch map.** Six haunted districts around the Gulf of Naples. `LEFT`/`RIGHT` choose, `A` sends the Fiat out for 250K lire.
2. **Lungomare.** Three lanes along the bay. `UP`/`DOWN` change lane, `RIGHT`/`LEFT` accelerate and brake. Slime costs speed and feeds the city's psychokinetic (PK) energy; every espresso you pick up gives you more time at the capture.
3. **Capture.** Hold `A` to keep the spirit in the proton beam and move the trap under it with `LEFT`/`RIGHT`. The pack heats up while it fires: at the top it vents and the beam is off until it cools. If the spirit's patience runs out, or you press `B`, it escapes.
4. **Vesuvio.** With the six districts clear, the volcano wakes. The apparition takes three rounds, and firing through its lightning overheats the pack.

PK energy climbs all night and falls with every capture; it stains the sky green as it rises. The shift ends when Naples is safe, when the till cannot pay for another call-out, or when PK energy reaches 100. `SELECT` on the title shows the high scores.

## What it uses from PRG32

- **Indexed colours.** Everything is drawn with `prg32_sprite_draw_indexed` and `prg32_gfx_rect_indexed`. The ESP32-C6 framebuffer holds one byte per pixel and maps each RGB565 colour to a cell of a 6x6x6 cube; the cartridge programs each of its colours into its cell with `prg32_palette_set`, so the board shows the authored colours, the same as QEMU. See [docs/ASSET_PIPELINE.md](docs/ASSET_PIPELINE.md).
- **Palette effects.** Fades between screens, the capture flash, spirits that glow along their own colour ramp, the cycling proton beam, twinkling stars, the trap's light cone, the selection ring, lightning, the PK-stained sky and the dawn of the ending.
- **SID-like stereo audio.** Ten procedural instruments and eight original tracker tracks in a PCM-free AUDIO block. Music plays on voices 0-3; the beam, siren, engine and other effects use voices 4-7 and are panned by screen position.
- **Portable ABI build**, scoreboard, bounded random numbers.

[INTEGRATION.md](INTEGRATION.md) lists the calls and the firmware behaviour the cartridge relies on.

## Build

Needs a checkout of `riscv-prg32/PRG32` `main`, the ESP-IDF RISC-V toolchain, and Python with Pillow and NumPy.

```sh
export PRG32_REPO=/path/to/PRG32
./build.sh
```

`build.sh` regenerates the art and the score, runs the tests, builds the portable cartridge, attaches the Store metadata for `esp32c6` and `qemu`, packs the bundle and, when a `CartridgeStore` checkout is next to this one (or `CARTRIDGE_STORE_ROOT` is set), validates it with the Store's own intake code.

```text
dist/store/spiriti-napoli97-esp32c6.prg32
dist/store/spiriti-napoli97-qemu.prg32
dist/spiriti-napoli97-2.0.0-store.zip
```

The cartridge needs 38.8 KiB of cartridge RAM: it runs on the default 64 KiB profile of the ESP32-C6 and QEMU firmware, not on the 32 KiB classroom profile.

## Test

```sh
./test.sh
```

- `tests/source_checks.py`: static checks, including that colours shown together never share a palette cell.
- `tests/host_syntax.sh`: strict C99.
- `tests/run_harness.sh`: a bot plays the whole night on a software model of both display back ends and fails on any pixel that differs between QEMU and the ESP32-C6, then exercises the failure paths.

`make screens` renders the harness frames in `release-artifacts/screens/`. `make capture` runs the cartridge in the QEMU firmware and records `preview.mp4` and the Store screenshot. [VALIDATION.md](VALIDATION.md) says what has been verified and what has not.

## Tribute / rights notice

**Spiriti! Napoli '97 is a tribute game.** It is unofficial, non-commercial in intent, and not affiliated with, endorsed by, or sponsored by the Ghostbusters rights holders. Ghostbusters is mentioned only to identify the cultural work being paid tribute to. The project contains original title treatment, pixel artwork, music, sound design and code. Trademarks and third-party rights remain with their respective owners.
