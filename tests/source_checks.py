#!/usr/bin/env python3
"""Static checks on the cartridge source, the generated art and the score."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
game = (ROOT / "game.c").read_text()
assets = (ROOT / "assets.h").read_text()
audio = json.loads((ROOT / "audio.json").read_text())
meta = json.loads((ROOT / "metadata.json").read_text())
colophon = json.loads((ROOT / "colophon.json").read_text())


def fail(message):
    sys.exit(f"source_checks: {message}")


def array(name):
    match = re.search(rf"{name}\[\d+\] = \{{(.*?)\}};", assets, re.S)
    if not match:
        fail(f"{name} missing from assets.h")
    return [int(v, 0) for v in re.findall(r"0x[0-9A-Fa-f]+|\d+", match.group(1))]


def define(name):
    return int(re.search(rf"#define {name} (\w+)", assets).group(1), 0)


for token in ("spiriti_napoli97_init", "spiriti_napoli97_update", "spiriti_napoli97_draw",
              "prg32_sprite_draw_indexed", "prg32_palette_set", "prg32_gfx_rect_indexed",
              "prg32_audio_note_on_pan", "prg32_audio_play_track", "prg32_scoreboard_show"):
    if token not in game:
        fail(f"missing: {token}")
# Portable cartridges are loaded at different addresses: no pointer tables in data.
if re.search(r"static\s+const\s+char\s*\*\s*(const\s+)?\w+\s*\[", game):
    fail("static pointer table found; portable cartridges cannot relocate it")
# RGB565 fills are quantised per pixel on the board, and the tile engine is built on them.
for call in ("prg32_gfx_rect(", "prg32_gfx_clear(", "prg32_gfx_pixel(", "prg32_tile_", "prg32_playfield_",
             "prg32_buzzer_"):
    if call in game:
        fail(f"{call} bypasses the indexed palette or the audio engine")

# Colours: everything shown together owns its own 6x6x6 cube cell, so the
# ESP32-C6 indexed framebuffer shows the authored colours exactly.
NAMED = (0x0000, 0xFFFF, 0xF800, 0x07E0, 0x001F, 0xFFE0, 0x07FF, 0xF81F)


def cell(v):
    return 16 + ((v >> 11) * 5 // 31) * 36 + (((v >> 5) & 63) * 5 // 63) * 6 + ((v & 31) * 5 // 31)


def distinct(label, colours):
    colours = {c for c in colours if c not in NAMED}
    if len({cell(c) for c in colours}) != len(colours):
        fail(f"{label}: two colours share a system-palette cell")


shared = set(array("sn_props_pal")[1:]) | set(array("sn_hunter_pal")[1:]) | set(array("sn_fiat_pal")[1:])
shared.add(define("SN_UI_NAVY"))
distinct("shared colours", shared)
scenes = define("SN_SCENE_COUNT")
scene_pal, far_pal = array("sn_scene_pal"), array("sn_far_pal")
# The spirit drawn in each scene, as game.c pairs them: six districts, the villa's guardian, the
# piazza (the giant uses reserved entries only) and the lungomare of the title and the endings.
SPIRITS = {0: ["ghost0"], 1: ["ghost1"], 2: ["ghost3"], 3: ["ghost2"], 4: ["ghost4"], 5: ["ghost5"], 6: ["boss"],
           7: [], 8: ["ghost0"]}
if len(scene_pal) != scenes * 16 or len(far_pal) != 4 or scenes != len(SPIRITS):
    fail("scene palettes do not match the scene count")
for scene, spirits in SPIRITS.items():
    here = shared | set(scene_pal[scene * 16 + 1:(scene + 1) * 16])
    if scene == 8:
        here |= set(far_pal[1:])
    distinct(f"scene {scene}", here)
    for spirit in spirits:
        distinct(f"scene {scene} with {spirit}", here | set(array(f"sn_{spirit}_pal")[1:]))

cells = define("SN_SCENE_COLS") * define("SN_SCENE_ROWS")
maps = array("sn_shore_map") + array("sn_road_map") + array("sn_ground")
if len(maps) != 2 * cells + scenes * 3 or any(code > define("SN_TILE_COUNT") for code in maps):
    fail("tile maps")
if len(array("sn_tiles")) != define("SN_TILE_COUNT") * 128:
    fail("tile bank size")


def picture_rows(name, width):
    """Walk a picture as game.c does; every band must fill the width exactly."""
    data = array(name)
    i = rows = 0
    while data[i]:
        rows += data[i]
        i += 1
        x = 0
        while x < width:
            n = (data[i] & 15) + 1
            i += 1
            if n == 16:
                n = data[i]
                i += 1
            x += n
        if x != width:
            fail(f"{name}: a band overruns its width")
    if i != len(data) - 1:
        fail(f"{name}: data after the terminator")
    return rows


for scene in range(8):
    if picture_rows(f"sn_pic{scene}", define("SN_PIC_W")) not in (56, 64, 80):
        fail(f"sn_pic{scene}: unexpected height")
for name in ("far", "logo", "gulf", "pulci0", "pulci1"):
    if picture_rows(f"sn_{name}_pic", define(f"SN_{name.upper()}_W")) != define(f"SN_{name.upper()}_H"):
        fail(f"sn_{name}_pic: wrong height")
if not (ROOT / "assets-src/villa_doria_dangri.jpg").exists():
    fail("the Villa Doria d'Angri photograph is missing")
for token in ("SCEGLI LA FORMA", "DEL DISTRUTTORE", "PIAZZA DEL PLEBISCITO", "VILLA DORIA D'ANGRI", "prg32_audio_set_tempo"):
    if token not in game:
        fail(f"missing: {token}")

# Audio: procedural instruments only, music on voices 0-3, every track ends or loops.
if audio.get("samples"):
    fail("the soundtrack must stay PCM-free")
for instrument in audio["instruments"]:
    if not instrument["sample_id"] & 0x8000 or instrument["sample_id"] & 0x7000:
        fail("instrument is not a documented PRG32_AUDIO_SYNTH_ID")
for number, track in enumerate(audio["tracks"]):
    events = track["events"]
    for event in events:
        if event["command"] in ("NOTE_ON", "NOTE_OFF") and event["arg0"] > 3:
            fail(f"track {number} uses a voice reserved for effects")
    if events[-1]["command"] not in ("JUMP", "END"):
        fail(f"track {number} does not end")
    if events[-1]["command"] == "JUMP" and events[events[-1]["arg0"]]["command"] not in ("NOTE_ON", "NOTE_OFF"):
        fail(f"track {number} loops into its set-up events")
if len(audio["tracks"]) != 10 or len(audio["instruments"]) != 10:
    fail("audio.json does not match the voices game.c uses")

if colophon["version"] != meta["version"] or colophon["title"] != meta["title"]:
    fail("metadata and colophon disagree")
if f"## {meta['version']}" not in (ROOT / "CHANGELOG.md").read_text():
    fail("CHANGELOG.md has no entry for this version")
print(f"OK: {scenes} scenes, {define('SN_TILE_COUNT')} tiles, {len(audio['tracks'])} tracks, version {meta['version']}")
