#!/usr/bin/env python3
"""Run the cartridge in PRG32's QEMU firmware and record what it really does.

The cartridge is staged into a private copy of the firmware's flash image and
booted in Espressif QEMU. The tool then:

- plays a demo through the UART keyboard mapper: title, map and drive from a
  script, then the capture by looking at the picture, like a player would;
- copies the firmware's 320x240 frame buffer out of guest memory with the
  QEMU monitor's `pmemsave` (no screen-recording permission needed) and keeps
  the 320x200 playfield;
- feeds the firmware's credit-paced UART audio and records the 22050 Hz PCM;
- writes PNG screenshots and, with ffmpeg, preview.mp4 with the real soundtrack;
- keeps the capture frame with the most beam and trap light as the Store
  screenshot (screenshot.png). Run ./build.sh again afterwards to embed it.

Usage (after `python3 -m prg32 qemu build` in the PRG32 checkout and ./build.sh):

    PRG32_REPO=/path/to/PRG32 python3 tools/qemu_capture.py
"""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

import numpy as np
from PIL import Image

GAME = Path(__file__).resolve().parents[1]
RATE = 22050
CONSOLE_PORT, AUDIO_PORT, MONITOR_PORT = 5551, 4321, 5552

# Demo script, in seconds after the title screen is up: (start, end, keys).
# Keys are held by resending them faster than the firmware's 120 ms key hold.
RIGHT, LEFT, UP, DOWN, A, B, SELECT = "d", "a", "w", "s", "j", "k", " "
DEMO = [
    (2.0, 2.1, A),                                   # start the shift
    (4.5, 4.6, A),                                   # dispatch to Centro Storico
    (6.0, 30.0, RIGHT),                              # floor it along the lungomare
    (8.0, 8.1, UP), (10.5, 10.6, DOWN), (12.0, 12.1, DOWN), (14.5, 14.6, UP), (17.0, 17.1, UP), (19.5, 19.6, DOWN),
]
SHOTS = {"title": 1.2, "map": 3.6, "drive": 12.0}
DRIVE_FROM = 6.0         # the scripted part ends when the capture screen appears
OUTRO = 5.0              # seconds recorded after the capture: the result and the map


def on_capture_screen(a: np.ndarray) -> bool:
    """Capture screen: a yellow district name in the top band, cyan CATTURA in the bottom one."""
    top, low = a[4:12, 4:60], a[179:187, 4:60]
    yellow = ((top[:, :, 0] > 240) & (top[:, :, 1] > 240) & (top[:, :, 2] < 40)).sum()
    cyan = ((low[:, :, 0] < 40) & (low[:, :, 1] > 240) & (low[:, :, 2] > 240)).sum()
    return yellow > 20 and cyan > 20


def capture_keys(a: np.ndarray, state: dict) -> str:
    """Play the capture from the picture: keep the trap under the spirit, fire in bursts."""
    keys = ""
    band = a[148:162, 60:]
    red = (band[:, :, 0] > 200) & (band[:, :, 1] < 90) & (band[:, :, 2] < 110)
    area = a[30:124, 64:]
    bright = (area[:, :, 0] > 225) & (area[:, :, 1] > 235) & (area[:, :, 2] > 235)
    if red.sum() >= 4 and bright.sum() >= 20:
        trap = 60 + float(np.median(np.nonzero(red)[1]))
        spirit = 64 + float(np.median(np.nonzero(bright)[1]))
        if trap < spirit - 8:
            keys += RIGHT
        if trap > spirit + 8:
            keys += LEFT
    bar = a[181:185, 212:312]
    heat = float(((bar[:, :, 0] > 200) & (bar[:, :, 2] < 80)).any(axis=0).mean())
    if heat > 0.85:
        state["cooling"] = True
    if heat < 0.35:
        state["cooling"] = False
    if not state.get("cooling"):
        keys += A
    return keys


def cone_score(a: np.ndarray) -> int:
    """Pixels of the trap's pale light cone while the beam is on: the Store
    screenshot is the capture frame with the most."""
    play = a[16:176]
    beam = ((play[:, :, 0] < 40) & (play[:, :, 1] > 240) & (play[:, :, 2] > 240)).sum()
    cone = ((play[:, :, 0] > 150) & (play[:, :, 0] < 190) & (play[:, :, 1] > 240) & (play[:, :, 2] > 240)).sum()
    return int(cone) if beam > 30 else 0


def connect(port: int, process: subprocess.Popen, timeout: float = 20.0) -> socket.socket:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"QEMU exited early with status {process.returncode}")
        try:
            return socket.create_connection(("127.0.0.1", port), timeout=1)
        except OSError:
            time.sleep(0.1)
    raise TimeoutError(f"timed out connecting to QEMU port {port}")


def audio_worker(process: subprocess.Popen, samples: bytearray, recording: threading.Event,
                 stopping: threading.Event) -> None:
    """Grant one 20 ms credit at a time, as the host audio player does."""
    sock = connect(AUDIO_PORT, process)
    chunk = 441 * 2
    try:
        sock.sendall(b"K")
        next_credit = time.monotonic() + 0.02
        while not stopping.is_set() and process.poll() is None:
            data = bytearray()
            while len(data) < chunk:
                part = sock.recv(chunk - len(data))
                if not part:
                    return
                data.extend(part)
            if recording.is_set():
                samples.extend(data)
            delay = next_credit - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            next_credit += 0.02
            sock.sendall(b"K")
    except OSError:
        return
    finally:
        sock.close()


def drain(sock: socket.socket, sink: bytearray, stopping: threading.Event) -> None:
    sock.settimeout(0.2)
    while not stopping.is_set():
        try:
            data = sock.recv(4096)
        except (TimeoutError, socket.timeout):
            continue
        except OSError:
            return
        if not data:
            return
        sink.extend(data)


PANEL_W, PANEL_H = 320, 240


def framebuffer_address(elf: Path) -> int:
    """Address of the firmware's RGB565 frame buffer (`g_fb`) in the QEMU build."""
    tools = sorted(Path.home().glob(".espressif/tools/riscv32-esp-elf/*/riscv32-esp-elf/bin"))
    nm = shutil.which("riscv32-esp-elf-nm", path=os.pathsep.join([str(t) for t in tools] + [os.environ["PATH"]]))
    if not nm:
        raise SystemExit("riscv32-esp-elf-nm not found; source the ESP-IDF environment")
    for line in subprocess.run([nm, str(elf)], check=True, capture_output=True, text=True).stdout.splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[2] == "g_fb":
            return int(fields[0], 16)
    raise SystemExit(f"g_fb not found in {elf}")


def grab(monitor: socket.socket, address: int, path: Path) -> Image.Image | None:
    """Copy the firmware frame buffer out of guest memory; keep the 320x200 playfield."""
    size = PANEL_W * PANEL_H * 2
    path.unlink(missing_ok=True)
    monitor.sendall(f"pmemsave {address:#x} {size} \"{path}\"\n".encode())
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if path.exists() and path.stat().st_size == size:
            raw = np.frombuffer(path.read_bytes(), dtype="<u2").reshape(PANEL_H, PANEL_W)[20:220]
            rgb = np.dstack(((raw >> 11) * 255 // 31, ((raw >> 5) & 63) * 255 // 63, (raw & 31) * 255 // 31))
            return Image.fromarray(rgb.astype(np.uint8), "RGB")
        time.sleep(0.004)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prg32-root", type=Path, default=Path(os.environ.get("PRG32_REPO", os.environ.get("PRG32_ROOT", GAME.parent / "PRG32"))))
    parser.add_argument("--cartridge", type=Path, default=GAME / "build/spiriti-napoli97-base.prg32")
    parser.add_argument("--out", type=Path, default=GAME / "release-artifacts")
    parser.add_argument("--duration", type=float, default=75.0, help="upper limit; the demo stops after the first capture")
    parser.add_argument("--warmup", type=float, default=7.0, help="seconds from reset to the title screen")
    parser.add_argument("--store-shot", default="capture", help="shot copied to screenshot.png")
    parser.add_argument("--display", default="sdl", help="QEMU display back end; the firmware stalls with `none`")
    args = parser.parse_args()

    root = args.prg32_root.resolve()
    for required in (root / "build-qemu/qemu_flash.bin", root / "build-qemu/qemu_efuse.bin", args.cartridge):
        if not required.exists():
            raise SystemExit(f"missing {required}")
    qemu = shutil.which("qemu-system-riscv32", path=os.pathsep.join(
        [str(p) for p in sorted(Path.home().glob(".espressif/tools/qemu-riscv32/*/qemu/bin"))] + [os.environ["PATH"]]))
    if not qemu:
        raise SystemExit("qemu-system-riscv32 (Espressif build) not found")
    ffmpeg = shutil.which("ffmpeg")
    fb_address = framebuffer_address(root / "build-qemu/PRG32.elf")
    shots_dir = args.out / "qemu"
    shots_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="spiriti-qemu-") as temp_name:
        temp = Path(temp_name)
        flash, efuse = temp / "flash.bin", temp / "efuse.bin"
        shutil.copy2(root / "build-qemu/qemu_flash.bin", flash)
        shutil.copy2(root / "build-qemu/qemu_efuse.bin", efuse)
        subprocess.run([sys.executable, "-m", "prg32", "qemu", "upload", str(args.cartridge.resolve()),
                        "--flash", str(flash), "--cart-ram-kib", "64"], cwd=root, check=True)
        command = [
            qemu, "-M", "esp32c3", "-m", "4M",
            "-drive", f"file={flash},if=mtd,format=raw",
            "-drive", f"file={efuse},if=none,format=raw,id=efuse",
            "-global", "driver=nvram.esp32c3.efuse,property=drive,value=efuse",
            "-global", "driver=timer.esp32c3.timg,property=wdt_disable,value=true",
            "-nic", "user,model=open_eth", "-display", args.display,
            "-monitor", f"tcp:127.0.0.1:{MONITOR_PORT},server=on,wait=off",
            "-serial", f"tcp:127.0.0.1:{CONSOLE_PORT},server=on,wait=off,nodelay=on",
            "-serial", f"tcp:127.0.0.1:{AUDIO_PORT},server=on,wait=on,nodelay=on",
        ]
        samples, transcript, monitor_log = bytearray(), bytearray(), bytearray()
        recording, stopping = threading.Event(), threading.Event()
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        threads = [threading.Thread(target=audio_worker, args=(process, samples, recording, stopping), daemon=True)]
        threads[0].start()
        console = connect(CONSOLE_PORT, process)
        monitor = connect(MONITOR_PORT, process)
        threads.append(threading.Thread(target=drain, args=(console, transcript, stopping), daemon=True))
        threads.append(threading.Thread(target=drain, args=(monitor, monitor_log, stopping), daemon=True))
        for thread in threads[1:]:
            thread.start()
        frames: list[tuple[float, Path]] = []
        try:
            time.sleep(args.warmup)
            recording.set()
            start = time.monotonic()
            pending = dict(SHOTS)
            best_score = -1
            last_key: dict[str, float] = {}
            index = 0
            bot: dict = {}
            capturing, stop_at = False, args.duration
            while (now := time.monotonic() - start) < stop_at:
                image = grab(monitor, fb_address, temp / "panel.bin")
                if image is None:
                    continue
                pixels = np.asarray(image).astype(int)
                on_capture = now >= DRIVE_FROM and on_capture_screen(pixels)
                if on_capture:
                    capturing = True
                    keys = capture_keys(pixels, bot)
                elif capturing:
                    keys = ""
                    stop_at = min(stop_at, now + OUTRO)      # caught or lost: record the outcome and stop
                    capturing = False
                else:
                    keys = "" if stop_at < args.duration else "".join(k for b, e, k in DEMO if b <= now < e)
                for key in keys:
                    if now - last_key.get(key, -1.0) >= 0.06:
                        console.sendall(key.encode())
                        last_key[key] = now
                time.sleep(max(0.0, 1 / 30 - (time.monotonic() - start - now)))
                frame = temp / f"frame-{index:05d}.png"
                image.save(frame)
                frames.append((now, frame))
                index += 1
                if on_capture and cone_score(pixels) > best_score:
                    best_score = cone_score(pixels)
                    image.save(shots_dir / "capture.png", optimize=True)
                for name, when in list(pending.items()):
                    if now >= when:
                        image.save(shots_dir / f"{name}.png", optimize=True)
                        del pending[name]
            args.duration = min(args.duration, now)
            if process.poll() is not None:
                raise RuntimeError("QEMU stopped during the capture")
        finally:
            stopping.set()
            process.terminate()
            process.wait(timeout=10)
            for sock in (console, monitor):
                sock.close()
            log = [line for line in bytes(transcript).decode(errors="replace").splitlines()
                   if not line.startswith("TRACKER ")]          # drop the firmware's per-note trace
            (shots_dir / "boot-log.txt").write_text("\n".join(log) + "\n")
            if not frames:
                print(monitor_log.decode(errors="replace")[-600:])

        shot = shots_dir / f"{args.store_shot}.png"
        if args.out.resolve() == (GAME / "release-artifacts").resolve() and shot.exists():
            Image.open(shot).quantize(colors=64, dither=Image.Dither.NONE).save(GAME / "screenshot.png", optimize=True)
        if len(frames) < 10:
            raise SystemExit("QEMU produced no frames; see release-artifacts/qemu/boot-log.txt")
        distinct = len({Image.open(path).tobytes() for _, path in frames[:: max(1, len(frames) // 40)]})
        print(f"{len(frames)} frames in {args.duration:g} s ({len(frames) / args.duration:.1f} fps), "
              f"{distinct} distinct in a sample of 40, {len(samples) // 2} audio samples")
        with wave.open(str(temp / "audio.wav"), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(RATE)
            wav.writeframes(bytes(samples[: int(args.duration * RATE) * 2]))
        if ffmpeg:
            listing = temp / "frames.txt"
            lines = []
            for i, (when, path) in enumerate(frames):
                nxt = frames[i + 1][0] if i + 1 < len(frames) else args.duration
                lines += [f"file '{path}'", f"duration {max(nxt - when, 0.001):.4f}"]
            lines.append(f"file '{frames[-1][1]}'")
            listing.write_text("\n".join(lines) + "\n")
            video = GAME / "preview.mp4"
            subprocess.run([ffmpeg, "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                            "-i", str(temp / "audio.wav"), "-vf", "scale=640:400:flags=neighbor,fps=30",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "26", "-c:a", "aac", "-b:a", "96k",
                            "-t", f"{args.duration:g}", "-movflags", "+faststart", str(video)], check=True)
            print(f"wrote {video}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
