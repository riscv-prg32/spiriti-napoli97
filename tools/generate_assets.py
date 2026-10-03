#!/usr/bin/env python3
"""Generate assets.h for Spiriti! Napoli '97.

Everything the cartridge draws is palette-indexed:

- the Fiat, the hunter, six spirits and the Vesuvius boss are converted from
  the pixel-art sources in assets-src/ to 4-bpp sprites;
- the districts are built from a bank of 16x16 4-bpp tiles drawn here pixel
  by pixel. A tile pixel is a *role* (wall, window, water...), and each
  district gives the roles its own 16 colours, so one bank serves them all;
- props, the logo, the far Vesuvius and the dispatch-map coastline are drawn
  here too.

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
from PIL import Image, ImageDraw

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
    # Dispatch-map markers, one frame each: a haunted district and a cleared one.
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
# Tiles: 16x16, a pixel is a role
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


def t_wall():
    t = blank(WM)
    R(t, 0, 15, 15, 15, WD)
    P(t, [(3, 4), (4, 4), (11, 9), (12, 9), (13, 9), (6, 12), (1, 7)], WD)
    P(t, [(8, 2), (9, 2), (2, 10), (3, 10), (13, 5), (14, 5)], WL)
    return t


def window(t, lit):
    R(t, 3, 2, 12, 13, A1)
    R(t, 4, 3, 11, 12, WIN_L if lit else WIN_D)
    if lit:
        R(t, 7, 3, 8, 12, A1)
        R(t, 4, 7, 11, 7, A1)
        P(t, [(5, 4), (9, 4), (5, 9), (9, 9)], GLOW)
    else:
        for y in range(4, 12, 2):
            R(t, 4, y, 11, y, A1)
        R(t, 7, 3, 8, 12, OUT_)
    R(t, 2, 14, 13, 14, WL)
    R(t, 2, 1, 13, 1, WL)
    return t


def t_balcony():
    t = t_wall()
    R(t, 4, 0, 11, 9, A1)
    R(t, 5, 0, 10, 8, WIN_L)
    R(t, 7, 0, 8, 8, A1)
    R(t, 0, 9, 15, 9, HI)
    for x in range(0, 16, 2):
        R(t, x, 10, x, 13, MET)
    for x in range(1, 16, 2):
        R(t, x, 10, x, 13, OUT_)
    R(t, 0, 14, 15, 15, WD)
    P(t, [(1, 8), (2, 7), (13, 8), (14, 7), (12, 7)], A2)
    P(t, [(1, 7), (3, 8), (14, 8), (13, 7)], N2)
    return t


def t_cornice():
    t = blank()
    for x in range(16):
        t[4, x] = A2
        t[5, x] = A2 if x % 4 else OUT_
    R(t, 0, 6, 15, 7, WL)
    R(t, 0, 8, 15, 8, WD)
    R(t, 0, 9, 15, 15, WM)
    for x in range(1, 16, 4):
        R(t, x, 10, x + 1, 11, WD)
    R(t, 0, 15, 15, 15, WD)
    return t


def t_door_top():
    t = t_wall()
    for y in range(16):
        for x in range(16):
            d = ((x - 7.5) ** 2 + (y - 15.5) ** 2) ** 0.5
            if d < 6.2:
                t[y, x] = OUT_
            elif d < 8.2:
                t[y, x] = WL if (x + y) % 3 else WD
    R(t, 7, 6, 8, 8, HI)
    P(t, [(6, 12), (9, 12), (7, 11), (8, 11)], WIN_D)
    return t


def t_door_bot():
    t = t_wall()
    R(t, 1, 0, 14, 13, WL)
    R(t, 2, 0, 13, 13, A1)
    R(t, 7, 0, 8, 13, OUT_)
    for y in (3, 8):
        R(t, 3, y, 6, y, OUT_)
        R(t, 9, y, 12, y, OUT_)
    P(t, [(6, 6), (9, 6)], GLOW)
    R(t, 0, 14, 15, 15, GL)
    R(t, 0, 15, 15, 15, GD)
    return t


def t_plinth():
    t = blank(WD)
    R(t, 0, 0, 15, 1, WL)
    R(t, 0, 2, 15, 2, WM)
    R(t, 0, 8, 15, 8, OUT_)
    R(t, 0, 15, 15, 15, OUT_)
    for x, y0, y1 in ((5, 3, 7), (13, 3, 7), (1, 9, 14), (9, 9, 14)):
        R(t, x, y0, x, y1, OUT_)
    P(t, [(2, 4), (8, 5), (4, 11), (12, 12)], WM)
    return t


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


def t_lattice():
    t = blank()
    R(t, 3, 0, 4, 15, MET)
    R(t, 11, 0, 12, 15, MET)
    for i in range(8):
        t[i, 4 + i] = A1
        t[i, 11 - i] = A1
        t[8 + i, 4 + i] = A1
        t[8 + i, 11 - i] = A1
    R(t, 3, 0, 12, 0, A1)
    R(t, 3, 8, 12, 8, A1)
    return t


def t_crate():
    t = blank(A1)
    R(t, 0, 0, 15, 0, OUT_)
    R(t, 0, 15, 15, 15, OUT_)
    R(t, 0, 0, 0, 15, OUT_)
    R(t, 15, 0, 15, 15, OUT_)
    R(t, 1, 1, 14, 2, WL)
    R(t, 1, 13, 14, 14, WD)
    for i in range(3, 13):
        t[i, i] = WD
        t[i, 15 - i] = WD
    P(t, [(2, 4), (13, 4), (2, 11), (13, 11)], HI)
    return t


def t_container():
    t = blank(A2)
    for x in range(1, 15, 3):
        R(t, x, 1, x, 14, OUT_)
        R(t, x + 1, 1, x + 1, 14, WL)
    R(t, 0, 0, 15, 0, OUT_)
    R(t, 0, 15, 15, 15, OUT_)
    R(t, 5, 5, 10, 9, HI)
    R(t, 6, 6, 9, 8, A2)
    return t


def t_hull():
    t = blank(WD)
    R(t, 0, 0, 15, 1, HI)
    R(t, 0, 2, 15, 2, MET)
    R(t, 0, 11, 15, 13, A2)
    R(t, 0, 14, 15, 15, OUT_)
    P(t, [(2, 5), (7, 5), (12, 5), (4, 8), (9, 8), (14, 8)], MET)
    return t


def t_cabin():
    t = blank()
    R(t, 0, 4, 15, 4, MET)
    for x in (2, 8, 14):
        R(t, x, 4, x, 7, MET)
    R(t, 0, 8, 15, 15, WL)
    R(t, 0, 8, 15, 8, HI)
    R(t, 0, 15, 15, 15, OUT_)
    for x in (2, 7, 12):
        R(t, x, 10, x + 2, 12, WIN_L)
        t[10, x] = GLOW
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


def t_panel():
    t = blank(WM)
    R(t, 1, 1, 14, 14, WD)
    R(t, 2, 2, 13, 13, WL)
    R(t, 3, 3, 12, 12, WM)
    R(t, 3, 12, 12, 12, WD)
    R(t, 12, 3, 12, 12, WD)
    R(t, 6, 6, 9, 9, WL)
    R(t, 7, 7, 8, 8, GLOW)
    return t


def t_column(capital):
    t = blank(WD)
    R(t, 3, 0, 12, 15, WM)
    for x in (4, 7, 10):
        R(t, x, 0, x, 15, WL)
    R(t, 12, 0, 12, 15, OUT_)
    if capital:
        R(t, 0, 0, 15, 3, WM)
        R(t, 0, 0, 15, 0, HI)
        R(t, 0, 3, 15, 3, OUT_)
        R(t, 1, 4, 14, 7, WL)
        R(t, 1, 7, 14, 7, WD)
        P(t, [(2, 5), (3, 5), (12, 5), (13, 5), (7, 5), (8, 5)], GLOW)
    return t


def t_curtain(swag):
    t = blank(A2)
    for x in range(16):
        if x % 4 == 0:
            R(t, x, 0, x, 15, A1)
        if x % 4 == 1:
            R(t, x, 0, x, 15, OUT_)
        if x % 4 == 3:
            R(t, x, 0, x, 15, HI if swag else A2)
    if swag:
        t[:] = A2
        R(t, 0, 0, 15, 1, GLOW)
        R(t, 0, 2, 15, 2, OUT_)
        for x in range(16):
            depth = 7 + int(4 * abs(((x % 8) - 3.5) / 3.5) ** 1.5)
            R(t, x, depth, x, 15, T_)
            t[depth - 1, x] = GLOW
            if x % 2:
                t[depth, x] = GLOW
        for x in (2, 5, 10, 13):
            R(t, x, 3, x, 6, A1)
        t[t == T_] = WD
    return t


def t_portrait():
    t = t_panel()
    R(t, 2, 1, 13, 14, GLOW)
    R(t, 3, 2, 12, 13, OUT_)
    R(t, 6, 4, 9, 8, WL)
    R(t, 5, 9, 10, 13, MET)
    R(t, 7, 9, 8, 10, WL)
    P(t, [(6, 6), (9, 6)], WIN_L)
    P(t, [(7, 8), (8, 8)], WD)
    R(t, 6, 3, 9, 3, WD)
    return t


def t_parquet():
    t = blank(GD)
    for y in range(16):
        for x in range(16):
            if (x + y) % 8 == 0 and (x // 8 + y // 8) % 2 == 0:
                t[y, x] = GL
            if (x - y) % 8 == 0 and (x // 8 + y // 8) % 2 == 1:
                t[y, x] = GL
    R(t, 0, 0, 15, 0, GL)
    return t


def t_chandelier():
    t = blank()
    R(t, 7, 0, 8, 6, MET)
    R(t, 2, 9, 13, 9, GLOW)
    R(t, 4, 7, 11, 7, GLOW)
    R(t, 6, 6, 9, 10, GLOW)
    P(t, [(7, 11), (8, 11), (7, 12)], GLOW)
    for x in (2, 5, 10, 13):
        R(t, x, 6, x, 8, HI)
        t[5, x] = WIN_L
        t[4, x] = GLOW
    return t


def t_tuff():
    t = blank(WM)
    R(t, 0, 7, 15, 7, WD)
    R(t, 0, 15, 15, 15, WD)
    R(t, 5, 0, 5, 6, WD)
    R(t, 12, 8, 12, 14, WD)
    R(t, 0, 8, 0, 14, WD)
    P(t, [(1, 1), (2, 1), (7, 2), (8, 9), (9, 9), (14, 10), (10, 3)], WL)
    P(t, [(3, 4), (9, 5), (4, 11), (6, 12), (14, 2)], OUT_)
    return t


def t_dark():
    t = blank(OUT_)
    P(t, [(2, 3), (9, 6), (13, 12), (5, 13), (11, 1)], WD)
    return t


def t_arch(right):
    t = t_tuff()
    for y in range(16):
        for x in range(16):
            d = ((x - 15.5) ** 2 + (y - 15.5) ** 2) ** 0.5
            if d < 13.2:
                t[y, x] = OUT_
            elif d < 15.4:
                t[y, x] = WL if (x * 2 + y) % 5 else WD
    return t[:, ::-1].copy() if right else t


def t_niche():
    t = t_dark()
    for y in range(16):
        for x in range(16):
            d = ((x - 7.5) ** 2 + (y - 6) ** 2) ** 0.5
            if 3.2 < d < 5.2:
                t[y, x] = WD
    R(t, 7, 8, 8, 13, HI)
    R(t, 7, 5, 8, 7, GLOW)
    P(t, [(7, 4), (8, 3)], WIN_L)
    P(t, [(7, 6)], HI)
    R(t, 5, 14, 10, 15, MET)
    return t


def t_skulls():
    t = t_dark()
    for cx in (3, 10):
        R(t, cx, 5, cx + 4, 9, HI)
        P(t, [(cx, 5), (cx + 4, 5)], OUT_)
        P(t, [(cx + 1, 7), (cx + 3, 7)], OUT_)
        R(t, cx + 1, 10, cx + 3, 11, MET)
        P(t, [(cx + 2, 9)], OUT_)
    R(t, 0, 12, 15, 13, WM)
    R(t, 0, 14, 15, 15, WD)
    return t


def t_statue(top):
    t = t_dark()
    if top:
        R(t, 6, 6, 9, 11, MET)
        R(t, 6, 6, 7, 10, HI)
        R(t, 5, 5, 10, 6, WD)
        R(t, 4, 12, 11, 15, MET)
        R(t, 4, 12, 5, 15, HI)
        P(t, [(7, 8), (9, 8)], OUT_)
    else:
        R(t, 4, 0, 11, 10, MET)
        for x in (5, 8, 10):
            R(t, x, 0, x, 10, HI if x == 5 else WD)
        R(t, 2, 6, 4, 8, MET)
        R(t, 2, 11, 13, 15, WM)
        R(t, 2, 11, 13, 11, WL)
        R(t, 2, 15, 13, 15, WD)
    return t


def t_flag():
    t = blank(GD)
    R(t, 0, 0, 15, 0, GL)
    R(t, 0, 8, 15, 8, GL)
    R(t, 4, 1, 4, 7, GL)
    R(t, 12, 9, 12, 15, GL)
    P(t, [(8, 4), (9, 4), (2, 12), (14, 3)], OUT_)
    return t


def t_stand():
    t = blank(WD)
    spots = [(1, 1, A2), (4, 2, HI), (7, 1, WIN_L), (10, 2, A2), (13, 1, HI), (2, 6, HI), (6, 5, A2), (9, 6, WIN_L),
             (12, 5, HI), (15, 6, A2), (0, 10, WIN_L), (3, 9, A2), (8, 10, HI), (11, 9, A2), (14, 10, WIN_L),
             (1, 14, A2), (5, 13, HI), (10, 14, A2), (13, 13, HI)]
    for y in (3, 7, 11, 15):
        R(t, 0, y, 15, y, WM)
    for x, y, c in spots:
        t[y, x] = c
    return t


def t_flood(pole):
    t = blank()
    R(t, 7, 0, 8, 15, MET)
    if not pole:
        R(t, 1, 2, 14, 10, MET)
        R(t, 1, 2, 14, 2, HI)
        for y in (4, 7):
            for x in (3, 6, 9, 12):
                R(t, x, y, x + 1, y + 1, GLOW)
                t[y, x] = HI
    else:
        P(t, [(6, 4), (9, 4), (6, 12), (9, 12)], MET)
    return t


def t_fence():
    t = blank()
    R(t, 0, 0, 15, 0, HI)
    R(t, 0, 15, 15, 15, MET)
    for i in range(16):
        if i % 4 == 0:
            R(t, i, 1, i, 14, MET)
        for j in range(1, 15):
            if (i + j) % 4 == 0 and (i - j) % 2 == 0:
                t[j, i] = MET
    return t


def t_rock(rim):
    t = blank(WD)
    P(t, [(1, 2), (2, 2), (2, 3), (9, 5), (10, 5), (10, 6), (4, 10), (5, 10), (13, 12), (14, 12)], WM)
    P(t, [(1, 1), (9, 4), (4, 9), (13, 11)], WL)
    P(t, [(6, 1), (6, 2), (7, 3), (12, 8), (11, 9), (11, 10), (2, 13), (3, 14)], OUT_)
    P(t, [(7, 4), (8, 5), (12, 9), (3, 15)], GLOW)
    if rim:
        heights = (9, 7, 6, 8, 5, 3, 4, 6, 8, 7, 4, 2, 3, 6, 8, 10)
        for x, top in enumerate(heights):
            R(t, x, 0, x, top - 1, T_)
            t[top, x] = WL
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
    ("WALL", t_wall()), ("WIN_LIT", window(t_wall(), True)), ("WIN_DARK", window(t_wall(), False)),
    ("BALCONY", t_balcony()), ("CORNICE", t_cornice()), ("DOOR_TOP", t_door_top()), ("DOOR_BOT", t_door_bot()),
    ("PLINTH", t_plinth()), ("COBBLE", t_cobble()), ("KERB", t_kerb()), ("WATER", t_water(0)), ("WATER_B", t_water(1)),
    ("SHORE", t_shore()), ("BALUSTRADE", t_balustrade(False)), ("PILLAR", t_balustrade(True)),
    ("LATTICE", t_lattice()), ("JIB", t_lattice().T.copy()), ("CRATE", t_crate()), ("CONTAINER", t_container()),
    ("HULL", t_hull()), ("CABIN", t_cabin()), ("QUAY", t_quay()), ("PANEL", t_panel()),
    ("COLUMN", t_column(False)), ("CAPITAL", t_column(True)), ("CURTAIN", t_curtain(False)), ("SWAG", t_curtain(True)),
    ("PORTRAIT", t_portrait()), ("PARQUET", t_parquet()), ("CHANDELIER", t_chandelier()), ("TUFF", t_tuff()),
    ("DARK", t_dark()), ("ARCH_L", t_arch(False)), ("ARCH_R", t_arch(True)), ("NICHE", t_niche()),
    ("SKULLS", t_skulls()), ("STATUE_T", t_statue(True)), ("STATUE_B", t_statue(False)), ("FLAG", t_flag()),
    ("STAND", t_stand()), ("FLOOD", t_flood(False)), ("POLE", t_flood(True)), ("FENCE", t_fence()),
    ("ROCK", t_rock(False)), ("RIM", t_rock(True)), ("ASPHALT", t_asphalt(0)), ("DASH", t_asphalt(1)),
    ("EDGE", t_asphalt(2)), ("MOON", t_moon()),
]
TILE_CODE = {name: i + 1 for i, (name, _) in enumerate(TILES)}       # 0 = nothing

CHARS = {
    ".": 0, "W": "WALL", "l": "WIN_LIT", "d": "WIN_DARK", "b": "BALCONY", "c": "CORNICE", "A": "DOOR_TOP",
    "D": "DOOR_BOT", "p": "PLINTH", "o": "COBBLE", "k": "KERB", "~": "WATER", "s": "SHORE", "=": "BALUSTRADE",
    "I": "PILLAR", "#": "LATTICE", "-": "JIB", "x": "CRATE", "C": "CONTAINER", "H": "HULL", "h": "CABIN",
    "q": "QUAY", "P": "PANEL", "|": "COLUMN", "T": "CAPITAL", "U": "CURTAIN", "S": "SWAG", "R": "PORTRAIT",
    "/": "PARQUET", "*": "CHANDELIER", "t": "TUFF", " ": "DARK", "(": "ARCH_L", ")": "ARCH_R", "n": "NICHE",
    "u": "SKULLS", "1": "STATUE_T", "2": "STATUE_B", "f": "FLAG", "g": "STAND", "F": "FLOOD", "i": "POLE",
    "+": "FENCE", "r": "ROCK", "^": "RIM", "a": "ASPHALT", "_": "DASH", "e": "EDGE", "O": "MOON",
}

# --------------------------------------------------------------------------
# Districts: 20x10 maps and one palette each
# --------------------------------------------------------------------------
SCENES = [
    # 0 Centro Storico: stucco palazzi and an alley of lit windows
    dict(name="CENTRO", ghosts=("ghost0",), far=False, rows=[
        "....................",
        "ccccccc.cccccc.ccccc",
        "WlWdWlW.WdWlWW.WlWdW",
        "WbWWWbW.WbWWbW.WWbWW",
        "WWdWlWW.WWlWdW.WdWlW",
        "WlWWWdW.WdWWWW.WWWWW",
        "WWAWWWW.WWWAWW.WAWWl",
        "ppDppppkpppDppkpDppp",
        "kkkkkkkkkkkkkkkkkkkk",
        "oooooooooooooooooooo"],
         pal=[(18, 14, 26), (92, 56, 44), (176, 112, 72), (224, 168, 110), (44, 92, 84), (188, 72, 60),
              (30, 34, 58), (255, 214, 120), (255, 244, 190), (58, 56, 70), (104, 100, 112), (36, 96, 60),
              (120, 190, 96), (120, 124, 140), (246, 236, 214)],
         sky=((8, 10, 40), (62, 44, 96)), far_pal=[(40, 36, 70), (70, 60, 100), (255, 120, 60)]),
    # 1 Mergellina: the lungomare, the bay and the Vesuvius
    dict(name="MERGELLINA", ghosts=("ghost0", "ghost1"), far=True, rows=[
        "................O...",
        "....................",
        "....................",
        "....................",
        "ssssssssssssssssssss",
        "~~~~~~~~~~~~~~~~~~~~",
        "~~~~~~~~~~~~~~~~~~~~",
        "I===I===I===I===I===",
        "kkkkkkkkkkkkkkkkkkkk",
        "oooooooooooooooooooo"],
         pal=[(10, 12, 30), (60, 62, 96), (110, 114, 150), (170, 176, 204), (150, 96, 50), (214, 92, 70),
              (24, 30, 64), (255, 208, 110), (255, 240, 180), (60, 58, 80), (112, 108, 128), (10, 58, 124),
              (56, 122, 200), (150, 156, 176), (236, 240, 250)],
         sky=((6, 10, 44), (40, 60, 130)), far_pal=[(44, 44, 96), (80, 70, 130), (255, 110, 50)]),
    # 2 Vomero: a haunted palazzo interior, gold panels and red curtains
    dict(name="VOMERO", ghosts=("ghost3",), far=False, rows=[
        "SSSSSSSSSSSSSSSSSSSS",
        "UTPP*PPTUUTPP*PPTUPP",
        "U|PRPPR|UU|PRPPR|UPR",
        "U|PPPPP|UU|PPPPP|UPP",
        "U|PRPPR|UU|PRPPR|UPR",
        "U|PPPPP|UU|PPPPP|UPP",
        "U|PPPPP|UU|PPPPP|UPP",
        "pppppppppppppppppppp",
        "////////////////////",
        "////////////////////"],
         pal=[(22, 10, 14), (96, 60, 20), (170, 118, 34), (226, 178, 70), (112, 16, 28), (178, 30, 40),
              (40, 26, 30), (120, 230, 255), (255, 226, 130), (74, 40, 26), (128, 78, 42), (30, 60, 50),
              (90, 140, 100), (150, 140, 130), (255, 240, 200)],
         sky=((30, 10, 20), (60, 20, 30)), far_pal=[(40, 20, 30), (70, 40, 50), (255, 120, 60)]),
    # 3 Porto: cranes, containers and a liner at the quay
    dict(name="PORTO", ghosts=("ghost2",), far=False, rows=[
        "..O.................",
        ".------.............",
        ".#...............hh.",
        ".#..........hhhhhhh.",
        ".#.......HHHHHHHHHHH",
        ".#..CC...HHHHHHHHHHH",
        ".#.xCCx.~~~~~~~~~~~~",
        "x#xxCCxx~~~~~~~~~~~~",
        "qqqqqqqqqqqqqqqqqqqq",
        "oooooooooooooooooooo"],
         pal=[(8, 12, 26), (26, 40, 84), (60, 80, 130), (210, 216, 230), (222, 120, 40), (186, 50, 54),
              (20, 26, 50), (255, 220, 120), (255, 246, 200), (52, 56, 70), (98, 104, 120), (10, 36, 90),
              (40, 100, 170), (128, 136, 152), (240, 244, 252)],
         sky=((4, 8, 36), (30, 50, 110)), far_pal=[(30, 34, 80), (60, 60, 110), (255, 110, 50)]),
    # 4 Fuorigrotta: the stadium under its floodlights
    dict(name="FUORIGROTTA", ghosts=("ghost4",), far=False, rows=[
        "..F..............F..",
        "..i..............i..",
        "..i.cccccccccccc.i..",
        "..icgggggggggggggci.",
        ".cgggggggggggggggggc",
        "cggggggggggggggggggg",
        "WAWWAWWAWWAWWAWWAWWA",
        "p+p++p++p++p++p++p++",
        "kkkkkkkkkkkkkkkkkkkk",
        "oooooooooooooooooooo"],
         pal=[(12, 14, 28), (48, 60, 86), (96, 112, 140), (150, 168, 196), (40, 110, 190), (90, 170, 240),
              (24, 28, 52), (255, 236, 150), (255, 252, 220), (54, 58, 66), (100, 106, 116), (30, 90, 60),
              (110, 180, 100), (136, 146, 164), (240, 246, 255)],
         sky=((6, 12, 44), (50, 70, 120)), far_pal=[(30, 34, 80), (60, 60, 110), (255, 110, 50)]),
    # 5 Capodimonte: tuff catacombs, candles and skulls
    dict(name="CAPODIMONTE", ghosts=("ghost5",), far=False, rows=[
        "tttttttttttttttttttt",
        "t()tt()tt()tt()tt()t",
        "t  tt  tt  tt  tt  t",
        "t1 ttn tt 1ttn tt1 t",
        "t2 ttu tt 2ttu tt2 t",
        "tttttttttttttttttttt",
        "tnttuuttnttuuttnttut",
        "pppppppppppppppppppp",
        "ffffffffffffffffffff",
        "ffffffffffffffffffff"],
         pal=[(14, 10, 12), (70, 50, 36), (122, 92, 60), (170, 136, 90), (90, 60, 30), (140, 40, 30),
              (30, 20, 24), (255, 150, 50), (255, 226, 120), (40, 34, 34), (78, 66, 60), (30, 50, 40),
              (80, 110, 80), (128, 122, 116), (232, 222, 200)],
         sky=((20, 12, 10), (40, 24, 16)), far_pal=[(40, 20, 30), (70, 40, 50), (255, 120, 60)]),
    # 6 Vesuvio: the crater, where the last apparition waits
    dict(name="VESUVIO", ghosts=("boss",), far=False, rows=[
        "....................",
        "....................",
        "^..................^",
        "r^^..............^^r",
        "rrr^............^rrr",
        "rrrr^^........^^rrrr",
        "rrrrrr^^^^^^^^rrrrrr",
        "rrrr~~~~~~~~~~~~rrrr",
        "^^^^^^^^^^^^^^^^^^^^",
        "rrrrrrrrrrrrrrrrrrrr"],
         pal=[(14, 12, 22), (40, 42, 60), (72, 74, 98), (112, 112, 136), (120, 40, 20), (200, 60, 30),
              (30, 14, 20), (255, 140, 40), (255, 210, 80), (40, 20, 24), (80, 40, 40), (196, 36, 10),
              (255, 150, 30), (120, 100, 100), (255, 236, 170)],
         sky=((36, 6, 26), (176, 52, 20)), far_pal=[(40, 20, 30), (70, 40, 50), (255, 120, 60)]),
]
SCENE_COLS, SCENE_ROWS = 20, 10

# The drive along the lungomare uses the Mergellina palette.
ROAD_ROWS = ["................O...", "....................", "....................", "ssssssssssssssssssss",
             "~~~~~~~~~~~~~~~~~~~~", "I===I===I===I===I===", "kkkkkkkkkkkkkkkkkkkk", "eeeeeeeeeeeeeeeeeeee",
             "____________________", "____________________"]

# Interface colours that are drawn as RGB565 (text backgrounds) and so need a cell.
UI_NAVY = rgb565((10, 16, 52))


# --------------------------------------------------------------------------
# Far Vesuvius, logo and the dispatch map
# --------------------------------------------------------------------------
def make_far():
    """96x32, 2 bpp: the two-peaked Vesuvius seen across the bay."""
    im = Image.new("P", (96, 32), 0)
    d = ImageDraw.Draw(im)
    d.polygon([(0, 31), (14, 24), (30, 10), (36, 6), (42, 9), (47, 12), (52, 7), (58, 3), (64, 5), (78, 20), (95, 31)], fill=1)
    d.polygon([(47, 12), (52, 7), (58, 3), (64, 5), (78, 20), (95, 31), (60, 31), (56, 16)], fill=2)
    d.line([(58, 3), (60, 8), (58, 13), (61, 18)], fill=3)
    d.point([(57, 2), (59, 1), (60, 3)], fill=3)
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
    """'SPIRITI!' in 4x4 blocks, 1 bpp, 192x28; game.c draws it twice for a shadow."""
    scale = 4
    a = np.zeros((7 * scale, 8 * 6 * scale), dtype=np.uint8)
    for n, ch in enumerate("SPIRITI!"):
        for gy, row in enumerate(GLYPHS[ch]):
            for gx, bit in enumerate(row):
                if bit == "1":
                    px, py = (n * 6 + gx) * scale + 2, gy * scale
                    a[py:py + scale, px:px + scale] = 1
    return a


MAP_CELL, MAP_W, MAP_H = 4, 80, 40


COAST = [(0, 150), (30, 146), (56, 136), (76, 120), (96, 110), (130, 106), (170, 98), (210, 90), (236, 92),
         (256, 104), (276, 126), (296, 150), (319, 164)]


def make_map():
    """The Gulf of Naples as horizontal runs of 4x4 cells.

    North is up: the city climbs from the bay, Capo Posillipo closes it to the
    west and the Vesuvian coast to the east. Three nested masks (beach, land,
    hills) each hold up to MAP_RUNS (start, end) cell pairs per row.
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
    for cy in range(MAP_H):                              # Capri on the horizon
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
    layers = [land, erode(grown, 1)[6:-6, 6:-6], erode(grown, 5)[6:-6, 6:-6]]
    flat = []
    for mask in layers:
        for y in range(MAP_H):
            runs = []
            x = 0
            while x < MAP_W:
                if mask[y, x]:
                    x0 = x
                    while x < MAP_W and mask[y, x]:
                        x += 1
                    runs.append((x0, x))
                else:
                    x += 1
            assert len(runs) <= 3, (y, runs)
            for i in range(3):
                flat += list(runs[i]) if i < len(runs) else [0, 0]
    return flat, layers


# District markers on the 320x160 map, in playfield pixels.
HAUNT_XY = [(184, 66), (112, 92), (124, 50), (232, 72), (48, 104), (176, 22)]
VESUVIO_XY = (282, 44)
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
    # ---- each district against the shared colours and its own spirits ----
    scene_pals, far_pals, sky = [], [], []
    for scene in SCENES:
        taken = dict(shared)
        blocked = set()                                  # cells two of its spirits use differently
        for g in scene["ghosts"]:
            for k, v in ghost_cells[g].items():
                if k in taken and taken[k] != v:
                    blocked.add(k)
                taken[k] = v
        for k in blocked:
            del taken[k]
        placed, own = place([rgb565(c) for c in scene["pal"]], taken, {}, blocked)
        far, own = place([rgb565(c) for c in scene["far_pal"]], taken, own, blocked)
        scene_pals += [0] + placed
        far_pals += [0] + far
        sky += [rgb565(scene["sky"][0]), rgb565(scene["sky"][1])]
        scene["placed"] = [0] + placed
        for role, (want, got) in enumerate(zip(scene["pal"], placed), 1):
            if distance(rgb565(want), got) > 34:
                print(f"note: {scene['name']} {ROLE_NAMES[role]} {want} became {rgb888(got)}")
        scene["far_placed"] = [0] + far

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

    out.append(c_u8("sn_scene_maps", [v for s in SCENES for v in encode(s["rows"])]))
    out.append(c_u8("sn_road_map", encode(ROAD_ROWS)))
    out.append(c_u16("sn_scene_pal", scene_pals))
    out.append(c_u16("sn_far_pal", far_pals))
    out.append(c_u16("sn_sky_pal", sky))

    far = make_far()
    out.append(f"#define SN_FAR_W {far.shape[1]}")
    out.append(f"#define SN_FAR_H {far.shape[0]}")
    out.append(c_u8("sn_far_pixels", pack(far, 2)))
    logo = make_logo()
    out.append(f"#define SN_LOGO_W {logo.shape[1]}")
    out.append(f"#define SN_LOGO_H {logo.shape[0]}")
    out.append(c_u8("sn_logo_pixels", pack(logo, 1)))

    map_runs, map_layers = make_map()
    out.append(f"#define SN_MAP_CELL {MAP_CELL}")
    out.append(f"#define SN_MAP_ROWS {MAP_H}")
    out.append("#define SN_MAP_RUNS 3")
    out.append("#define SN_MAP_LAYERS 3")
    out.append(c_u8("sn_map_runs", map_runs, per=24))
    out.append(c_u16("sn_haunt_xy", [v for xy in HAUNT_XY for v in xy]))
    out.append(f"#define SN_VESUVIO_X {VESUVIO_XY[0]}")
    out.append(f"#define SN_VESUVIO_Y {VESUVIO_XY[1]}")
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

    def scene_image(scene, rows):
        im = Image.new("RGBA", (320, 160), (0, 0, 0, 255))
        d = ImageDraw.Draw(im)
        top, low = scene["sky"]
        for band in range(8):
            c = tuple(top[i] + (low[i] - top[i]) * band // 7 for i in range(3))
            d.rectangle((0, band * 20, 319, band * 20 + 19), fill=c)
        if scene["far"]:
            fp = scene["far_placed"]
            for y in range(far.shape[0]):
                for x in range(far.shape[1]):
                    if far[y, x]:
                        im.putpixel((196 + x, (3 if rows is ROAD_ROWS else 4) * 16 - 23 + y), rgb888(fp[far[y, x]]) + (255,))
        for ty, row in enumerate(rows):
            for tx, ch in enumerate(row):
                if CHARS[ch]:
                    tile = TILES[TILE_CODE[CHARS[ch]] - 1][1]
                    im.alpha_composite(tile_image(tile, scene["placed"]), (tx * 16, ty * 16))
        return im

    def sprite_image(inds, pal):
        h, w = inds.shape
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        for y in range(h):
            for x in range(w):
                if inds[y, x]:
                    im.putpixel((x, y), rgb888(pal[inds[y, x]]) + (255,))
        return im

    sheet = Image.new("RGBA", (640, 4 * 180), (4, 8, 20, 255))
    d = ImageDraw.Draw(sheet)
    views = [(s, s["rows"]) for s in SCENES] + [(SCENES[1], ROAD_ROWS)]
    for i, (scene, rows) in enumerate(views):
        im = scene_image(scene, rows)
        x, y = (i % 2) * 320, (i // 2) * 180
        ghost = scene["ghosts"][-1]
        if rows is ROAD_ROWS:
            im.alpha_composite(sprite_image(sprites["fiat"][0], palettes["fiat"]), (60, 104))
            im.alpha_composite(sprite_image(props["slime"], props_pal), (220, 140))
            im.alpha_composite(sprite_image(props["palm"], props_pal), (150, 40))
        else:
            im.alpha_composite(sprite_image(sprites[ghost][0], palettes[ghost]), (200 if ghost != "boss" else 112, 30))
            im.alpha_composite(sprite_image(sprites["hunter"][0], palettes["hunter"]), (30, 88))
            im.alpha_composite(sprite_image(props["trap"], props_pal), (180, 134))
            im.alpha_composite(sprite_image(props["lamp"], props_pal), (4, 96))
        sheet.alpha_composite(im, (x, y))
        d.text((x + 4, y + 164), scene["name"] if rows is not ROAD_ROWS else "LUNGOMARE (drive)", fill=(255, 255, 255))
    sheet.convert("RGB").save(DOCS / "scenes.png", optimize=True)

    bank = Image.new("RGBA", (10 * 36 + 4, ((len(TILES) + 9) // 10) * 36 + 4), (30, 30, 46, 255))
    for i, (name, t) in enumerate(TILES):
        bank.alpha_composite(tile_image(t, SCENES[0]["placed"]).resize((32, 32), Image.Resampling.NEAREST),
                             (4 + (i % 10) * 36, 4 + (i // 10) * 36))
    bank.convert("RGB").save(DOCS / "tiles.png", optimize=True)

    art = Image.new("RGBA", (640, 200), (16, 20, 34, 255))
    x = 6
    for symbol, _, size, _, _ in SPRITES:
        im = sprite_image(sprites[symbol][0], palettes[symbol]).resize((size[0] * 2, size[1] * 2), Image.Resampling.NEAREST)
        if x + im.width > 636:
            break
        art.alpha_composite(im, (x, 8))
        x += im.width + 6
    x = 6
    for name, inds in props.items():
        im = sprite_image(inds, props_pal).resize((inds.shape[1] * 2, inds.shape[0] * 2), Image.Resampling.NEAREST)
        art.alpha_composite(im, (x, 200 - im.height - 4))
        x += im.width + 8
    art.alpha_composite(sprite_image(logo, [0, 0xFFE0]), (300, 164))
    art.convert("RGB").save(DOCS / "sprites.png", optimize=True)

    mp = Image.new("RGB", (320, 160), (14, 44, 110))
    md = ImageDraw.Draw(mp)
    for layer, colour in enumerate(((226, 196, 130), (46, 120, 66), (70, 150, 80))):
        for row in range(MAP_H):
            for i in range(3):
                x0, x1 = map_runs[(layer * MAP_H + row) * 6 + i * 2:(layer * MAP_H + row) * 6 + i * 2 + 2]
                if x1 > x0:
                    md.rectangle((x0 * 4, row * 4, x1 * 4 - 1, row * 4 + 3), fill=colour)
    fp = SCENES[1]["far_placed"]
    for y in range(far.shape[0]):
        for x in range(far.shape[1]):
            if far[y, x]:
                mp.putpixel((FAR_ON_MAP[0] + x, FAR_ON_MAP[1] + y), rgb888(fp[far[y, x]]))
    for (hx, hy) in HAUNT_XY:
        md.ellipse((hx - 4, hy - 4, hx + 4, hy + 4), fill=(255, 255, 255))
    md.ellipse((VESUVIO_XY[0] - 4, VESUVIO_XY[1] - 4, VESUVIO_XY[0] + 4, VESUVIO_XY[1] + 4), fill=(255, 80, 40))
    mp.save(DOCS / "map.png", optimize=True)

    cells = len(shared)
    art_bytes = (len(TILES) * 128 + sum(s[0] * s[1] // 2 for _, _, s, _, _ in SPRITES)
                 + sum(v.size // 2 for v in props.values()) + far.size // 4 + logo.size // 8 + len(map_runs))
    print(f"{OUT.name}: {len(TILES)} tiles, {len(SCENES)} districts, {cells} shared cells, {art_bytes} bytes of art")


if __name__ == "__main__":
    main()
