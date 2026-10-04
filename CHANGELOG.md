# Changelog

## 3.0.0 — 2026-10-04 — Naples landmarks, Villa Doria d'Angri, the giant Pulcinella

### New

- **The drive.** Slime on the road is now cleaned by driving over it; spirits fly in over a lane, with a shadow on the road, and slime the car if it is under them. Puddles left behind and slime on the car raise the PK energy.
- **Landmarks.** Each capture is fought in front of a Naples landmark: the Gesù Nuovo and the Guglia dell'Immacolata, Castel dell'Ovo and the Vesuvius, Castel Sant'Elmo and the Certosa di San Martino, the Maschio Angioino, the stadium at Fuorigrotta, the Reggia di Capodimonte.
- **Villa Doria d'Angri.** The final call replaces the crater of the Vesuvius. The background is converted from a photograph of the villa. The guardian cannot be trapped: the hunter now moves, wears it down with the pack and dodges the fire it throws.
- **"Scegli la forma del distruttore."** After the guardian, the message, then a giant evil Pulcinella rising over Piazza del Plebiscito.
- **The run to the piazza** with a giant trap on the Fiat's roof, and **the fight in Piazza del Plebiscito**: rays from the car bind the giant, `B` opens the trap when he is bound and the car is under him, three times.
- **The parade** on the lungomare: confetti, fireworks, dawn.
- **Soundtrack.** Ten tracks: new ones for the omen, the giant (a dark tarantella) and the parade. The game sets the tracker's tempo while a track plays, so the music follows the car's speed, a spirit's patience and the rounds against the giant.
- **Pictures.** Landmarks, the giant, the map, the logo and the far Vesuvius are stored as bands of runs and drawn as enlarged indexed rectangles (`picture()`), instead of tiles and bitmaps.
- `tools/qemu_capture.py` now plays the whole game in the QEMU firmware by looking at the frames.

### Changed

- The building tiles, the crater scene and the bitmap logo, map and far Vesuvius are gone; 13 ground and lungomare tiles remain.
- The Store icon is re-encoded with 32 colours and the metadata is shorter, to keep the package within 64 KiB.
- The title line reads "Una notte. Sei quartieri. Un gigante."

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
