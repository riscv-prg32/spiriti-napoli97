# Spiriti! Napoli '97 — PRG32 cartridge

An unofficial **Ghostbusters-inspired tribute game** for PRG32 `development-c6`, intended for publication under the `riscv-prg32` GitHub organization. The game is set in Naples in 1997 and uses original cartridge code, graphics and SID-like music. Its visual/audio language deliberately evokes the 1984 paranormal-comedy arcade tradition without shipping the protected Ghostbusters logo, soundtrack melody/recording, dialogue, film/game sprites, or other copied franchise assets.

[Download the 30-second MP4 captured from the actual QEMU playfield and UART soundtrack](preview.mp4).

## Gameplay

The night shift alternates between a tiled Naples dispatch map, a driving sequence in a modified classic Fiat 500-style response car, and a spirit-capture encounter. Calls appear around Centro Storico, Mergellina, Vomero, Porto, Fuorigrotta and Capodimonte. Dispatches cost money; ectoplasm raises city paranormal energy; successful captures earn cash and score. The Capodimonte call escalates to a large Vesuvius apparition.

## Graphics architecture — 1.2.3

This release replaces the earlier placeholder-style rectangles/sprites with runtime graphics derived from the project's high-quality visual direction:

- **PRG32 tile/playfield backgrounds:** Naples map and district scenery are rendered through reusable 8x8 tiles on the 64x32 playfield rather than embedded full-screen bitmaps.
- **Scrollable scenery:** 40x18 source scenes repeat across the wider playfield, enabling camera offsets and the driving sequence without duplicate full-screen images.
- **Compact 4-bpp sprites:** the classic Fiat 500-style response car, hunter, six spectral forms, Vesuvius boss, trap, slime, street lamps and palms use packed indexed artwork with carefully quantized 16-colour palettes.
- **Pointer-free portable data:** sprite descriptors are assembled on the stack. Static cartridge data contains raw pixels, palettes, tiles and maps rather than initialized pointers to other cartridge objects.
- **Verified previews:** `actual-assets-sheet.png` and `actual-tile-scenes.png` are generated from runtime data; `screenshot.png` is extracted from the real QEMU recording.

The generated graphics and executable fit PRG32's strict 32 KiB runtime slot. The complete Store bundle, including both architecture packages and media metadata, also remains below the 128 KiB distribution ceiling.

## PRG32 features

- Portable ABI-table build using `--portable`.
- 320x200 viewport.
- 40x25 simple tile API / 64x32 scrolling playfield rendering.
- 4-bpp indexed sprites for a balanced visual and memory footprint.
- Descriptor-only `AUD0` block with original 1980s supernatural-comedy SID-like procedural instruments and tracker music.
- Stereo pan effects on PRG32 Audio Plus and mono-safe fallback.
- Scoreboard support and Store metadata/colophon.
- Store manifest declares both `esp32c6` and `qemu`.

## Regenerating graphics

The checked-in `assets-src/` directory contains the cropped original project artwork used to generate the cartridge graphics. `assets.h` is already generated and is sufficient for normal builds. To regenerate it and the previews:

```sh
python3 -m pip install pillow numpy
./tools/generate_assets.py
```

The generator converts hero/vehicle/enemy art to packed 4-bpp data and reduces background artwork to coherent scene-local 24-colour 8x8 tile dictionaries compatible with PRG32's tile API. The deliberately chunky backgrounds keep moving sprites readable, avoid noisy tile-remapping artifacts, and leave high IDs available for runtime road/cobblestone overlays.

## Build

Use a checkout of `riscv-prg32/PRG32` on branch `development-c6`:

```sh
export PRG32_REPO=/path/to/PRG32
./build.sh
```

Expected outputs:

```text
dist/store/spiriti-napoli97-esp32c6.prg32
dist/store/spiriti-napoli97-qemu.prg32
dist/spiriti-napoli97-1.2.3-store.zip
```

The same portable executable payload is intended to run through the ABI table on physical ESP32-C6 hardware and the ESP32-C3 QEMU firmware path. Store metadata is attached for both architecture entries.

## Validation

`./test.sh` runs strict host C syntax validation and parses all JSON metadata. The graphics generator is deterministic for the checked-in sources. The official PRG32 portable build and package-size checks are documented in `VALIDATION.md`; physical ESP32-C6 testing remains a release step.

## Recording the preview

Build the Store packages first, then record the real QEMU framebuffer and UART PCM soundtrack:

```sh
export PRG32_REPO=/path/to/PRG32
./tools/capture_preview.py
```

The resulting `preview.mp4` is 320x200 H.264 video with AAC audio, runs for 30 seconds, and is repository publishing media rather than part of the size-limited Store bundle. The recorder also extracts an actual beam-action frame to `screenshot.png`; run `./build.sh` again afterward to embed that screenshot in both Store cartridges.

## Tribute / rights notice

**Spiriti! Napoli '97 is a tribute game.** It is unofficial, non-commercial in intent, and not affiliated with, endorsed by, or sponsored by the Ghostbusters rights holders. Ghostbusters is mentioned only to identify the cultural work being paid tribute to. Recognition comes from broad paranormal-response and 1980s arcade cues, not reproduction of protected assets. The project contains original title treatment, pixel artwork, music, sound design and code. Trademarks and third-party rights remain with their respective owners.
