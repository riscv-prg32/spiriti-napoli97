#!/usr/bin/env python3
"""Generate assets.h for Spiriti! Napoli '97.

Everything the cartridge draws is palette-indexed:

- the Fiat, the hunter, six spirits and the guardian of the villa are
  converted from the pixel-art sources in assets-src/ to 4-bpp sprites;
- the landmarks behind each capture are "pictures", stored as bands of runs
  and drawn by game.c as enlarged indexed rectangles. Villa Doria d'Angri is
  converted from a photograph in assets-src/; the others, the giant
  Pulcinella, the logo, the far Vesuvius and the dispatch map are drawn here;
- the ground and the lungomare are 16x16 4-bpp tiles drawn here pixel by
  pixel. A tile pixel is a *role* (ground, water, metal...), and each scene
  gives the roles its own colours;
- props are drawn here too.

The ESP32-C6 firmware stores one byte per pixel and maps every RGB565 colour
to a cell of its 6x6x6 colour cube. The generator therefore gives every
colour that can be on screen together its own cell; game.c writes the colour
into that cell with prg32_palette_set, and the board shows exactly what QEMU
shows. See docs/ASSET_PIPELINE.md.

The output is deterministic and holds no pointers: portable cartridges are
loaded at different addresses and game.c fills its descriptors at run time.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "assets-src"
OUT = ROOT / "assets.h"
DOCS = ROOT / "docs"

# --------------------------------------------------------------------------
# Colour helpers and the firmware's colour cube
# --------------------------------------------------------------------------
NAMED = (0x0000, 0xFFFF, 0xF800, 0x07E0, 0x001F, 0xFFE0, 0x07FF, 0xF81F)


def rgb565(c):
    r, g, b = c
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def rgb888(v):
    return ((v >> 11) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31)


def cell(v):
    return ((v >> 11) * 5 // 31, ((v >> 5) & 63) * 5 // 63, (v & 31) * 5 // 31)


def cell_index(v):
    r, g, b = cell(v)
    return 16 + r * 36 + g * 6 + b


def _box(i, top):
    values = [v for v in range(top + 1) if v * 5 // top == i]
    return values[0], values[-1]


BOX5 = [_box(i, 31) for i in range(6)]
BOX6 = [_box(i, 63) for i in range(6)]


def into_cell(v, target):
    """The colour of cell `target` closest to v."""
    r = min(max(v >> 11, BOX5[target[0]][0]), BOX5[target[0]][1])
    g = min(max((v >> 5) & 63, BOX6[target[1]][0]), BOX6[target[1]][1])
    b = min(max(v & 31, BOX5[target[2]][0]), BOX5[target[2]][1])
    return (r << 11) | (g << 5) | b


def distance(a, b):
    return sum((x - y) ** 2 for x, y in zip(rgb888(a), rgb888(b))) ** 0.5


ALL_CELLS = [(r, g, b) for r in range(6) for g in range(6) for b in range(6)]
MERGE = 26.0    # colours this close in one cell become one colour


def place(colours, taken, own=None, blocked=()):
    """Give each colour its own cube cell.

    `taken` maps the cells of everything else that can be on screen at the
    same time to its colour; `own` collects the cells of this group. A colour
    that lands in a used cell takes the colour already there when that is the
    smaller error, otherwise it moves to the nearest free cell. `blocked`
    cells hold different colours at different times and cannot be shared.
    """
    own = {} if own is None else own
    out = []
    for v in colours:
        if v in NAMED:
            out.append(v)
            continue
        k = cell(v)
        holder = own.get(k, taken.get(k))
        if holder is None and k not in blocked:
            own[k] = v
            out.append(v)
            continue
        free = [c for c in ALL_CELLS if c not in own and c not in taken and c not in blocked]
        best = min(free, key=lambda c: distance(into_cell(v, c), v))
        moved = into_cell(v, best)
        # Sharing the holder's colour costs a distinct shade; moving costs accuracy.
        if holder is not None and (holder == v or distance(holder, v) <= MERGE or distance(holder, v) <= distance(moved, v)):
            out.append(holder)
        else:
            own[best] = moved
            out.append(moved)
    return out, own


# --------------------------------------------------------------------------
# C output
# --------------------------------------------------------------------------
def c_u8(name, vals, per=20):
    vals = [int(v) & 255 for v in vals]
    rows = [",".join(f"{v}" for v in vals[i:i + per]) for i in range(0, len(vals), per)]
    return f"static const uint8_t {name}[{len(vals)}] = {{\n" + ",\n".join(rows) + "};"


def c_u16(name, vals, per=12):
    vals = [int(v) & 0xFFFF for v in vals]
    rows = [",".join(f"0x{v:04X}" for v in vals[i:i + per]) for i in range(0, len(vals), per)]
    return f"static const uint16_t {name}[{len(vals)}] = {{\n" + ",\n".join(rows) + "};"


def pack(indices, bpp):
    """Dense packing, most significant index first, as prg32_sprite_draw_indexed reads it."""
    flat = np.asarray(indices, dtype=np.uint8).reshape(-1)
    assert flat.max(initial=0) < (1 << bpp)
    assert (flat.size * bpp) % 8 == 0, "frame must end on a byte"
    out = []
    acc = n = 0
    for v in flat:
        acc = (acc << bpp) | int(v)
        n += bpp
        if n == 8:
            out.append(acc)
            acc = n = 0
    return out


# --------------------------------------------------------------------------
# Sprites converted from the pixel-art sources
# --------------------------------------------------------------------------
def background_mask(im):
    """Flood-fill the dark design-sheet panel from the edges."""
    a = np.asarray(im.convert("RGB"), dtype=np.int16)
    h, w, _ = a.shape
    corners = np.concatenate([a[0:3, 0:3].reshape(-1, 3), a[0:3, -3:].reshape(-1, 3),
                              a[-3:, 0:3].reshape(-1, 3), a[-3:, -3:].reshape(-1, 3)], axis=0)
    bg = np.median(corners, axis=0)
    candidate = np.sqrt(np.sum((a - bg) ** 2, axis=2)) < 54
    candidate |= (a[:, :, 0] < 28) & (a[:, :, 1] < 42) & (a[:, :, 2] < 60)
    seen = np.zeros((h, w), dtype=bool)
    stack = [(0, x) for x in range(w)] + [(h - 1, x) for x in range(w)]
    stack += [(y, 0) for y in range(h)] + [(y, w - 1) for y in range(h)]
    while stack:
        y, x = stack.pop()
        if y < 0 or x < 0 or y >= h or x >= w or seen[y, x] or not candidate[y, x]:
            continue
        seen[y, x] = True
        stack += [(y, x - 1), (y, x + 1), (y - 1, x), (y + 1, x)]
    return seen


def trim_and_fit(im, size):
    im = im.convert("RGB")
    mask = background_mask(im)
    ys, xs = np.where(~mask)
    x0, x1 = max(0, int(xs.min()) - 2), min(im.width, int(xs.max()) + 3)
    y0, y1 = max(0, int(ys.min()) - 2), min(im.height, int(ys.max()) + 3)
    crop = im.crop((x0, y0, x1, y1))
    alpha = Image.fromarray((~background_mask(crop) * 255).astype(np.uint8))
    scale = min(size[0] / crop.width, size[1] / crop.height)
    nw, nh = max(1, round(crop.width * scale)), max(1, round(crop.height * scale))
    crop = crop.resize((nw, nh), Image.Resampling.NEAREST).convert("RGBA")
    crop.putalpha(alpha.resize((nw, nh), Image.Resampling.NEAREST))
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    canvas.alpha_composite(crop, ((size[0] - nw) // 2, size[1] - nh))     # stand on the bottom edge
    return canvas


def convert_sprite(filename, size, crop, by_light):
    """-> (indices, [RGB565 * 16]); index 0 is transparent."""
    source = Image.open(SRC / filename)
    if crop:
        source = source.crop(crop)
    im = trim_and_fit(source, size)
    rgba = np.asarray(im)
    opaque = rgba[:, :, 3] > 0
    rgb = rgba[:, :, :3].copy()
    rgb[~opaque] = rgb[opaque].mean(axis=0).astype(np.uint8)       # keep the key colour out of the palette
    q = Image.fromarray(rgb).quantize(colors=15, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    inds = np.asarray(q, dtype=np.uint8)
    pal = q.getpalette()[:45]
    colours = [rgb565(tuple(pal[i * 3:i * 3 + 3])) for i in range(15)]
    counts = [int(((inds == i) & opaque).sum()) for i in range(15)]
    if by_light:        # spirits: a dark-to-bright ramp the game can shift to make them glow
        order = sorted(range(15), key=lambda i: sum(x * w for x, w in zip(rgb888(colours[i]), (3, 6, 1))))
    else:
        order = sorted(range(15), key=lambda i: -counts[i])
    remap = np.zeros(16, dtype=np.uint8)
    for new, old in enumerate(order):
        remap[old] = new + 1
    out = np.where(opaque, remap[inds], 0).astype(np.uint8)
    return out, [0] + [colours[i] for i in order], [counts[i] for i in order]


SPRITES = [
    # symbol, file, size, crop, ramp
    ("fiat", "fiat.png", (72, 36), (0, 0, 92, 76), False),
    ("hunter", "hunter.png", (32, 48), (0, 0, 56, 84), False),
    ("ghost0", "ghost0.png", (40, 40), (0, 0, 72, 70), True),
    ("ghost1", "ghost1.png", (40, 40), (0, 0, 69, 70), True),
    ("ghost2", "ghost2.png", (40, 40), (0, 0, 71, 70), True),
    ("ghost3", "ghost3.png", (40, 40), (0, 0, 78, 70), True),
    ("ghost4", "ghost4.png", (40, 40), (0, 0, 72, 70), True),
    ("ghost5", "ghost5.png", (40, 40), (0, 0, 71, 70), True),
    ("boss", "boss.png", (96, 72), None, True),
]

# --------------------------------------------------------------------------
# Props: one shared 16-colour palette
# --------------------------------------------------------------------------
PROP_RGB = [
    (0, 0, 0),            # 0 transparent
    (20, 22, 34),         # 1 outline
    (62, 66, 80),         # 2 dark metal
    (156, 164, 178),      # 3 light metal
    (255, 206, 56),       # 4 lamp yellow
    (232, 48, 64),        # 5 red
    (40, 208, 248),       # 6 cyan
    (255, 255, 255),      # 7 white
    (16, 150, 56),        # 8 slime dark
    (84, 236, 120),       # 9 slime
    (196, 255, 120),      # 10 slime light
    (120, 78, 40),        # 11 trunk
    (190, 138, 66),       # 12 trunk light
    (30, 92, 50),         # 13 leaf dark
    (62, 150, 66),        # 14 leaf
    (124, 200, 84),       # 15 leaf light
]


def prop(w, h, draw):
    im = Image.new("P", (w, h), 0)
    draw(ImageDraw.Draw(im))
    return np.asarray(im, dtype=np.uint8)


def make_props():
    p = {}
    p["trap"] = prop(24, 14, lambda d: (
        d.rectangle((2, 5, 21, 11), fill=3), d.rectangle((2, 5, 21, 5), fill=7), d.rectangle((4, 2, 19, 4), fill=2),
        d.rectangle((6, 1, 17, 2), fill=4), d.rectangle((6, 7, 17, 8), fill=5), d.point([(8, 7), (12, 7), (16, 7)], fill=4),
        d.rectangle((1, 11, 22, 12), fill=2), d.rectangle((4, 12, 6, 13), fill=1), d.rectangle((17, 12, 19, 13), fill=1),
        d.rectangle((2, 9, 3, 10), fill=6), d.rectangle((20, 9, 21, 10), fill=6)))
    p["slime"] = prop(24, 12, lambda d: (
        d.ellipse((1, 4, 22, 11), fill=8), d.ellipse((3, 3, 19, 10), fill=9), d.ellipse((6, 1, 15, 8), fill=9),
        d.ellipse((7, 2, 12, 5), fill=10), d.point([(9, 3), (10, 3)], fill=7), d.rectangle((14, 6, 15, 7), fill=1),
        d.rectangle((9, 6, 10, 7), fill=1), d.line((10, 9, 14, 9), fill=8), d.point([(2, 11), (21, 11), (18, 2)], fill=9)))
    p["lamp"] = prop(16, 40, lambda d: (
        d.rectangle((7, 12, 8, 37), fill=2), d.line((7, 12, 7, 37), fill=3), d.rectangle((4, 37, 11, 39), fill=2),
        d.rectangle((5, 36, 10, 36), fill=3), d.polygon([(3, 3), (12, 3), (10, 12), (5, 12)], fill=1),
        d.rectangle((5, 4, 10, 10), fill=4), d.rectangle((6, 5, 9, 8), fill=7), d.rectangle((6, 0, 9, 2), fill=2),
        d.line((2, 3, 13, 3), fill=2)))
    p["palm"] = prop(32, 56, lambda d: (
        d.polygon([(14, 16), (18, 16), (20, 55), (13, 55)], fill=11), d.line((16, 18, 15, 54), fill=12),
        [d.line((13, y, 19, y + 1), fill=1) for y in range(22, 54, 6)],
        d.polygon([(16, 16), (0, 8), (4, 6), (12, 10)], fill=14), d.polygon([(16, 16), (5, 0), (10, 0), (15, 9)], fill=15),
        d.polygon([(16, 16), (26, 0), (21, 0), (17, 9)], fill=15), d.polygon([(16, 16), (31, 8), (27, 6), (20, 10)], fill=14),
        d.polygon([(16, 16), (1, 20), (3, 23), (12, 18)], fill=13), d.polygon([(16, 16), (30, 20), (28, 23), (20, 18)], fill=13),
        d.ellipse((13, 13, 19, 18), fill=11)))
    p["cup"] = prop(16, 12, lambda d: (
        d.polygon([(2, 3), (11, 3), (10, 9), (3, 9)], fill=7), d.rectangle((3, 3, 10, 4), fill=11),
        d.arc((9, 4, 14, 8), -90, 90, fill=7), d.rectangle((1, 10, 12, 11), fill=3), d.point([(5, 0), (7, 1), (8, 0)], fill=3),
        d.line((4, 6, 4, 8), fill=3)))
    # The oversized trap bolted to the Fiat's roof for the last call.
    p["rooftrap"] = prop(36, 12, lambda d: (
        d.rectangle((0, 4, 35, 10), fill=3), d.rectangle((0, 4, 35, 4), fill=7), d.rectangle((3, 1, 32, 3), fill=2),
        [d.rectangle((x, 6, x + 2, 8), fill=4 if (x // 4) % 2 else 1) for x in range(4, 32, 4)],
        d.rectangle((17, 1, 18, 3), fill=1), d.rectangle((0, 6, 1, 8), fill=5), d.rectangle((34, 6, 35, 8), fill=5),
        d.rectangle((2, 10, 33, 11), fill=2), d.rectangle((6, 11, 8, 11), fill=1), d.rectangle((27, 11, 29, 11), fill=1)))
    # Markers, one frame each: a spirit (on the map and over the road) and a cleared district.
    p["mark"] = np.concatenate([
        prop(16, 16, lambda d: (
            d.ellipse((3, 1, 12, 10), fill=7), d.rectangle((3, 6, 12, 12), fill=7),
            d.polygon([(3, 12), (3, 14), (5, 12), (7, 14), (8, 12), (10, 14), (12, 12)], fill=7),
            d.rectangle((5, 5, 6, 7), fill=1), d.rectangle((9, 5, 10, 7), fill=1), d.line((6, 10, 9, 10), fill=1),
            d.arc((2, 0, 13, 11), 180, 360, fill=6))),
        prop(16, 16, lambda d: (
            d.ellipse((2, 2, 13, 13), fill=8), d.ellipse((3, 3, 12, 12), fill=14),
            d.line((5, 8, 7, 10), fill=7, width=2), d.line((7, 10, 11, 5), fill=7, width=2))),
    ])
    return p


# --------------------------------------------------------------------------
# Ground and lungomare tiles: 16x16, a pixel is a role
# --------------------------------------------------------------------------
(T_, OUT_, WD, WM, WL, A1, A2, WIN_D, WIN_L, GLOW, GD, GL, N1, N2, MET, HI) = range(16)
ROLE_NAMES = ("key", "outline", "wall dark", "wall", "wall light", "accent 1", "accent 2", "window dark",
              "window lit", "glow", "ground dark", "ground light", "deep", "light", "metal", "highlight")


def blank(fill=T_):
    return np.full((16, 16), fill, dtype=np.uint8)


def R(t, x0, y0, x1, y1, c):
    t[y0:y1 + 1, x0:x1 + 1] = c


def P(t, pts, c):
    for x, y in pts:
        t[y, x] = c


def t_cobble():
    t = blank(GD)
    for row, y in enumerate(range(0, 16, 4)):
        for x in range(0, 16, 8):
            xx = (x + (4 if row % 2 else 0)) % 16
            for i in range(5):
                t[y, (xx + 1 + i) % 16] = GL
            t[y + 1, xx % 16] = GL
            t[y + 1, (xx + 6) % 16] = GL
    return t


def t_kerb():
    t = t_cobble()
    R(t, 0, 0, 15, 0, HI)
    R(t, 0, 1, 15, 3, GL)
    R(t, 0, 4, 15, 4, OUT_)
    for x in (3, 11):
        R(t, x, 1, x, 3, GD)
    return t


def t_water(phase):
    t = blank(N1)
    waves = ((3, 1, 5), (7, 9, 5), (11, 0, 4), (13, 8, 3), (1, 11, 3), (9, 3, 3))
    for y, x, n in waves:
        for i in range(n):
            t[y, (x + i + phase * 4) % 16] = N2
    P(t, [((4 + phase * 7) % 16, 5), ((12 + phase * 5) % 16, 14)], HI)
    return t


def t_shore():
    t = blank()
    R(t, 0, 9, 15, 10, OUT_)
    P(t, [(1, 8), (2, 8), (6, 8), (7, 7), (7, 8), (12, 8), (13, 8)], OUT_)
    P(t, [(2, 10), (5, 9), (9, 10), (11, 9), (14, 10)], WIN_L)
    P(t, [(7, 10)], GLOW)
    R(t, 0, 11, 15, 15, N1)
    P(t, [(2, 11), (5, 11), (9, 11), (11, 11), (14, 11), (5, 13), (6, 13), (11, 14), (12, 14)], N2)
    return t


def t_balustrade(pillar):
    t = t_water(0)
    R(t, 0, 3, 15, 4, HI)
    R(t, 0, 5, 15, 5, MET)
    R(t, 0, 13, 15, 15, MET)
    R(t, 0, 13, 15, 13, HI)
    if pillar:
        R(t, 4, 0, 11, 15, MET)
        R(t, 5, 0, 6, 15, HI)
        R(t, 3, 0, 12, 1, HI)
        R(t, 11, 2, 11, 15, WD)
    else:
        for x in (1, 6, 11):
            R(t, x, 6, x + 2, 12, MET)
            R(t, x, 6, x, 12, HI)
            t[9, x + 3] = MET
            t[9, (x + 15) % 16] = MET
    return t


def t_quay():
    t = blank(GD)
    R(t, 0, 0, 15, 0, HI)
    R(t, 0, 1, 15, 2, GL)
    R(t, 0, 3, 15, 3, OUT_)
    R(t, 7, 4, 7, 15, OUT_)
    R(t, 0, 10, 15, 10, OUT_)
    P(t, [(3, 6), (11, 7), (4, 13), (12, 12)], GL)
    return t


def t_flag():
    t = blank(GD)
    R(t, 0, 0, 15, 0, GL)
    R(t, 0, 8, 15, 8, GL)
    R(t, 4, 1, 4, 7, GL)
    R(t, 12, 9, 12, 15, GL)
    P(t, [(8, 4), (9, 4), (2, 12), (14, 3)], OUT_)
    return t


def t_asphalt(dash):
    t = blank(GD)
    P(t, [(2, 3), (9, 6), (13, 11), (5, 13), (11, 1), (7, 9)], GL)
    if dash == 1:
        R(t, 2, 0, 11, 1, HI)
    if dash == 2:
        R(t, 0, 0, 15, 1, HI)
    return t


def t_moon():
    t = blank()
    for y in range(16):
        for x in range(16):
            if (x - 7.5) ** 2 + (y - 7.5) ** 2 < 42:
                t[y, x] = HI
    P(t, [(5, 5), (6, 5), (9, 9), (10, 9), (10, 10), (6, 10)], MET)
    return t


TILES = [
    ("COBBLE", t_cobble()), ("KERB", t_kerb()), ("WATER", t_water(0)), ("WATER_B", t_water(1)),
    ("SHORE", t_shore()), ("BALUSTRADE", t_balustrade(False)), ("PILLAR", t_balustrade(True)),
    ("QUAY", t_quay()), ("FLAG", t_flag()), ("ASPHALT", t_asphalt(0)), ("DASH", t_asphalt(1)),
    ("EDGE", t_asphalt(2)), ("MOON", t_moon()),
]
TILE_CODE = {name: i + 1 for i, (name, _) in enumerate(TILES)}       # 0 = nothing
CHARS = {".": 0, "o": "COBBLE", "k": "KERB", "~": "WATER", "s": "SHORE", "=": "BALUSTRADE", "I": "PILLAR",
         "q": "QUAY", "f": "FLAG", "a": "ASPHALT", "_": "DASH", "e": "EDGE", "O": "MOON"}

# The lungomare: the title and the endings (SHORE_ROWS) and the drive (ROAD_ROWS).
SCENE_COLS, SCENE_ROWS = 20, 10
SHORE_ROWS = ["................O...", "....................", "....................", "....................",
              "ssssssssssssssssssss", "~~~~~~~~~~~~~~~~~~~~", "~~~~~~~~~~~~~~~~~~~~", "I===I===I===I===I===",
              "kkkkkkkkkkkkkkkkkkkk", "oooooooooooooooooooo"]
ROAD_ROWS = ["................O...", "....................", "....................", "ssssssssssssssssssss",
             "~~~~~~~~~~~~~~~~~~~~", "I===I===I===I===I===", "kkkkkkkkkkkkkkkkkkkk", "eeeeeeeeeeeeeeeeeeee",
             "____________________", "____________________"]


# --------------------------------------------------------------------------
# Pictures: role-indexed images stored as bands of runs and drawn enlarged
# --------------------------------------------------------------------------
def encode_picture(a):
    """Rows that repeat are stored once: [rows][runs...]... 0.

    A run is one byte, colour in the high nibble and length-1 in the low one;
    a low nibble of 15 means the length follows in the next byte. Colour 0 is
    not drawn. Buildings are mostly columns and courses, so this is far
    smaller than a bitmap, and game.c draws each run as one rectangle.
    """
    a = np.asarray(a, dtype=np.uint8)
    h, w = a.shape
    out = []
    y = 0
    while y < h:
        rep = 1
        while y + rep < h and rep < 255 and (a[y + rep] == a[y]).all():
            rep += 1
        out.append(rep)
        x = 0
        while x < w:
            c = int(a[y, x])
            n = 1
            while x + n < w and a[y, x + n] == c and n < 255:
                n += 1
            out += [(c << 4) | (n - 1)] if n <= 15 else [(c << 4) | 15, n]
            x += n
        y += rep
    return out + [0]


PIC_W = 160


def canvas(h=64):
    im = Image.new("P", (PIC_W, h), 0)
    return im, ImageDraw.Draw(im)


def pic_centro():
    """Piazza del Gesu Nuovo: the diamond-point facade of the church and the Guglia dell'Immacolata."""
    im, d = canvas()
    d.rectangle((0, 20, 20, 63), fill=A1)                      # Palazzo Pignatelli side
    d.rectangle((0, 18, 21, 19), fill=WL)
    for y in (24, 36, 48):
        for x in (3, 12):
            d.rectangle((x, y, x + 4, y + 7), fill=WIN_L if (x + y) % 5 == 0 else WIN_D)
    d.rectangle((26, 12, 128, 63), fill=WD)                    # piperno facade
    d.rectangle((24, 10, 130, 11), fill=WM)
    for y in range(16, 62, 4):                                 # the diamond-point ashlar
        for x in range(28 + (y // 4 % 2) * 4, 127, 8):
            d.rectangle((x, y, x + 1, y + 1), fill=WM)
    d.rectangle((62, 30, 92, 63), fill=WL)                     # marble portal
    d.polygon([(60, 30), (77, 21), (94, 30)], fill=WL)
    d.rectangle((64, 30, 66, 63), fill=HI)
    d.rectangle((88, 30, 90, 63), fill=HI)
    d.rectangle((70, 38, 84, 63), fill=A2)
    d.rectangle((77, 38, 77, 63), fill=OUT_)
    d.rectangle((70, 36, 84, 37), fill=MET)
    for x in (36, 104):                                        # side portals
        d.rectangle((x, 42, x + 14, 63), fill=WL)
        d.rectangle((x + 3, 47, x + 11, 63), fill=A2)
        d.rectangle((x - 1, 40, x + 15, 41), fill=HI)
        d.rectangle((x + 2, 22, x + 12, 34), fill=WL)          # windows above
        d.rectangle((x + 4, 24, x + 10, 33), fill=WIN_D)
    d.rectangle((70, 13, 84, 19), fill=WL)
    d.rectangle((72, 14, 82, 19), fill=WIN_L)
    for y in range(4, 64):                                     # the spire
        half = 1 + (y - 4) // 11 + (5 if y > 54 else 0)
        d.rectangle((146 - half, y, 146 + half, y), fill=WL)
        d.point((146 - half, y), fill=HI)
    for y in (16, 28, 40, 52):
        d.rectangle((146 - 2 - y // 11, y, 146 + 2 + y // 11, y + 1), fill=MET)
    d.rectangle((145, 0, 147, 3), fill=GLOW)
    return im


def pic_mergellina():
    """The bay from Mergellina: Castel dell'Ovo on its islet and the Vesuvius across the water."""
    im, d = canvas(56)
    d.polygon([(64, 36), (92, 24), (104, 15), (110, 18), (116, 12), (124, 15), (150, 32), (159, 36)], fill=WD)
    d.polygon([(110, 18), (116, 12), (124, 15), (150, 32), (159, 36), (130, 36)], fill=WM)
    d.point([(117, 11), (118, 10), (116, 13)], fill=A2)
    d.rectangle((0, 36, 159, 37), fill=OUT_)
    for x in (72, 80, 91, 99, 108, 121, 133, 140, 152):
        d.point((x, 36 + x % 2), fill=WIN_L)
    d.rectangle((0, 38, 159, 55), fill=N1)
    for x, y in ((84, 41), (120, 44), (96, 49), (140, 51), (70, 53), (30, 54)):
        d.rectangle((x, y, x + 5, y), fill=N2)
    d.polygon([(4, 46), (72, 46), (76, 50), (0, 50)], fill=OUT_)        # the islet of Megaride
    d.rectangle((8, 34, 68, 46), fill=A1)
    d.rectangle((8, 34, 68, 34), fill=WL)
    d.rectangle((14, 27, 46, 34), fill=WL)
    d.rectangle((22, 21, 38, 27), fill=A1)
    d.rectangle((22, 21, 38, 21), fill=WL)
    d.rectangle((50, 29, 64, 34), fill=A1)
    for x in (12, 20, 28, 36, 44, 52, 60):
        d.rectangle((x, 38, x + 1, 40), fill=WIN_L if x % 3 == 0 else OUT_)
    for x in (18, 26, 34, 42):
        d.point((x, 30), fill=OUT_)
    d.rectangle((68, 44, 96, 45), fill=MET)                             # the causeway
    return im


def pic_vomero():
    """The Vomero hill: Castel Sant'Elmo above the Certosa di San Martino."""
    im, d = canvas()
    d.polygon([(0, 34), (24, 24), (136, 22), (159, 30), (159, 63), (0, 63)], fill=N1)
    d.polygon([(22, 24), (30, 6), (124, 6), (134, 24)], fill=WM)        # the star fort
    d.polygon([(96, 6), (124, 6), (134, 24), (104, 24)], fill=WD)
    d.polygon([(40, 24), (48, 10), (66, 10), (72, 24)], fill=WL)
    d.rectangle((30, 6, 124, 6), fill=HI)
    for x in (36, 58, 82, 112):
        d.rectangle((x, 12, x + 1, 14), fill=OUT_)
    d.rectangle((58, 28, 152, 40), fill=HI)                             # the Certosa
    d.rectangle((56, 26, 154, 27), fill=A2)
    for x in range(62, 150, 7):
        d.rectangle((x, 31, x + 3, 37), fill=WIN_D)
        d.point([(x, 31), (x + 3, 31)], fill=HI)
    d.ellipse((132, 16, 144, 28), fill=MET)
    d.rectangle((137, 13, 138, 16), fill=HI)
    palette = (A1, A2, WL, A1, WL, A2, A1, WL)
    for i, x in enumerate(range(2, 156, 20)):                           # houses down the slope
        top = 44 + (i * 5) % 9
        d.rectangle((x, top, x + 17, 63), fill=palette[i])
        d.rectangle((x, top, x + 17, top), fill=A2 if palette[i] != A2 else WD)
        for wy in range(top + 4, 60, 7):
            for wx in (x + 3, x + 10):
                d.rectangle((wx, wy, wx + 3, wy + 3), fill=WIN_L if (wx + wy + i) % 3 == 0 else WIN_D)
    for x, y in ((8, 36), (30, 38), (48, 34), (150, 42)):
        d.ellipse((x, y, x + 8, y + 6), fill=N2)
    return im


def pic_porto():
    """Castel Nuovo, the Maschio Angioino: round piperno towers and the marble triumphal arch."""
    im, d = canvas()
    d.rectangle((128, 50, 159, 63), fill=N1)
    d.rectangle((132, 44, 159, 49), fill=OUT_)                          # a ferry at the Molo Beverello
    d.rectangle((140, 38, 156, 43), fill=HI)
    for x in (142, 147, 152):
        d.point((x, 40), fill=WIN_L)
    d.rectangle((30, 26, 116, 63), fill=WM)                             # curtain walls
    for x in range(30, 116, 6):
        d.rectangle((x, 23, x + 2, 25), fill=WM)
    for x in (40, 50, 60):
        d.rectangle((x, 36, x + 2, 42), fill=WIN_D)
    for cx in (20, 76, 118):
        d.rectangle((cx - 10, 12, cx + 10, 63), fill=WD)
        d.rectangle((cx - 7, 12, cx - 5, 63), fill=WM)
        d.rectangle((cx + 7, 12, cx + 10, 63), fill=OUT_)
        d.rectangle((cx - 12, 8, cx + 12, 13), fill=WD)
        d.rectangle((cx - 12, 13, cx + 12, 13), fill=OUT_)
        for x in range(cx - 12, cx + 12, 5):
            d.rectangle((x, 5, x + 2, 7), fill=WD)
        d.polygon([(cx - 10, 52), (cx - 14, 63), (cx + 14, 63), (cx + 10, 52)], fill=WD)
        d.rectangle((cx - 1, 24, cx, 28), fill=OUT_)
    d.rectangle((87, 16, 107, 63), fill=HI)                             # the arch of Alfonso of Aragon
    d.rectangle((91, 44, 103, 63), fill=OUT_)
    d.rectangle((93, 42, 101, 43), fill=OUT_)
    d.rectangle((91, 26, 103, 36), fill=WIN_D)
    d.rectangle((93, 24, 101, 25), fill=WIN_D)
    for y in (20, 38):
        d.rectangle((87, y, 107, y + 1), fill=MET)
    d.polygon([(87, 16), (97, 10), (107, 16)], fill=HI)
    return im


def pic_fuorigrotta():
    """The stadium at Fuorigrotta: the concrete bowl under its steel roof and floodlights."""
    im, d = canvas()
    d.ellipse((2, 20, 157, 120), fill=WL)
    d.rectangle((2, 44, 157, 63), fill=WM)
    d.rectangle((2, 42, 157, 43), fill=OUT_)
    for x in range(6, 156, 8):
        d.rectangle((x, 44, x, 63), fill=WD)
    for x in range(10, 152, 16):
        d.rectangle((x, 54, x + 5, 63), fill=OUT_)
    d.arc((2, 12, 157, 112), 184, 356, fill=A1, width=3)                # the roof ring
    for x in (22, 50, 80, 108, 137):
        top = 22 - int(10 * (1 - ((x - 80) / 80) ** 2))
        d.rectangle((x, top + 4, x + 1, top + 20), fill=MET)
        d.rectangle((x - 3, top + 2, x + 4, top + 4), fill=A1)
    for x in (14, 144):
        d.rectangle((x, 6, x + 1, 30), fill=MET)
        d.rectangle((x - 3, 2, x + 4, 7), fill=MET)
        d.point([(x - 2, 3), (x, 3), (x + 2, 3), (x - 2, 5), (x, 5), (x + 2, 5)], fill=GLOW)
    for i, x in enumerate(range(20, 140, 3)):
        d.point((x, 34 + (i * 7) % 5), fill=(A2, HI, WIN_L, A1)[i % 4])  # the crowd
    d.rectangle((66, 46, 94, 51), fill=A1)
    d.rectangle((68, 48, 92, 49), fill=HI)
    return im


def pic_capodimonte():
    """The Reggia di Capodimonte: Pompeian red walls and grey piperno pilasters among the trees."""
    im, d = canvas()
    for x, y, r in ((0, 12, 20), (136, 10, 22), (60, 14, 16), (96, 16, 14)):
        d.ellipse((x, y, x + 2 * r, y + r + 8), fill=N1)
    d.rectangle((8, 24, 151, 63), fill=A2)
    d.rectangle((6, 21, 153, 23), fill=WL)
    for x in range(8, 152, 4):
        d.point((x, 20), fill=HI)
    d.rectangle((8, 56, 151, 63), fill=WD)
    for bay, x in enumerate(range(8, 152, 16)):
        d.rectangle((x, 24, x + 2, 63), fill=MET)
        if x + 16 > 152:
            break
        d.rectangle((x + 6, 27, x + 12, 27), fill=WL)
        d.rectangle((x + 7, 28, x + 11, 36), fill=WIN_L if bay in (2, 6) else WIN_D)
        if bay in (3, 4, 5):
            d.rectangle((x + 6, 46, x + 12, 63), fill=OUT_)
            d.rectangle((x + 7, 44, x + 11, 45), fill=OUT_)
        else:
            d.rectangle((x + 6, 41, x + 12, 41), fill=WL)
            d.rectangle((x + 7, 42, x + 11, 51), fill=WIN_D)
    d.rectangle((149, 24, 151, 63), fill=MET)
    for x, y in ((0, 44), (146, 46)):
        d.ellipse((x, y, x + 13, y + 12), fill=N2)
        d.rectangle((x + 6, y + 12, x + 7, 63), fill=A1)
    return im


def pic_villa():
    """Villa Doria d'Angri at Posillipo, from the photograph in assets-src/.

    The daytime sky is cut out so the storm shows behind the roof, the picture
    is dimmed towards dusk and reduced to 12 flat colours.
    """
    photo = Image.open(SRC / "villa_doria_dangri.jpg").convert("RGB")
    photo = photo.crop((44, 0, 500, 256)).resize((PIC_W, 80), Image.Resampling.LANCZOS)
    a = np.asarray(photo, dtype=np.int16)
    sky = (a[:, :, 2] > a[:, :, 0] + 24) & (a[:, :, 2] > a[:, :, 1] + 8) & (a[:, :, 2] > 110)
    seen = np.zeros(sky.shape, dtype=bool)
    stack = [(0, x) for x in range(PIC_W)]
    while stack:                                                         # only the sky that reaches the top edge
        y, x = stack.pop()
        if y < 0 or x < 0 or y >= 80 or x >= PIC_W or seen[y, x] or not sky[y, x]:
            continue
        seen[y, x] = True
        stack += [(y, x - 1), (y, x + 1), (y + 1, x), (y - 1, x)]
    grey = a.mean(axis=2, keepdims=True)
    graded = np.clip((grey + (a - grey) * 1.35) * np.array([0.86, 0.80, 0.82]), 0, 255).astype(np.uint8)
    graded[seen] = graded[~seen].mean(axis=0).astype(np.uint8)
    q = Image.fromarray(graded).quantize(colors=12, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    q = q.filter(ImageFilter.ModeFilter(3))
    inds = np.asarray(q, dtype=np.uint8) + 1
    inds[seen] = 0
    for y in range(80):                                                  # drop one-pixel specks along each row
        for x in range(1, PIC_W - 1):
            if inds[y, x - 1] == inds[y, x + 1] != inds[y, x] and inds[y, x - 1]:
                inds[y, x] = inds[y, x - 1]
    pal = q.getpalette()[:36]
    return inds, [tuple(pal[i * 3:i * 3 + 3]) for i in range(12)]


def pic_plebiscito():
    """Piazza del Plebiscito: the dome and portico of San Francesco di Paola and its colonnade."""
    im, d = canvas()
    d.ellipse((56, 4, 103, 52), fill=MET)                               # the great dome
    d.arc((58, 6, 101, 50), 190, 260, fill=WL)
    d.rectangle((77, 0, 82, 5), fill=WL)
    d.rectangle((79, 0, 80, 1), fill=GLOW)
    d.rectangle((58, 26, 101, 33), fill=WL)
    for x in range(61, 100, 5):
        d.rectangle((x, 28, x + 1, 31), fill=WIN_D)
    for x in (36, 106):                                                 # side domes
        d.ellipse((x, 24, x + 17, 42), fill=MET)
        d.rectangle((x + 8, 21, x + 9, 24), fill=WL)
    d.rectangle((0, 42, 159, 55), fill=WD)                              # the hemicycle
    d.rectangle((0, 38, 159, 41), fill=WL)
    for x in range(2, 158, 5):
        d.rectangle((x, 42, x + 1, 55), fill=HI)
    for x in range(4, 158, 10):
        d.rectangle((x, 35, x, 37), fill=MET)
    d.rectangle((58, 33, 101, 55), fill=WM)
    d.polygon([(58, 33), (79, 24), (80, 24), (101, 33)], fill=HI)       # the portico
    d.rectangle((58, 33, 101, 34), fill=WL)
    d.rectangle((60, 35, 99, 55), fill=OUT_)
    for x in range(61, 99, 7):
        d.rectangle((x, 35, x + 2, 55), fill=HI)
    d.rectangle((0, 56, 159, 58), fill=WL)
    d.rectangle((0, 59, 159, 63), fill=GL)
    for x in (30, 124):                                                 # the equestrian statues
        d.rectangle((x, 52, x + 6, 63), fill=WM)
        d.rectangle((x - 1, 47, x + 7, 51), fill=OUT_)
        d.rectangle((x + 2, 43, x + 3, 47), fill=OUT_)
    return im


def pulcinella(frame):
    """44x60, drawn 2x: white smock and sugar-loaf hat, black half mask with the hooked nose.
    Colours: 1 white, 2 shadow, 3 black, 4 red. Frame 0 arms raised, frame 1 arms down."""
    im = Image.new("P", (44, 60), 0)
    d = ImageDraw.Draw(im)
    d.polygon([(15, 14), (29, 14), (30, 6), (36, 1), (33, 0), (24, 4)], fill=1)       # the hat, flopping
    d.line([(27, 13), (29, 6), (34, 2)], fill=2)
    d.ellipse((14, 11, 30, 27), fill=1)
    d.rectangle((14, 15, 30, 20), fill=3)                                             # the mask
    d.polygon([(21, 17), (29, 25), (22, 23)], fill=3)
    d.rectangle((16, 16, 18, 17), fill=4)
    d.rectangle((25, 16, 27, 17), fill=4)
    d.line([(17, 24), (21, 25)], fill=4)
    d.polygon([(9, 28), (35, 28), (39, 47), (5, 47)], fill=1)                         # the smock
    for x in (14, 22, 30):
        d.line([(x, 31), (x - 2 + (x - 22) // 4, 46)], fill=2)
    d.rectangle((7, 41, 37, 42), fill=3)
    if frame == 0:
        d.polygon([(10, 28), (1, 12), (6, 10), (15, 27)], fill=1)
        d.polygon([(34, 28), (43, 12), (38, 10), (29, 27)], fill=1)
        d.rectangle((0, 8, 5, 11), fill=3)
        d.rectangle((38, 8, 43, 11), fill=3)
    else:
        d.polygon([(10, 28), (0, 38), (4, 42), (14, 32)], fill=1)
        d.polygon([(34, 28), (43, 38), (39, 42), (30, 32)], fill=1)
        d.rectangle((0, 39, 4, 43), fill=3)
        d.rectangle((39, 39, 43, 43), fill=3)
    d.rectangle((10, 47, 20, 56), fill=1)                                             # baggy trousers
    d.rectangle((24, 47, 34, 56), fill=1)
    d.line([(15, 48), (15, 56)], fill=2)
    d.line([(29, 48), (29, 56)], fill=2)
    d.rectangle((7, 56, 20, 59), fill=3)
    d.rectangle((24, 56, 37, 59), fill=3)
    return np.asarray(im, dtype=np.uint8)


def make_far():
    """48x16, drawn 2x: the two-peaked Vesuvius seen across the bay. 1 dark, 2 light, 3 lava."""
    im = Image.new("P", (48, 16), 0)
    d = ImageDraw.Draw(im)
    d.polygon([(0, 15), (7, 12), (15, 5), (18, 3), (21, 4), (23, 6), (26, 3), (29, 1), (32, 2), (39, 10), (47, 15)], fill=1)
    d.polygon([(23, 6), (26, 3), (29, 1), (32, 2), (39, 10), (47, 15), (30, 15), (28, 8)], fill=2)
    d.line([(29, 1), (30, 4), (29, 6)], fill=3)
    d.point((28, 0), fill=3)
    return np.asarray(im, dtype=np.uint8)


GLYPHS = {
    "S": ["01110", "10001", "10000", "01110", "00001", "10001", "01110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "I": ["01110", "00100", "00100", "00100", "00100", "00100", "01110"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "!": ["00100", "00100", "00100", "00100", "00100", "00000", "00100"],
}


def make_logo():
    """'SPIRITI!' as a 47x7 picture drawn 4x; game.c draws it twice for a shadow."""
    a = np.zeros((7, 47), dtype=np.uint8)
    for n, ch in enumerate("SPIRITI!"):
        for gy, row in enumerate(GLYPHS[ch]):
            for gx, bit in enumerate(row):
                a[gy, n * 6 + gx] = int(bit)
    return a


MAP_CELL, MAP_W, MAP_H = 4, 80, 40
COAST = [(0, 150), (30, 146), (56, 136), (76, 120), (96, 110), (130, 106), (170, 98), (210, 90), (236, 92),
         (256, 104), (276, 126), (296, 150), (319, 164)]


def make_map():
    """The Gulf of Naples, 80x40 drawn 4x: 1 beach, 2 land, 3 hills.

    North is up: the city climbs from the bay, Capo Posillipo closes it to the
    west and the Vesuvian coast to the east; Capri is on the horizon.
    """
    land = np.zeros((MAP_H, MAP_W), dtype=bool)
    for cx in range(MAP_W):
        x = cx * MAP_CELL + 2
        for (x0, y0), (x1, y1) in zip(COAST, COAST[1:]):
            if x0 <= x <= x1:
                t = (x - x0) / (x1 - x0)
                t = t * t * (3 - 2 * t)
                edge = y0 + (y1 - y0) * t + 3 * np.sin(cx * 0.55)
                land[:max(0, int(edge) // MAP_CELL), cx] = True
    for cy in range(MAP_H):
        for cx in range(MAP_W):
            if ((cx - 40) / 5.5) ** 2 + ((cy - 36.5) / 2.2) ** 2 < 1:
                land[cy, cx] = True

    def erode(m, n):
        for _ in range(n):
            e = m.copy()
            e[1:, :] &= m[:-1, :]
            e[:-1, :] &= m[1:, :]
            e[:, 1:] &= m[:, :-1]
            e[:, :-1] &= m[:, 1:]
            m = e
        return m

    grown = np.pad(land, 6, mode="edge")                 # the map's own edges are not a coast
    return (land.astype(np.uint8) + erode(grown, 1)[6:-6, 6:-6] + erode(grown, 5)[6:-6, 6:-6]).astype(np.uint8)


# --------------------------------------------------------------------------
# Scenes: a picture, three rows of ground tiles, a sky and 15 colours each
# --------------------------------------------------------------------------
GROUND_GREY = [(58, 56, 70), (104, 100, 112)]
SCENES = [
    dict(name="CENTRO", title="Centro Storico - Gesu Nuovo", pic=pic_centro, ground=".ko", spirits=("ghost0",),
         pal=[(16, 14, 24), (66, 64, 78), (100, 98, 114), (206, 200, 190), (182, 118, 74), (112, 56, 44),
              (26, 30, 54), (255, 214, 120), (255, 236, 150), (58, 56, 70), (104, 100, 112), (36, 96, 60),
              (120, 190, 96), (132, 134, 150), (246, 238, 220)],
         sky=((8, 10, 40), (62, 44, 96))),
    dict(name="MERGELLINA", title="Mergellina - Castel dell'Ovo", pic=pic_mergellina, ground="=ko", spirits=("ghost1",),
         pal=[(10, 12, 30), (52, 48, 98), (86, 74, 134), (214, 196, 160), (176, 140, 96), (255, 110, 50),
              (24, 30, 64), (255, 208, 110), (255, 240, 180), (60, 58, 80), (112, 108, 128), (10, 58, 124),
              (56, 122, 200), (150, 156, 176), (236, 240, 250)],
         sky=((6, 10, 44), (40, 60, 130))),
    dict(name="VOMERO", title="Vomero - Castel Sant'Elmo", pic=pic_vomero, ground=".ko", spirits=("ghost3",),
         pal=[(14, 14, 24), (120, 96, 60), (176, 146, 96), (220, 196, 150), (214, 150, 80), (190, 84, 70),
              (30, 30, 50), (255, 216, 120), (255, 240, 170), (56, 56, 68), (102, 100, 112), (24, 64, 46),
              (56, 112, 64), (136, 140, 156), (240, 234, 220)],
         sky=((8, 8, 38), (70, 50, 110))),
    dict(name="PORTO", title="Porto - Maschio Angioino", pic=pic_porto, ground=".qo", spirits=("ghost2",),
         pal=[(10, 10, 20), (58, 54, 62), (150, 126, 96), (196, 176, 140), (222, 120, 40), (186, 50, 54),
              (20, 26, 50), (255, 220, 120), (255, 246, 200), (52, 56, 70), (98, 104, 120), (10, 36, 90),
              (40, 100, 170), (150, 150, 160), (240, 240, 236)],
         sky=((4, 8, 36), (30, 50, 110))),
    dict(name="FUORIGROTTA", title="Fuorigrotta - lo stadio", pic=pic_fuorigrotta, ground=".ko", spirits=("ghost4",),
         pal=[(12, 14, 28), (70, 80, 100), (116, 128, 150), (170, 184, 204), (40, 110, 190), (90, 170, 240),
              (24, 28, 52), (255, 236, 150), (255, 252, 220), (54, 58, 66), (100, 106, 116), (30, 90, 60),
              (110, 180, 100), (136, 146, 164), (240, 246, 255)],
         sky=((6, 12, 44), (50, 70, 120))),
    dict(name="CAPODIMONTE", title="Capodimonte - la Reggia", pic=pic_capodimonte, ground=".oo", spirits=("ghost5",),
         pal=[(14, 12, 18), (70, 68, 76), (110, 106, 112), (214, 206, 190), (96, 66, 40), (168, 52, 44),
              (30, 22, 30), (255, 200, 110), (255, 232, 160), (60, 54, 50), (104, 96, 86), (22, 58, 40),
              (52, 104, 58), (140, 138, 144), (236, 228, 212)],
         sky=((10, 10, 36), (56, 50, 100))),
    dict(name="VILLA", title="Posillipo - Villa Doria d'Angri", pic=pic_villa, ground="...", spirits=("boss",),
         pal=None, sky=((22, 6, 40), (70, 110, 60))),
    dict(name="PLEBISCITO", title="Piazza del Plebiscito", pic=pic_plebiscito, ground=".ff", spirits=(),
         pal=[(16, 12, 20), (60, 56, 66), (128, 122, 124), (196, 190, 182), (150, 60, 40), (200, 60, 30),
              (30, 26, 44), (255, 200, 110), (255, 230, 150), (86, 82, 88), (140, 136, 138), (150, 24, 10),
              (255, 110, 20), (110, 114, 128), (236, 232, 222)],
         sky=((40, 6, 30), (170, 60, 24))),
    dict(name="LUNGOMARE", title="Lungomare", pic=None, ground="...", spirits=("ghost0",),
         pal=[(10, 12, 30), (60, 62, 96), (110, 114, 150), (170, 176, 204), (150, 96, 50), (214, 92, 70),
              (24, 30, 64), (255, 208, 110), (255, 240, 180), (60, 58, 80), (112, 108, 128), (10, 58, 124),
              (56, 122, 200), (150, 156, 176), (236, 240, 250)],
         sky=((6, 10, 44), (40, 60, 130))),
]
FAR_RGB = [(44, 44, 96), (80, 70, 130), (255, 110, 50)]

# Interface colour drawn as RGB565 (text backgrounds), so it needs a cell.
UI_NAVY = rgb565((10, 16, 52))

# District markers on the 320x160 map: six districts, the villa at Posillipo, the piazza.
HAUNT_XY = [(184, 66), (112, 92), (124, 50), (232, 72), (48, 100), (176, 22), (76, 112), (158, 88)]
FAR_ON_MAP = (224, 36)


# --------------------------------------------------------------------------
def main():
    DOCS.mkdir(exist_ok=True)
    out = ["#ifndef SPIRITI_NAPOLI97_ASSETS_H", "#define SPIRITI_NAPOLI97_ASSETS_H", "#include <stdint.h>",
           "/* Generated by tools/generate_assets.py; do not edit. No pointers: portable cartridges",
           " * are loaded at different addresses and game.c fills its descriptors at run time. */"]

    # ---- shared colours: interface, props, hunter, Fiat ----
    shared = {}
    props_pal, shared = place([rgb565(c) for c in PROP_RGB[1:]], {}, shared)
    props_pal = [0] + props_pal
    (ui_navy,), shared = place([UI_NAVY], {}, shared)
    sprites = {}
    for symbol, filename, size, crop, ramp in SPRITES:
        sprites[symbol] = convert_sprite(filename, size, crop, ramp)
    palettes = {}
    for symbol in ("hunter", "fiat"):
        inds, pal, _ = sprites[symbol]
        placed, shared = place(pal[1:], {}, shared)
        palettes[symbol] = [0] + placed
    # ---- each spirit against the shared colours ----
    ghost_cells = {}
    for symbol in ("ghost0", "ghost1", "ghost2", "ghost3", "ghost4", "ghost5", "boss"):
        inds, pal, _ = sprites[symbol]
        placed, own = place(pal[1:], shared, {})
        palettes[symbol] = [0] + placed
        ghost_cells[symbol] = own
    # ---- each scene against the shared colours and its own spirits ----
    scene_pals, sky, pictures = [], [], []
    for scene in SCENES:
        picture = scene["pic"]() if scene["pic"] else None
        if isinstance(picture, tuple):                   # the photograph brings its own colours
            picture, colours = picture
            scene["pal"] = colours + [(0, 0, 0)] * (15 - len(colours))
        elif picture is not None:
            picture = np.asarray(picture, dtype=np.uint8)
        taken = dict(shared)
        blocked = set()                                  # cells two of its spirits use differently
        for g in scene["spirits"]:
            for k, v in ghost_cells[g].items():
                if k in taken and taken[k] != v:
                    blocked.add(k)
                taken[k] = v
        for k in blocked:
            del taken[k]
        placed, own = place([rgb565(c) for c in scene["pal"]], taken, {}, blocked)
        if scene["name"] == "LUNGOMARE":
            far_pal, own = place([rgb565(c) for c in FAR_RGB], taken, own, blocked)
        scene_pals += [0] + placed
        sky += [rgb565(scene["sky"][0]), rgb565(scene["sky"][1])]
        scene["placed"] = [0] + placed
        scene["picture"] = picture
        for role, (want, got) in enumerate(zip(scene["pal"], placed), 1):
            if distance(rgb565(want), got) > 34:
                print(f"note: {scene['name']} {ROLE_NAMES[role]} {want} became {rgb888(got)}")
    far_pal = [0] + far_pal

    out.append(f"#define SN_UI_NAVY 0x{ui_navy:04X}")
    for symbol, _, size, _, _ in SPRITES:
        inds, _, _ = sprites[symbol]
        out.append(f"#define SN_{symbol.upper()}_W {size[0]}")
        out.append(f"#define SN_{symbol.upper()}_H {size[1]}")
        out.append(c_u16(f"sn_{symbol}_pal", palettes[symbol]))
        out.append(c_u8(f"sn_{symbol}_pixels", pack(inds, 4)))

    props = make_props()
    out.append(c_u16("sn_props_pal", props_pal))
    for name, inds in props.items():
        frames = 2 if name == "mark" else 1
        out.append(f"#define SN_{name.upper()}_W {inds.shape[1]}")
        out.append(f"#define SN_{name.upper()}_H {inds.shape[0] // frames}")
        out.append(c_u8(f"sn_{name}_pixels", pack(inds, 4)))

    out.append(f"#define SN_TILE_COUNT {len(TILES)}")
    for name, code in TILE_CODE.items():
        out.append(f"#define SN_T_{name} {code}")
    out.append(c_u8("sn_tiles", [v for _, t in TILES for v in pack(t, 4)]))

    out.append(f"#define SN_SCENE_COUNT {len(SCENES)}")
    out.append(f"#define SN_SCENE_COLS {SCENE_COLS}")
    out.append(f"#define SN_SCENE_ROWS {SCENE_ROWS}")

    def encode(rows):
        assert len(rows) == SCENE_ROWS and all(len(r) == SCENE_COLS for r in rows), rows
        return [TILE_CODE[CHARS[ch]] if CHARS[ch] else 0 for r in rows for ch in r]

    out.append(c_u8("sn_shore_map", encode(SHORE_ROWS)))
    out.append(c_u8("sn_road_map", encode(ROAD_ROWS)))
    out.append(c_u8("sn_ground", [TILE_CODE[CHARS[ch]] if CHARS[ch] else 0 for s in SCENES for ch in s["ground"]]))
    out.append(c_u16("sn_scene_pal", scene_pals))
    out.append(c_u16("sn_far_pal", far_pal))
    out.append(c_u16("sn_sky_pal", sky))

    out.append(f"#define SN_PIC_W {PIC_W}")
    sizes = {}
    for number, scene in enumerate(SCENES):
        if scene["picture"] is not None:
            data = encode_picture(scene["picture"])
            sizes[scene["name"]] = len(data)
            out.append(f"/* {scene['title']} */")
            out.append(c_u8(f"sn_pic{number}", data, per=24))
    far = make_far()
    logo = make_logo()
    gulf = make_map()
    pulci = [pulcinella(0), pulcinella(1)]
    for name, a in (("far", far), ("logo", logo), ("gulf", gulf), ("pulci0", pulci[0]), ("pulci1", pulci[1])):
        data = encode_picture(a)
        sizes[name] = len(data)
        out.append(f"#define SN_{name.upper()}_W {a.shape[1]}")
        out.append(f"#define SN_{name.upper()}_H {a.shape[0]}")
        out.append(c_u8(f"sn_{name}_pic", data, per=24))
    out.append(c_u16("sn_haunt_xy", [v for xy in HAUNT_XY for v in xy]))
    out.append(f"#define SN_MAP_FAR_X {FAR_ON_MAP[0]}")
    out.append(f"#define SN_MAP_FAR_Y {FAR_ON_MAP[1]}")
    out.append("#endif")
    OUT.write_text("\n".join(out) + "\n")

    # ---- previews ----
    def tile_image(t, pal):
        im = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        px = im.load()
        for y in range(16):
            for x in range(16):
                if t[y, x]:
                    px[x, y] = rgb888(pal[t[y, x]]) + (255,)
        return im

    def sprite_image(inds, pal, scale=1):
        h, w = inds.shape
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        for y in range(h):
            for x in range(w):
                if inds[y, x]:
                    im.putpixel((x, y), rgb888(pal[inds[y, x]]) + (255,))
        return im.resize((w * scale, h * scale), Image.Resampling.NEAREST) if scale > 1 else im

    def scene_image(scene):
        im = Image.new("RGBA", (320, 160), (0, 0, 0, 255))
        d = ImageDraw.Draw(im)
        top, low = scene["sky"]
        for band in range(8):
            c = tuple(top[i] + (low[i] - top[i]) * band // 7 for i in range(3))
            d.rectangle((0, band * 20, 319, band * 20 + 19), fill=c)
        if scene["picture"] is not None:
            im.alpha_composite(sprite_image(scene["picture"], scene["placed"], 2), (0, 0))
        rows = SHORE_ROWS if scene["name"] == "LUNGOMARE" else ["." * 20] * 7 + [ch * 20 for ch in scene["ground"]]
        for ty, row in enumerate(rows):
            for tx, ch in enumerate(row):
                if ch == "=" and tx % 4 == 0:
                    ch = "I"
                if CHARS[ch]:
                    im.alpha_composite(tile_image(TILES[TILE_CODE[CHARS[ch]] - 1][1], scene["placed"]), (tx * 16, ty * 16))
        return im

    pulci_pal = [0, 0xFFFF, rgb565((176, 186, 214)), rgb565((8, 8, 12)), 0xF800]
    sheet = Image.new("RGBA", (640, 5 * 180), (4, 8, 20, 255))
    d = ImageDraw.Draw(sheet)
    for i, scene in enumerate(SCENES):
        im = scene_image(scene)
        x, y = (i % 2) * 320, (i // 2) * 180
        if scene["name"] == "PLEBISCITO":
            im.alpha_composite(sprite_image(pulci[0], pulci_pal, 2), (116, 8))
            im.alpha_composite(sprite_image(sprites["fiat"][0], palettes["fiat"]), (40, 118))
            im.alpha_composite(sprite_image(props["rooftrap"], props_pal), (58, 110))
        elif scene["spirits"]:
            ghost = scene["spirits"][-1]
            im.alpha_composite(sprite_image(sprites[ghost][0], palettes[ghost]), (200 if ghost != "boss" else 112, 24))
            im.alpha_composite(sprite_image(sprites["hunter"][0], palettes["hunter"]), (30, 102))
            im.alpha_composite(sprite_image(props["trap"], props_pal), (180, 132))
        sheet.alpha_composite(im, (x, y))
        d.text((x + 4, y + 164), f"{scene['title']}  ({sizes.get(scene['name'], 0)} bytes)", fill=(255, 255, 255))
    sheet.alpha_composite(sprite_image(gulf, [0, rgb565((226, 196, 130)), rgb565((46, 120, 66)), rgb565((70, 150, 80))], 4), (320, 720))
    sheet.convert("RGB").save(DOCS / "scenes.png", optimize=True)

    art = Image.new("RGBA", (640, 260), (16, 20, 34, 255))
    x = 6
    for symbol, _, size, _, _ in SPRITES:
        im = sprite_image(sprites[symbol][0], palettes[symbol], 2)
        if x + im.width > 636:
            break
        art.alpha_composite(im, (x, 8))
        x += im.width + 6
    x = 6
    for name, inds in props.items():
        im = sprite_image(inds, props_pal, 2)
        art.alpha_composite(im, (x, 260 - im.height - 4))
        x += im.width + 8
    art.alpha_composite(sprite_image(pulci[0], pulci_pal, 2), (430, 134))
    art.alpha_composite(sprite_image(pulci[1], pulci_pal, 2), (530, 134))
    art.convert("RGB").save(DOCS / "sprites.png", optimize=True)
    for stale in ("tiles.png", "map.png"):
        (DOCS / stale).unlink(missing_ok=True)

    art_bytes = (len(TILES) * 128 + sum(s[0] * s[1] // 2 for _, _, s, _, _ in SPRITES)
                 + sum(v.size // 2 for v in props.values()) + sum(sizes.values()))
    print("pictures:", ", ".join(f"{k} {v}" for k, v in sizes.items()))
    print(f"{OUT.name}: {len(TILES)} tiles, {len(SCENES)} scenes, {len(shared)} shared cells, {art_bytes} bytes of art")


if __name__ == "__main__":
    main()
