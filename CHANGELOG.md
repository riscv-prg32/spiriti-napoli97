# Changelog

## 2.0.0 — 2026-10-04 — indexed colours, palette effects, SID-like stereo

### Fixed

- The music was written for an older tracker in which `delta` came before an event; on current firmware `delta` is the wait after it, so chords were split and notes were cut in the tick they started. The score is rewritten and generated for delta-after timing.
- Effect notes were cut by a blanket note-off every 16 frames, whenever they had started. Each effect now has its own length, and held ones (beam, engine) are released when they end.
- Colours on the ESP32-C6 were quantised to the firmware's 216-colour cube. The cartridge now programs the system palette, so the board shows the authored colours.
- The backgrounds went through the tile engine, which fills every tile with RGB565 rectangles quantised pixel by pixel on the board. The districts are now drawn with indexed sprites.
- The drive could not be played: slime crossed the car's only row, so it could not be avoided. The road has three lanes.
- The drive background jumped every 64 frames, because the scroll wrapped at a width the scenery did not repeat on.
- The beam always reached the spirit wherever the trap was, the spirit's height was a new random number every frame, and an overheated pack lost the job at once. The capture is redesigned.
- The title line was 42 characters wide on a 40-column screen, and the status band text was longer than the band.
- A sixth spirit was converted and stored but never used; each district now has its own.
- The Store bundle manifest declared `prg32-bundle-1.0`, which the Cartridge Store rejects. The manifest is generated in the `prg32-metadata-1.0` form the Store rebuilds cartridges from.
- A button pressed between two simulation steps could be lost.

### New

- Seven districts built from a bank of 49 16x16 tiles drawn by `tools/generate_assets.py`, each with its own 16-colour palette: Centro Storico, Mergellina, Vomero, Porto, Fuorigrotta, Capodimonte and the crater of the Vesuvius.
- A dispatch map of the Gulf of Naples, PK energy that climbs through the night, three endings, espresso pick-ups, a three-round final apparition with lightning.
- Palette effects: fades, capture flash, glowing spirits, cycling beam, trap light cone, twinkling stars, PK-stained sky, dawn.
- Row parallax along the lungomare, screen shake.
- Ten SID-like instruments and eight original tracks (`tools/generate_audio.py`); effects panned by screen position.
- Fixed 33 ms simulation steps, so the pace holds when the board draws slower than 30 fps.
- Host harness: a bot plays the whole game on a model of both display back ends and fails on any differing pixel.
- `tools/qemu_capture.py` records the cartridge in the QEMU firmware, playing the capture from the picture.
- The Store bundle is in `dist/` and is checked with the Cartridge Store's intake code.

### Changed

- Needs 38.8 KiB of cartridge RAM (the default profile is 64 KiB); 1.x fitted the 32 KiB profile.
- `manifest.json`, `actual-*.png` and `tools/capture_preview.py` are replaced by generated files and the tools above.

## 1.2.3 — 2026-09-09

- Tile-engine backgrounds, 4-bpp sprites, portable build for `esp32c6` and `qemu`.
