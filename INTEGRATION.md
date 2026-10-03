# PRG32 `main` alignment

The cartridge targets `riscv-prg32/PRG32` branch `main`. Version 2.0.0 was built against commit `a8669e5`.

## Limits

| | Firmware default | Spiriti 2.0.0 |
| --- | ---: | ---: |
| Stored `.prg32` package, metadata included | 65536 bytes | 55794 bytes |
| Executable cartridge RAM | 64 KiB (32 KiB classroom profile) | 38800 bytes |
| AUDIO block | | 4264 bytes |

`build.sh` builds with `--cart-ram-kib 64` and fails if a Store variant exceeds 65536 bytes. The cartridge does not fit the 32 KiB classroom profile.

## Calls used

- Graphics: `prg32_sprite_draw_indexed`, `prg32_gfx_rect_indexed`, `prg32_palette_set`, `prg32_gfx_text8`. No RGB565 fills and no tile engine: on the ESP32-C6 those are quantised per pixel.
- Audio: `prg32_audio_play_track`, `prg32_audio_note_on_pan`, `prg32_audio_note_off`, `prg32_audio_get_mode`.
- Runtime: `prg32_input_read`, `prg32_ticks_ms`, `prg32_random_number`, `prg32_band_set_game_info`, `prg32_score_submit_current_player`, `prg32_scoreboard_show`.

The exported entry points are `spiriti_napoli97_init`, `spiriti_napoli97_update` and `spiriti_napoli97_draw`.

## Firmware behaviour the cartridge relies on

- **Indexed sprites on the ESP32-C6** are mapped colour by colour to the 6x6x6 system cube; QEMU writes the sprite's own RGB565 colours. [docs/ASSET_PIPELINE.md](docs/ASSET_PIPELINE.md) explains how the art gets exact colours on both.
- **`prg32_palette_set`** recolours pixels already on the ESP32-C6 screen; on QEMU it only affects later indexed draws. The whole screen is redrawn every frame, so both show the palette effects.
- **Palette entries 8-15 and 232-255** are never chosen by the cube mapping. The cartridge uses them for the sky, beam, stars, sea and interface.
- **The palette is not reset** between cartridges, so `spiriti_napoli97_init` restores the eight named colours the text uses.
- **Text** is drawn in named colours on a navy background that has its own cell.
- **The firmware presents** after the draw callback and paces frames at 33 ms; the simulation runs in 33 ms steps from `prg32_ticks_ms`, up to four per frame.
- **Tracker `delta`** is the wait after an event, a `NOTE_ON` plays instrument N on voice N at the channel's volume, and pan 0 means the instrument's own pan. Each track therefore starts by setting the volume and pan of voices 0-3.
- **A sprite frame out of range** draws nothing, and packed pixels run on across rows without padding.
- **Portable cartridges cannot carry pointer tables** in static data; strings are returned by functions and descriptors are filled at run time.
