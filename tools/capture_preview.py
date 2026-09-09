#!/usr/bin/env python3
"""Record the 30-second Store preview from real PRG32 QEMU video and audio."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys


HERE = Path(__file__).resolve().parents[1]
PRG32 = Path(os.environ.get("PRG32_REPO", HERE.parent / "PRG32")).resolve()
sys.path.insert(0, str(PRG32 / "tools"))

import capture_cartridge_previews as recorder  # noqa: E402


# Start, dispatch, steer during the drive, then pulse the beam during capture.
# A second dispatch ensures the preview shows the map/game loop as well as action.
KEY_EVENTS = (
    (1.0, "j"), (3.0, "j"),
    (4.0, "d"), (5.0, "a"), (6.0, "d"),
    (8.0, "j"), (8.7, "j"), (9.4, "j"), (10.1, "j"),
    (13.5, "d"), (14.0, "j"),
    (15.0, "a"), (16.0, "d"), (17.0, "d"),
    (19.0, "j"), (19.7, "j"), (20.4, "j"), (21.1, "j"),
    (24.0, "d"), (24.5, "j"),
)


def main() -> None:
    cartridge = HERE / "dist/store/spiriti-napoli97-qemu.prg32"
    temporary_output = PRG32 / "build-qemu/spiriti-napoli97-preview.mp4"
    output = HERE / "preview.mp4"
    recorder.CARTRIDGES["spiriti-napoli97"] = (
        str(cartridge), str(temporary_output), KEY_EVENTS
    )
    ffmpeg = os.environ.get("FFMPEG") or shutil.which("ffmpeg")
    if not ffmpeg:
        candidates=sorted((Path.home()/"Library/Python").glob(
            "*/lib/python/site-packages/imageio_ffmpeg/binaries/ffmpeg-*"))
        if not candidates:
            raise SystemExit("install ffmpeg or imageio-ffmpeg, or set FFMPEG")
        ffmpeg=str(candidates[-1])
    # The SDL window is captured at 2x backing resolution on Retina displays.
    # Adapt the upstream fixed-size filter so it records the complete 320x200
    # playfield instead of only its upper half.
    original_run=recorder.subprocess.run
    def retina_aware_run(args, *pargs, **kwargs):
        if isinstance(args,list) and args and str(args[0])==ffmpeg and "-vf" in args:
            args=list(args)
            vf=args.index("-vf")+1
            if args[vf]=="crop=iw:200:0:48,scale=320:200:flags=neighbor":
                args[vf]="crop=iw:400:0:56,scale=320:200:flags=neighbor"
        return original_run(args,*pargs,**kwargs)
    recorder.subprocess.run=retina_aware_run
    recorder.capture("spiriti-napoli97",30,30,7,ffmpeg,True)
    shutil.copy2(temporary_output, output)
    original_run([ffmpeg,"-y","-loglevel","error","-ss","19.05","-i",
                  str(output),"-frames:v","1",str(HERE/"screenshot.png")],check=True)
    magick=shutil.which("magick")
    if magick:
        optimized=HERE/"screenshot-indexed.png"
        original_run([magick,str(HERE/"screenshot.png"),"-dither","None",
                      "-colors","128",f"PNG8:{optimized}"],check=True)
        optimized.replace(HERE/"screenshot.png")
    print(f"wrote {output}")
    print(f"wrote {HERE/'screenshot.png'}")


if __name__ == "__main__":
    main()
