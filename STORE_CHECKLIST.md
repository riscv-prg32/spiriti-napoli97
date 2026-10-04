# Cartridge Store release checklist — 3.0.0

- [x] `make assets` regenerates `assets.h` and `audio.json` with no diff.
- [x] `./test.sh` passes (static checks, strict C99, bot playthrough on both display models).
- [x] `./build.sh` against `riscv-prg32/PRG32` `main` (commit `a8669e5`).
- [x] Both `.prg32` files are within 65536 bytes (59514).
- [x] Manifest is `prg32-metadata-1.0`; versions agree in metadata, colophon and changelog.
- [x] The Cartridge Store intake code accepts the bundle.
- [x] Colophon and metadata identify the cartridge as an unofficial tribute.
- [x] QEMU: played from the title to the parade, with music and effects (`make capture`).
- [x] Store screenshot and `preview.mp4` are real QEMU captures.
- [ ] ESP32-C6: colours match QEMU, frame rate in front of the landmarks is acceptable, stereo panning on two MAX98357A boards.
- [ ] Publish `dist/spiriti-napoli97-3.0.0-store.zip` to the Cartridge Store.
- [ ] Tag the version after the hardware run.
