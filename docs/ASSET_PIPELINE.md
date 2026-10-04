# Asset pipeline

`tools/generate_assets.py` writes `assets.h`; `tools/generate_audio.py` composes the score and writes `audio.json`. Both are deterministic.

## Sources

- The Fiat, the hunter, six spirits and the guardian are converted from the pixel-art crops in `assets-src/` to 4-bpp sprites (15 colours and a transparent index). The spirits' palettes are sorted from dark to bright, which is what lets them glow.
- **Villa Doria d'Angri** is converted from `assets-src/villa_doria_dangri.jpg`, a crop of a photograph of the villa: the daytime sky is cut out so the storm shows behind the roof, the picture is dimmed and reduced to 12 flat colours at 160x80.
- The other landmarks, the giant Pulcinella, the props, the logo, the far Vesuvius and the dispatch map are drawn by the generator. The other scenery crops in `assets-src/` are earlier art-direction references and are not used.

![The eight landmarks, the lungomare and the map](scenes.png)

## Pictures

A landmark is a 160x64 picture (160x56 at Mergellina, 160x80 at the villa) drawn at twice its size above two or three rows of ground tiles. A picture is stored as bands of runs:

```text
[rows] [run] [run] ...   one band: this row of runs repeats `rows` times
...
0                        end
```

A run is one byte, the colour in the high nibble and length-1 in the low one; a low nibble of 15 means the length is in the next byte. Colour 0 is not drawn, so the sky shows through. Architecture is mostly columns and courses, so rows repeat and runs are long: the seven drawn landmarks take 417 to 1185 bytes each, the photograph 2609. `picture()` in `game.c` draws each run as one `prg32_gfx_rect_indexed`, enlarged by a scale factor, which is also how the giant is drawn smaller as the trap takes him.

The same format holds the giant Pulcinella (44x60, two poses, drawn 2x), the Gulf of Naples on the map (80x40, drawn 4x), the logo (47x7, drawn 4x) and the far Vesuvius (48x16, drawn 2x).

## Ground tiles as roles

The 13 tiles are 16x16 at 4 bpp: cobbles, kerb, quay, paving, the water, shore and balustrade of the lungomare, the asphalt of the road, the moon. A pixel value is a *role*, not a colour, and each scene's 15 colours give the roles its own materials. The landmark pictures of a scene are drawn in the same 15 colours.

## One colour per cube cell

The ESP32-C6 firmware maps each RGB565 colour to the cell of its 6x6x6 colour cube (`16 + r*36 + g*6 + b`, each channel scaled to 0..5) and stores that index in the framebuffer. Two colours in the same cell would be shown as one. The generator therefore places every colour that can be on screen together in a cell of its own:

- the shared colours (interface navy, props, hunter, Fiat) are placed first;
- each spirit is placed against the shared colours;
- each scene is placed against the shared colours and the spirit that appears in it;
- a colour that lands in a used cell takes the colour already there when that is the smaller error, otherwise it moves to the nearest free cell. The generator prints a note when a colour moves far;
- the eight firmware named colours are exact everywhere and need no cell.

At run time `program()` in `game.c` writes each colour to its cell with `prg32_palette_set` and remembers the entry, so pictures can be drawn with indexed rectangles in those same colours. `tests/source_checks.py` and the host harness both fail if two colours shown together share a cell.

## Effects and the palette

- **Spirits** glow by shifting along their own dark-to-bright ramp, and flash white in the trap. Every colour they show is one of their authored colours or a named colour, so no cell changes.
- **Sky, beam, stars, trap cone, sea, map, meters, falling slime and fire, the giant** use the named colours and palette entries 8-15 and 232-255, which the cube never maps to. They are drawn with `prg32_gfx_rect_indexed` and recoloured freely every frame.
- **Fades and flashes** blend every colour. Colours that meet in a cell merge on the board for those few frames, which is what a fade looks like anyway.

## Sizes

| Asset | Format | Bytes |
| --- | --- | ---: |
| Eight landmark pictures | runs | 9000 |
| Giant Pulcinella, two poses | runs | 661 |
| Map, logo, far Vesuvius | runs | 468 |
| 13 tiles | 4 bpp | 1664 |
| Guardian 96x72 | 4 bpp | 3456 |
| Six spirits 40x40 | 4 bpp | 4800 |
| Fiat 72x36, hunter 32x48 | 4 bpp | 2064 |
| Props: traps, slime, lamp, palm, cup, markers | 4 bpp | 2096 |
| Lungomare and road maps | bytes | 427 |
| Palettes | RGB565 | about 900 |

Development dependencies are Pillow and NumPy; the cartridge depends on neither.
