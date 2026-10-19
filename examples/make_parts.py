"""Write the original material for the example disk as MIDI files (played into the emulated SD-1's MIDI IN).

  python3 -I examples/make_parts.py work/example/parts

Every part is 16th-note quantised at 120 BPM, starts on beat 1 of its first bar and ends before the last
16th of its last bar. The SD-1's first take sets a sequence's length from where Stop is pressed, so nothing
may sound in that last moment. Also writes name-NAME.mid files that type a name with the SD-1's
keyboard-naming feature (white keys from C2 = 0-9, A-Z; black keys = cursor left/right, space, dash, plus).
"""
import os
import sys

import mido

PPQ = 96
BAR = 4 * PPQ
S = PPQ // 4            # one 16th note

# --- music -----------------------------------------------------------------------------------------
# (start in 16ths from the part's beginning, length in 16ths, MIDI note, velocity)

KICK, SNARE, HAT, OPEN, TOM_HI, TOM_LO, CRASH = 36, 38, 42, 46, 48, 45, 49


def drums_a(bars=4):
    out = []
    for b in range(bars):
        o = b * 16
        out += [(o + 0, 1, KICK, 110), (o + 6, 1, KICK, 90), (o + 8, 1, KICK, 105), (o + 10, 1, KICK, 80)]
        out += [(o + 4, 1, SNARE, 110), (o + 12, 1, SNARE, 112)]
        out += [(o + k, 1, HAT, 70 if k % 4 else 95) for k in range(0, 16, 2)]
    return out


def drums_b(bars=4):
    out = []
    for b in range(bars):
        o = b * 16
        out += [(o + 0, 1, KICK, 115), (o + 3, 1, KICK, 85), (o + 8, 1, KICK, 110), (o + 11, 1, KICK, 90)]
        out += [(o + 4, 1, SNARE, 112), (o + 12, 1, SNARE, 115), (o + 13, 1, SNARE, 60) if b % 2 else (o + 14, 1, OPEN, 80)]
        out += [(o + k, 1, HAT, 60 + (25 if k % 4 == 0 else 0)) for k in range(16) if k not in (14, 15)]
    out.append((0, 1, CRASH, 100))
    return out


def drums_fill():
    out = [(k, 1, SNARE, 70 + 4 * k) for k in range(0, 8)]
    out += [(8, 1, TOM_HI, 110), (9, 1, TOM_HI, 100), (10, 1, TOM_LO, 110), (11, 1, TOM_LO, 100)]
    out += [(12, 1, KICK, 120), (12, 1, SNARE, 120), (13, 1, SNARE, 100), (14, 1, SNARE, 110)]
    return out


ROOTS_A = [45, 41, 48, 43]            # A F C G (bass, one bar each)
CHORDS_A = [[57, 60, 64, 67], [53, 57, 60, 64], [52, 55, 60, 64], [50, 55, 59, 62]]   # Am7 Fmaj7 C/E G/D


def bass_a(roots=ROOTS_A):
    out = []
    for b, r in enumerate(roots):
        o = b * 16
        out += [(o + 0, 3, r, 105), (o + 3, 1, r + 12, 80), (o + 6, 2, r, 95), (o + 10, 2, r + 7, 90), (o + 12, 2, r + 12, 85)]
    return out


def bass_b(roots=ROOTS_A):
    out = []
    for b, r in enumerate(roots):
        o = b * 16
        out += [(o + k, 1, r + (12 if k in (3, 11) else 0), 100 if k % 4 == 0 else 78) for k in range(0, 15, 1) if k % 2 == 0 or k in (3, 11)]
    return out


def chords_a():
    out = []
    for b, ch in enumerate(CHORDS_A):
        o = b * 16
        for start, length, vel in ((0, 3, 90), (6, 2, 70), (10, 4, 80)):
            out += [(o + start, length, n, vel) for n in ch]
    return out


def lead_b():
    phrase = [(0, 2, 76), (2, 2, 74), (4, 4, 72), (8, 2, 69), (10, 2, 72), (12, 3, 74),
              (16, 2, 72), (18, 2, 69), (20, 6, 67), (28, 3, 69),
              (32, 2, 76), (34, 2, 79), (36, 4, 81), (40, 2, 79), (42, 2, 76), (44, 3, 74),
              (48, 4, 72), (52, 4, 74), (56, 6, 76)]
    return [(s, l, n, 96) for s, l, n in phrase]


def ending_chords():                   # 2 bars of 3/4: 12 sixteenths per bar
    return [(0, 5, n, 95) for n in (57, 60, 64, 69)] + [(12, 10, n, 100) for n in (45, 57, 64, 69, 72)]


def ending_bass():
    return [(0, 5, 45, 105), (6, 2, 52, 85), (8, 2, 55, 85), (12, 10, 33, 110)]


PARTS = {
    "groove-a-drums": (drums_a(), 4, 4),      # name: (events, bars, beats per bar)
    "groove-a-bass": (bass_a(), 4, 4),
    "groove-a-keys": (chords_a(), 4, 4),
    "groove-b-drums": (drums_b(), 4, 4),
    "groove-b-bass": (bass_b(), 4, 4),
    "groove-b-lead": (lead_b(), 4, 4),
    "fill-drums": (drums_fill(), 1, 4),
    "ending-keys": (ending_chords(), 2, 3),
    "ending-bass": (ending_bass(), 2, 3),
}


def vlq(n):
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append(0x80 | (n & 0x7F))
        n >>= 7
    return bytes(reversed(out))


def write_clocked(path, events, bars, beats, lead_bars=0, channel=0):
    """A part that drives the SD-1's sequencer on external clock (Seq Control CLOCK=MIDI): MIDI Start,
    a MIDI Clock every 4 ticks (24 per beat), the notes after lead_bars of clock (the count-off of a later
    take), and MIDI Stop at the end. Start, Clock and Stop are written as SMF escape events (F7 len byte),
    which MAME's MIDI IN plays as raw bytes. With the SD-1 following this clock the recording is exact."""
    bar = beats * PPQ
    lead, end = lead_bars * bar, lead_bars * bar + bars * bar
    ev = [(0, 0, b"\xF7\x01\xFA")]
    ev += [(k, 1, b"\xF7\x01\xF8") for k in range(0, end, 4)]
    for start, length, note, vel in events:
        ev.append((lead + start * S, 3, bytes([0x90 | channel, note, vel])))
        ev.append((lead + start * S + length * S - 4, 2, bytes([0x80 | channel, note, 64])))
    ev.append((end, 4, b"\xF7\x01\xFC"))
    ev.sort(key=lambda e: (e[0], e[1]))
    body, t = bytearray(b"\x00\xFF\x51\x03\x07\xA1\x20"), 0       # tempo 120 BPM
    for at, _, data in ev:
        body += vlq(at - t) + data
        t = at
    body += b"\x00\xFF\x2F\x00"
    with open(path, "wb") as f:
        f.write(b"MThd" + (6).to_bytes(4, "big") + (0).to_bytes(2, "big") + (1).to_bytes(2, "big") +
                PPQ.to_bytes(2, "big") + b"MTrk" + len(body).to_bytes(4, "big") + bytes(body))


def write_part(path, events, channel=0):
    msgs = []
    for start, length, note, vel in events:
        msgs.append((start * S, 1, mido.Message("note_on", channel=channel, note=note, velocity=vel)))
        msgs.append((start * S + length * S - 4, 0, mido.Message("note_off", channel=channel, note=note, velocity=64)))
    msgs.sort(key=lambda m: (m[0], m[1]))
    mid = mido.MidiFile(ticks_per_beat=PPQ)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.MetaMessage("set_tempo", tempo=500000, time=0))   # 120 BPM, the SD-1's default
    t = 0
    for at, _, m in msgs:
        tr.append(m.copy(time=at - t))
        t = at
    mid.save(path)


# --- names -----------------------------------------------------------------------------------------

CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
WHITE = [0, 2, 4, 5, 7, 9, 11]
BLACK = {"<": 1, ">": 3, " ": 6, "-": 8, "+": 10}   # within an octave from C


def key_for(ch):
    if ch in CHARS:
        k = CHARS.index(ch)
        return 36 + 12 * (k // 7) + WHITE[k % 7]
    return 36 + BLACK[ch]


def write_name(path, name, width=11):
    text = name.upper().ljust(width)
    mid = mido.MidiFile(ticks_per_beat=PPQ)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.MetaMessage("set_tempo", tempo=500000, time=0))
    # the cursor doesn't advance by itself: follow every character with cursor-right (a black key)
    first = True
    for ch in text:
        for n in (key_for(ch), key_for(">")):
            tr.append(mido.Message("note_on", note=n, velocity=80, time=0 if first else 50))
            tr.append(mido.Message("note_off", note=n, velocity=64, time=10))
            first = False
    mid.save(path)


NAMES = ["GROOVE-A", "GROOVE-B", "FILL", "ENDING", "EXAMPLE"]


def write_sysex(path):
    """Two SysEx messages of our own, with the non-commercial manufacturer ID 7D (nothing anyone owns)."""
    text = b"SD-1 DISK IMAGE EXTRACTOR EXAMPLE DUMP"
    msgs = [b"\xF0\x7D\x01" + text + b"\xF7",
            b"\xF0\x7D\x02" + bytes(range(0, 128, 3)) + b"\xF7"]
    with open(path, "wb") as f:
        f.write(b"".join(msgs))


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join("work", "example", "parts")
    os.makedirs(out, exist_ok=True)
    for name, (events, bars, beats) in PARTS.items():
        last = max(s + l for s, l, _, _ in events)
        assert last <= bars * beats * 4 - 1, name + " sounds in its last 16th"
        write_part(os.path.join(out, name + ".mid"), events)
        write_clocked(os.path.join(out, name + "-first.mid"), events, bars, beats, 0)
    for name in NAMES:
        write_name(os.path.join(out, "name-%s.mid" % name), name)
    write_name(os.path.join(out, "name-EXAMPLE-SONG.mid"), "EXAMPLE", width=10)   # songs: '$' + 10 characters
    write_sysex(os.path.join(out, "example.syx"))
    print("wrote %d parts and %d names to %s" % (len(PARTS), len(NAMES), out))


if __name__ == "__main__":
    main()
