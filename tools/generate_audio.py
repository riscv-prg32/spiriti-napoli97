#!/usr/bin/env python3
"""Compose the soundtrack of Spiriti! Napoli '97 and write audio.json.

The AUDIO block holds ten SID-like procedural instruments and ten tracker
tracks and stores no PCM. Music plays on voices 0-3 (the tracker plays
instrument N on voice N, panned by the instrument); the game keeps voices
4-7 for the beam, the siren and the other effects, which it pans by screen
position.

Tracker timing: `delta` is the wait *after* an event, in ticks (16th notes),
so events with delta 0 sound together (PRG32 docs/tools/audio.md). Each track
opens by setting the level and pan of its four voices, because the firmware
keeps channel state from whatever played before.

The game also changes the tempo while a track plays (with the road speed,
as a spirit's patience runs out, round by round against the giant).

Every tune is original. None quotes a film, television or game theme.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TRI, SAW, PULSE, NOISE = range(4)


def synth(wave, pulse_width=8, cutoff=15, resonance=0):
    """PRG32_AUDIO_SYNTH_ID: bit 15 marker, resonance, cutoff, pulse width, waveform."""
    return 0x8000 | (resonance & 3) << 10 | (cutoff & 15) << 6 | (pulse_width & 15) << 2 | wave


def inst(sample_id, volume, pan, attack, decay, sustain, release):
    return {"sample_id": sample_id, "default_volume": volume, "default_pan": pan,
            "attack": attack, "decay": decay, "sustain": sustain, "release": release}


INSTRUMENTS = [
    inst(synth(PULSE, 6, 13, 1), 180, -22, 3, 90, 140, 70),    # 0 lead, left of centre
    inst(synth(PULSE, 3, 11, 0), 120, 26, 0, 60, 60, 50),      # 1 counter stabs, right
    inst(synth(SAW, 8, 7, 2), 220, 0, 2, 80, 170, 50),         # 2 bass
    inst(synth(NOISE, 8, 12, 0), 110, 8, 0, 50, 0, 30),        # 3 drums
    inst(synth(SAW, 8, 11, 3), 150, 0, 4, 30, 200, 40),        # 4 proton beam
    inst(synth(PULSE, 4, 14, 0), 170, 0, 0, 70, 0, 50),        # 5 blip, pick-up
    inst(synth(TRI, 8, 13, 1), 190, 0, 30, 0, 255, 90),        # 6 siren, wail
    inst(synth(NOISE, 8, 6, 1), 220, 0, 0, 130, 0, 90),        # 7 splat, thunder, vent
    inst(synth(PULSE, 2, 15, 3), 190, 0, 0, 100, 40, 80),      # 8 trap zap
    inst(synth(SAW, 8, 4, 2), 80, 0, 20, 0, 255, 60),          # 9 Fiat engine
]
MIX = (175, 115, 205, 125)      # level of voices 0-3
SETUP = 9                       # events before the first note; loops jump back here

NOTE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def midi(name):
    pitch = NOTE[name[0]]
    rest = name[1:]
    while rest[0] in "#b":
        pitch += 1 if rest[0] == "#" else -1
        rest = rest[1:]
    return 12 * (int(rest) + 1) + pitch


def part(text, bar=16):
    """'E5 G5:2 r:3 | ...' -> [(midi or None, ticks)]; every bar must be `bar` ticks."""
    out = []
    for number, chunk in enumerate(text.split("|")):
        notes = []
        for tok in chunk.split():
            name, _, length = tok.partition(":")
            notes.append((None if name == "r" else midi(name), int(length or 1)))
        if notes:
            assert sum(t for _, t in notes) == bar, f"bar {number + 1} of '{text[:24]}...' is {sum(t for _, t in notes)} ticks"
            out += notes
    return out


def bars(*patterns, bar=16):
    return part(" | ".join(patterns), bar)


def track(tempo, parts, loop=True, bar=16):
    """Merge per-voice note lists into one delta-after event stream."""
    timeline = []
    length = 0
    for voice, notes in parts.items():
        tick = 0
        for note, ticks in notes:
            timeline.append((tick, 0, "NOTE_OFF", voice, 0) if note is None else (tick, 1, "NOTE_ON", voice, note))
            tick += ticks
        length = max(length, tick)
    for voice, notes in parts.items():
        assert sum(t for _, t in notes) == length, f"voice {voice}: {sum(t for _, t in notes)} != {length}"
    timeline.sort()
    events = [{"delta": 0, "command": "SET_TEMPO", "arg0": tempo, "arg1": 0}]
    for voice in range(4):
        events.append({"delta": 0, "command": "SET_VOLUME", "arg0": voice, "arg1": MIX[voice]})
        events.append({"delta": 0, "command": "SET_PAN", "arg0": voice, "arg1": 0})    # 0: the instrument's own pan
    assert len(events) == SETUP
    for i, (tick, _, command, arg0, arg1) in enumerate(timeline):
        nxt = timeline[i + 1][0] if i + 1 < len(timeline) else length
        assert nxt - tick < 256
        events.append({"delta": nxt - tick, "command": command, "arg0": arg0, "arg1": arg1})
    if loop:
        events.append({"delta": 0, "command": "JUMP", "arg0": SETUP, "arg1": 0})
    else:
        for voice in parts:
            events.append({"delta": 0, "command": "NOTE_OFF", "arg0": voice, "arg1": 0})
        events.append({"delta": 0, "command": "END", "arg0": 0, "arg1": 0})
    return {"events": events}


KICK_HAT = "C3:2 C6:2 C4:2 C6:2 C3:1 C3:1 C6:2 C4:2 C6:2"

TRACKS = [
    # 0 Turno di notte: title, D minor, a bouncing octave bass under a call and response
    track(112, {
        0: bars("D5:2 F5:2 A5:3 G5:1 F5:2 D5:2 r:4", "r:4 Bb4:2 D5:2 F5:3 E5:1 D5:4",
                "E5:2 G5:2 C6:3 Bb5:1 G5:2 E5:2 r:4", "r:4 A4:2 C#5:2 E5:3 G5:1 A5:4",
                "A5:2 A5:1 G5:1 F5:2 D5:2 F5:2 G5:2 A5:4", "Bb5:2 Bb5:1 A5:1 F5:2 D5:2 F5:2 A5:2 Bb5:4",
                "C6:2 C6:1 Bb5:1 G5:2 E5:2 G5:2 Bb5:2 C6:4", "A5:3 G5:1 E5:2 C#5:2 A4:4 r:4"),
        1: bars(*["r:2 A4 D5 r:2 A4 D5 r:2 A4 D5 r:2 F4 A4", "r:2 Bb4 D5 r:2 Bb4 D5 r:2 Bb4 D5 r:2 F4 Bb4",
                  "r:2 G4 C5 r:2 G4 C5 r:2 G4 C5 r:2 E4 G4", "r:2 A4 C#5 r:2 A4 C#5 r:2 A4 C#5 r:2 E4 A4"] * 2),
        2: bars(*["D2:2 D3:2 D2:2 D3:2 D2:2 D3:2 C3:2 D3:2", "Bb1:2 Bb2:2 Bb1:2 Bb2:2 Bb1:2 Bb2:2 A2:2 Bb2:2",
                  "C2:2 C3:2 C2:2 C3:2 C2:2 C3:2 Bb2:2 C3:2", "A1:2 A2:2 A1:2 A2:2 A1:2 A2:2 E2:2 A2:2"] * 2),
        3: bars(*[KICK_HAT] * 8),
    }),
    # 1 Centrale: the dispatch map, A minor, unhurried
    track(100, {
        0: bars("E5:4 r:2 D5:2 C5:4 r:4", "A4:4 r:2 C5:2 B4:4 r:4", "F5:4 r:2 E5:2 D5:4 r:4", "E5:4 r:2 G#5:2 B5:4 r:4"),
        1: bars("r:2 C5:2 E5:2 C5:2 r:2 B4:2 E5:2 B4:2", "r:2 A4:2 C5:2 A4:2 r:2 G#4:2 B4:2 G#4:2",
                "r:2 A4:2 D5:2 A4:2 r:2 F4:2 A4:2 F4:2", "r:2 G#4:2 B4:2 G#4:2 r:2 B4:2 E5:2 B4:2"),
        2: bars("A2:4 E2:4 A2:4 G2:4", "F2:4 C3:4 F2:4 E2:4", "D2:4 A2:4 D2:4 A2:4", "E2:4 B2:4 E2:4 E3:4"),
        3: bars(*["C3:4 C6:2 C6:2 C4:4 C6:2 C6:2"] * 4),
    }),
    # 2 Lungomare: the drive, E minor, a two-note lead over straight eighths
    track(136, {
        0: bars("E5:2 G5:2 E5:2 G5:2 B5:4 A5:2 G5:2", "E5:2 G5:2 E5:2 G5:2 C6:4 B5:2 G5:2",
                "D5:2 F#5:2 D5:2 F#5:2 A5:4 G5:2 F#5:2", "B4:2 D#5:2 F#5:2 B5:2 A5:2 F#5:2 D#5:4"),
        1: bars("r B4 r B4 r B4 r B4 r B4 r B4 r B4 r B4", "r C5 r C5 r C5 r C5 r C5 r C5 r C5 r C5",
                "r A4 r A4 r A4 r A4 r A4 r A4 r A4 r A4", "r B4 r B4 r B4 r B4 r B4 r B4 r B4 r B4"),
        2: bars("E2:2 E2:2 E3:2 E2:2 E2:2 E2:2 D3:2 E3:2", "C2:2 C2:2 C3:2 C2:2 C2:2 C2:2 B2:2 C3:2",
                "D2:2 D2:2 D3:2 D2:2 D2:2 D2:2 C3:2 D3:2", "B1:2 B1:2 B2:2 B1:2 B1:2 B1:2 F#2:2 B2:2"),
        3: bars(*["C3:2 C6 C6 C4:2 C6:2 C3:2 C6 C6 C4:2 C6:2"] * 4),
    }),
    # 3 Presenza: the capture, C# minor, a held line over a nervous bass
    track(126, {
        0: bars("G#5:6 E5:2 G#5:8", "A5:6 F#5:2 A5:8", "G#5:4 B5:4 C#6:8", "C6:4 B5:4 G5:8"),
        1: bars("E5 r E5 r E5 r E5 r E5 r E5 r E5 r E5 r", "F#5 r F#5 r F#5 r F#5 r F#5 r F#5 r F#5 r F#5 r",
                "E5 r E5 r E5 r E5 r E5 r E5 r E5 r E5 r", "E5 r E5 r E5 r E5 r D5 r D5 r D5 r D5 r"),
        2: bars("C#2 C#2 C#3 C#2 C#2 C#2 C#3 C#2 C#2 C#2 C#3 C#2 C#2 C#2 B2 C#3",
                "D2 D2 D3 D2 D2 D2 D3 D2 D2 D2 D3 D2 D2 D2 C#3 D3",
                "C#2 C#2 C#3 C#2 C#2 C#2 C#3 C#2 C#2 C#2 C#3 C#2 C#2 C#2 B2 C#3",
                "C2 C2 C3 C2 C2 C2 C3 C2 G1 G1 G2 G1 G1 G1 G2 B2"),
        3: bars(*["C3:4 C4:4 C3:2 C3:2 C4:4"] * 4),
    }),
    # 4 Guardiano: the apparition at Villa Doria d'Angri, D phrygian
    track(150, {
        0: bars("D5:4 Eb5:4 D5:4 C5:4", "D5:4 F5:4 Eb5:8", "A5:4 Bb5:4 A5:4 G5:4", "F5:2 Eb5:2 D5:4 Ab5:4 G5:4"),
        1: bars("r:2 A4:2 r:2 A4:2 r:2 A4:2 r:2 A4:2", "r:2 Bb4:2 r:2 Bb4:2 r:2 Bb4:2 r:2 Bb4:2",
                "r:2 A4:2 r:2 A4:2 r:2 A4:2 r:2 A4:2", "r:2 G4:2 r:2 G4:2 r:2 C5:2 r:2 Bb4:2"),
        2: bars(*["D2:3 D2 Eb2:2 D2:2 D2:3 D2 F2:2 Eb2:2"] * 3, "D2:3 D2 Eb2:2 D2:2 Ab2:4 G2:4"),
        3: bars(*["C3:2 C6:2 C4:2 C3:2 C3:2 C6:2 C4:2 C4:2"] * 4),
    }),
    # 5 Catturato: a spirit is in the trap
    track(140, {
        0: part("D5 F5 A5 D6 F6:2 D6:2 F6:4", bar=12),
        1: part("A4:4 D5:4 A5:4", bar=12),
        2: part("D3:4 A3:4 D3:4", bar=12),
    }, loop=False),
    # 6 Fuga: the spirit got away
    track(100, {
        0: part("A4:2 G#4:2 G4:2 F#4:6", bar=12),
        2: part("A2:2 G#2:2 G2:2 F#2:6", bar=12),
    }, loop=False),
    # 7 Parata: the parade on the lungomare, D major in 6/8 (one tick per quaver)
    track(104, {
        0: bars("F#5 A5 D6 F#6 D6 A5", "G5 B5 D6 G6 D6 B5", "E5 A5 C#6 E6 C#6 A5", "D6:2 F#6 A6:3",
                "A5 D6 F#6 A6 F#6 D6", "B5 D6 G6 B6 G6 D6", "A5 C#6 E6 G6 E6 C#6", "D6:3 D6:3", bar=6),
        1: bars(*["r A4 A4 r A4 A4", "r B4 B4 r B4 B4", "r A4 A4 r A4 A4", "r F#4 F#4 r A4 A4"] * 2, bar=6),
        2: bars("D2:3 A2:3", "G2:3 D3:3", "A2:3 E3:3", "D3:3 A2:3", "D2:3 A2:3", "G2:3 D3:3", "A2:3 A2:3",
                "D2:3 D3:3", bar=6),
        3: bars(*["C3 C6 C6 C4 C6 C6"] * 8, bar=6),
    }),
    # 8 Presagio: "choose the form of the destructor", a tritone over a pedal
    track(60, {
        0: bars("r:8 Eb5:8", "r:4 A4:12", "r:8 Eb5:4 D5:4", "A4:16"),
        1: bars("r:12 E6:4", "r:16", "r:12 Eb6:4", "r:16"),
        2: bars("A1:16", "A1:16", "Bb1:16", "A1:16"),
        3: bars(*["C2:16"] * 4),
    }),
    # 9 Distruttore: the giant in the piazza, a dark tarantella in A minor
    track(118, {
        0: bars("E5 E5 F5 E5 D5 C5", "D5 D5 E5 D5 C5 B4", "C5 B4 A4 G#4 A4 B4", "C5:2 E5 A5:3",
                "A5 G#5 A5 B5 A5 G#5", "F5 E5 F5 G5 F5 E5", "D5 C5 B4 E5 D5 B4", "A4:3 r:3", bar=6),
        1: bars("r E4 E4 r E4 E4", "r D4 D4 r D4 D4", "r E4 E4 r E4 E4", "r E4 E4 r E4 E4",
                "r F4 F4 r F4 F4", "r F4 F4 r F4 F4", "r E4 E4 r G#4 G#4", "r E4 E4 r E4 E4", bar=6),
        2: bars("A2:3 E3:3", "G2:3 D3:3", "A2:3 E2:3", "A2:3 E3:3", "F2:3 C3:3", "D2:3 A2:3", "E2:3 E3:3",
                "A2:3 A2:3", bar=6),
        3: bars(*["C3 C6 C6 C4 C6 C6"] * 8, bar=6),
    }),
]

out = ROOT / "audio.json"
out.write_text(json.dumps({"instruments": INSTRUMENTS, "tracks": TRACKS}, separators=(",", ":")) + "\n")
events = sum(len(t["events"]) for t in TRACKS)
print(f"{out.name}: {len(INSTRUMENTS)} instruments, {len(TRACKS)} tracks, {events} events ({events * 4} bytes)")
