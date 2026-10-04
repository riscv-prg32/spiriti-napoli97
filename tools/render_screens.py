#!/usr/bin/env python3
"""Render real game frames through the host harness.

Builds tests/harness/run_harness.c, runs it with SPIRITI_SHOTS pointing at a
temporary directory and converts the dumped frames - the exact 320x200 output
of game.c as the ESP32-C6 palette shows it - into:

    release-artifacts/screens/*.png                  2x previews
    release-artifacts/spiriti-napoli97-contact-sheet.png

The Store screenshot itself is a QEMU capture: see tools/qemu_capture.py.
"""
import os
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "release-artifacts"
SHEET = ["01-titolo", "02-mappa", "03-lungomare", "04-centro-gesu-nuovo", "05-mergellina-castel-dell-ovo",
         "06-vomero-sant-elmo", "07-porto-maschio-angioino", "08-fuorigrotta-stadio", "09-capodimonte-reggia",
         "10-villa-doria-d-angri", "11-scegli-la-forma", "12-pulcinella", "13-corsa-al-plebiscito",
         "14-piazza-del-plebiscito", "16-parata"]

with tempfile.TemporaryDirectory(prefix="spiriti-shots-") as temp:
    binary = Path(temp) / "harness"
    subprocess.run([os.environ.get("CC", "cc"), "-std=c11", "-O1", f"-I{ROOT / 'tests/stub'}", f"-I{ROOT}",
                    str(ROOT / "tests/harness/run_harness.c"), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True, env={**os.environ, "SPIRITI_SHOTS": temp}, stdout=subprocess.DEVNULL)
    frames = {p.stem: Image.open(p).convert("RGB") for p in sorted(Path(temp).glob("*.ppm"))}

(OUT / "screens").mkdir(parents=True, exist_ok=True)
for old in (OUT / "screens").glob("*.png"):
    old.unlink()
for name, frame in frames.items():
    frame.resize((640, 400), Image.Resampling.NEAREST).quantize(colors=128, dither=Image.Dither.NONE).save(
        OUT / "screens" / f"{name}.png", optimize=True)
sheet = Image.new("RGB", (3 * 320 + 4 * 4, 5 * 200 + 6 * 4), (8, 10, 30))
for i, name in enumerate(SHEET):
    sheet.paste(frames[name], (4 + (i % 3) * 324, 4 + (i // 3) * 204))
sheet.quantize(colors=220, dither=Image.Dither.NONE).save(OUT / "spiriti-napoli97-contact-sheet.png", optimize=True)
print(f"wrote {len(frames)} screens and the contact sheet to {OUT}")
