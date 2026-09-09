# PRG32 integration notes

Target branch: `development-c6`.

The cartridge exports `spiriti_napoli97_init`, `spiriti_napoli97_update`, and `spiriti_napoli97_draw`. `build.sh` builds with `--portable`, the matching `--entry-prefix`, and a procedural AUDIO block, then attaches Store metadata for `esp32c6` and `qemu`.

## Graphics

`game.c` uses the PRG32 playfield/tile engine for map and scene backgrounds. Scene-specific tile dictionaries are installed with `prg32_tile_define()`, copied into the 64x32 layer with `prg32_playfield_put()`, and rendered/scroll-adjusted with playfield calls. The driving road uses the transparent foreground playfield over the Mergellina background.

Movable assets and props are 4-bpp packed indexed sprites rendered by `prg32_sprite_draw_indexed()`. Descriptors are constructed at runtime; generated static data contains no pointer-bearing descriptors.

## Audio

`audio.json` contains procedural SID-like instruments and an original 1980s paranormal-comedy tracker sequence only. Stereo pan is used when available and collapses safely to mono.
