#!/usr/bin/env python3
"""Play the cartridge in PRG32's QEMU firmware and record what it really does.

The cartridge is staged into a private copy of the firmware's flash image and
booted in Espressif QEMU. The tool then:

- copies the firmware's 320x240 frame buffer out of guest memory with the
  QEMU monitor's `pmemsave` (no screen-recording permission needed) and keeps
  the 320x200 playfield;
- plays the whole game through the UART keyboard mapper by looking at those
  frames, as a player would: it reads which screen is up from the colours of
  the status bands, finds the spirit at the end of its own beam, the trap, the
  giant and the car by their colours, and the heat from its gauge;
- feeds the firmware's credit-paced UART audio and records the 22050 Hz PCM;
- writes PNG screenshots of each stage, the Store screenshot (the piazza
  fight) and, with ffmpeg, preview.mp4: the first call-out, then everything
  from Villa Doria d'Angri to the parade, with the real soundtrack.

Usage (after `python3 -m prg32 qemu build` in the PRG32 checkout and ./build.sh;
run ./build.sh again afterwards to embed the new screenshot):

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

RIGHT, LEFT, UP, DOWN, A, B, SELECT = "d", "a", "w", "s", "j", "k", " "
HUD_Y = 176
LANE_SHADOW_ROWS = (135, 151, 167)       # where a flying spirit's shadow falls in each lane


def count(a: np.ndarray, box: tuple[int, int, int, int], colour: str) -> int:
    """Pixels of a named colour in box (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = box
    r, g, b = a[y0:y1, x0:x1, 0], a[y0:y1, x0:x1, 1], a[y0:y1, x0:x1, 2]
    if colour == "yellow":
        m = (r > 240) & (g > 240) & (b < 40)
    elif colour == "cyan":
        m = (r < 40) & (g > 240) & (b > 240)
    elif colour == "green":
        m = (r < 40) & (g > 240) & (b < 40)
    elif colour == "red":
        m = (r > 240) & (g < 40) & (b < 40)
    elif colour == "white":
        m = (r > 250) & (g > 250) & (b > 250)
    else:
        m = (r < 6) & (g < 6) & (b < 6)
    return int(m.sum())


def screen(a: np.ndarray) -> str:
    """Which screen is up, from the colours of the text in the two bands."""
    top, low = (4, 4, 100, 12), (4, 179, 56, 187)
    if count(a, top, "green") > 20:
        return "title"
    if count(a, top, "cyan") > 20:
        return "drive"
    if count(a, top, "red") > 20:
        return "omen"
    if count(a, top, "yellow") > 20:
        if count(a, low, "cyan") > 20:
            if count(a, (180, 4, 208, 12), "red") > 3:
                return "piazza"
            return "villa" if count(a, (64, 180, 148, 186), "red") > 30 else "capture"
        if count(a, low, "yellow") > 20:
            return "map"
        if count(a, (88, 189, 232, 197), "cyan") > 40:
            return "over"
        return "result"
    return "other"


def heat_keys(a: np.ndarray, state: dict) -> str:
    """Fire in bursts: stop before the pack vents, start again when it has cooled."""
    bar = a[181:185, 212:312]
    heat = float(((bar[:, :, 0] > 200) & (bar[:, :, 2] < 80)).any(axis=0).mean())
    if heat > 0.82:
        state["cooling"] = True
    if heat < 0.35:
        state["cooling"] = False
    return "" if state.get("cooling") else A


def median_x(mask: np.ndarray, offset: int = 0) -> float | None:
    xs = np.nonzero(mask)[1]
    return offset + float(np.median(xs)) if len(xs) >= 4 else None


def play(a: np.ndarray, where: str, now: float, state: dict) -> str:
    """The keys to hold for this frame."""
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    if where in ("title", "map"):
        return A if now - state.get("tapped", -9.0) > 1.2 and not state.update(tapped=now) else ""
    if where == "drive":
        keys = RIGHT
        lane = state.setdefault("lane", 1)
        if state.get("drive_seen") != state.get("drives"):          # a new drive starts in the middle lane
            state["drive_seen"] = state.get("drives")
            lane = state["lane"] = 1
        shadow = [count(a, (110, y, 300, y + 2), "black") >= 10 for y in LANE_SHADOW_ROWS]
        if shadow[lane] and now - state.get("steered", -9.0) > 0.35:
            want = next((n for n in (lane - 1, lane + 1) if 0 <= n <= 2 and not shadow[n]), None)
            if want is not None:
                keys += UP if want < lane else DOWN
                state["lane"], state["steered"] = want, now
        return keys
    if where == "capture":
        keys = heat_keys(a, state)
        beam = (r[20:150] < 40) & (g[20:150] > 240) & (b[20:150] > 240)
        rows_hit = np.nonzero(beam.any(axis=1))[0]
        if len(rows_hit):                                           # the spirit is where the beam ends
            state["spirit"] = median_x(beam[rows_hit[0]:rows_hit[0] + 6]) or state.get("spirit")
        trap = median_x((r[148:162, 60:] > 200) & (g[148:162, 60:] < 90) & (b[148:162, 60:] < 110), 60)
        if trap is not None and state.get("spirit") is not None:
            if trap < state["spirit"] - 8:
                keys += RIGHT
            if trap > state["spirit"] + 8:
                keys += LEFT
        return keys
    if where == "villa":                                            # never stand still under the fire
        return heat_keys(a, state) + (LEFT if int(now / 2.5) % 2 else RIGHT)
    if where == "piazza":
        giant = median_x((r[30:130] > 250) & (g[30:130] > 250) & (b[30:130] > 250))
        car = median_x((r[146:172] > 200) & (g[146:172] < 90) & (b[146:172] < 110))
        bound = count(a, (160, 189, 284, 197), "yellow") > 20
        keys = "" if bound else heat_keys(a, state)
        if giant is not None and car is not None:
            if car < giant - 10:
                keys += RIGHT
            if car > giant + 10:
                keys += LEFT
            if bound and abs(car - giant) < 40 and now - state.get("trap", -9.0) > 0.5:
                keys += B
                state["trap"] = now
        return keys
    return ""


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
    sock.settimeout(None)       # a busy host must not end the stream: the firmware waits for these credits
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
    parser.add_argument("--duration", type=float, default=540.0, help="upper limit; the run stops at an ending")
    parser.add_argument("--warmup", type=float, default=7.0, help="seconds from reset to the title screen")
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
        seen: dict[str, float] = {}          # when each screen was first shown
        story: list[str] = []
        try:
            time.sleep(args.warmup)
            recording.set()
            start = time.monotonic()
            last_key: dict[str, float] = {}
            state: dict = {"drives": 0}
            index, stop_at, previous, best = 0, args.duration, "", -1
            while (now := time.monotonic() - start) < stop_at:
                image = grab(monitor, fb_address, temp / "panel.bin")
                if image is None:
                    continue
                pixels = np.asarray(image).astype(int)
                where = screen(pixels)
                if where != previous and where != "other":
                    story.append(f"{now:6.1f} s  {where}")
                    if where == "drive":
                        state["drives"] += 1
                    if where in ("capture", "villa", "piazza"):
                        state.pop("spirit", None)
                        state["cooling"] = False
                    if where == "over":
                        stop_at = min(stop_at, now + 9.0)        # the ending: record it and stop
                    previous = where
                if where != "other" and where not in seen:
                    seen[where] = now
                for key in play(pixels, where, now, state):
                    if now - last_key.get(key, -1.0) >= 0.06:
                        console.sendall(key.encode())
                        last_key[key] = now
                time.sleep(max(0.0, 1 / 30 - (time.monotonic() - start - now)))
                frame = temp / f"frame-{index:05d}.png"
                image.save(frame)
                frames.append((now, frame))
                index += 1
                # One screenshot per stage, a couple of seconds in; the piazza frame with the most beam is the Store's.
                if where != "other" and now - seen[where] >= (4.0 if where in ("drive", "omen") else 0.0 if where == "title" else 1.5) and where + "!" not in seen:
                    seen[where + "!"] = now
                    image.save(shots_dir / f"{where}.png", optimize=True)
                if where == "piazza" and count(pixels, (0, 16, 320, 176), "cyan") > best:
                    best = count(pixels, (0, 16, 320, 176), "cyan")
                    image.save(shots_dir / "store.png", optimize=True)
            if process.poll() is not None:
                raise RuntimeError("QEMU stopped during the capture")
            end = now
        finally:
            stopping.set()
            process.terminate()
            process.wait(timeout=10)
            for sock in (console, monitor):
                sock.close()
            log = [line for line in bytes(transcript).decode(errors="replace").splitlines()
                   if not line.startswith(("TRACKER ", "PLAY_TRACK "))]      # drop the firmware's per-note trace
            (shots_dir / "boot-log.txt").write_text("\n".join(log) + "\n")
            (shots_dir / "playthrough.txt").write_text("\n".join(story) + "\n")
            if not frames:
                print(monitor_log.decode(errors="replace")[-600:])

        print("\n".join(story))
        if len(frames) < 10:
            raise SystemExit("QEMU produced no frames; see release-artifacts/qemu/boot-log.txt")
        print(f"{len(frames)} frames in {end:.0f} s ({len(frames) / end:.1f} fps), {len(samples) // 2} audio samples")
        if "over" not in seen:
            raise SystemExit("the run did not reach an ending")
        store = shots_dir / "store.png"
        if args.out.resolve() == (GAME / "release-artifacts").resolve() and store.exists():
            Image.open(store).quantize(colors=64, dither=Image.Dither.NONE).save(GAME / "screenshot.png", optimize=True)
        if ffmpeg:
            # The preview: the first call-out, then from the villa to the end.
            cuts = [(0.0, min(end, seen.get("result", 30.0) + 4.0))]
            if "villa" in seen:
                cuts.append((seen["villa"], end))
            pcm = bytearray()
            lines = []
            for begin, finish in cuts:
                pcm += samples[int(begin * RATE) * 2:int(finish * RATE) * 2]
                chosen = [(when, path) for when, path in frames if begin <= when < finish]
                for i, (when, path) in enumerate(chosen):
                    nxt = chosen[i + 1][0] if i + 1 < len(chosen) else finish
                    lines += [f"file '{path}'", f"duration {max(nxt - when, 0.001):.4f}"]
            lines.append(f"file '{frames[-1][1]}'")
            (temp / "frames.txt").write_text("\n".join(lines) + "\n")
            with wave.open(str(temp / "audio.wav"), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(RATE)
                wav.writeframes(bytes(pcm))
            video = GAME / "preview.mp4"
            subprocess.run([ffmpeg, "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(temp / "frames.txt"),
                            "-i", str(temp / "audio.wav"), "-vf", "scale=640:400:flags=neighbor,fps=20",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "33", "-c:a", "aac", "-b:a", "48k",
                            "-shortest", "-movflags", "+faststart", str(video)], check=True)
            print(f"wrote {video} ({video.stat().st_size // 1024} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
