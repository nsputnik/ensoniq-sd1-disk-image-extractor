"""Convert a MIDI OUT capture from mame/sd1.lua into a Standard MIDI File.

The capture is "<emulated-seconds> <byte>" per line: every byte the emulated SD-1
wrote to its MIDI OUT UART. Timing is taken from the SD-1's own MIDI clock (F8,
24 per quarter note) rather than from seconds: each event is placed between the
two clocks around it, at 96 PPQ (the SD-1 sequencer's native resolution, so 4
ticks per clock). Tempo comes from the clock spacing. Without clocks it falls
back to emulated seconds at a fixed --bpm.

With --tempo (the sequence's set tempo, read off the SD-1 display), the file gets
that exact tempo; note positions still come from the clock, so they are unaffected
by the emulated clock running a fraction of a percent off nominal.

For a song, --tempo-map "0:121,32:123,..." (beat:bpm, from the song steps) does the same per
section; each section is checked against the measured clock and the map is only used if all agree.

Time signature: --timesig 3/4 (from the SD-1 Locate page) or, for a song, --timesig-map
"0:4/4,32:3/4,..." (beat:N/D, one entry per song step whose sequence changes meter).
--bars N (the INFO page's BARS) is checked against the captured length.

usage: python3 -I tools/cap2mid.py capture.cap out.mid [--name NAME] [--tempo 120 | --tempo-map MAP]
                                   [--timesig 4/4 | --timesig-map MAP] [--bars N] [--bpm 120]
"""
import argparse
import bisect
import json
import sys

import mido

PPQ = 96
TICKS_PER_CLOCK = PPQ // 24
LEN = {0x80: 3, 0x90: 3, 0xA0: 3, 0xB0: 3, 0xC0: 2, 0xD0: 2, 0xE0: 3}


def read_capture(path):
    rows = []
    with open(path) as f:
        for line in f:
            t, b = line.split()
            rows.append((float(t), int(b)))
    return rows


def parse(rows):
    """Split the byte stream into channel events and realtime markers (handles running status)."""
    events, clocks, start, stop = [], [], None, None
    running, data, t_msg = 0, [], 0.0
    malformed = 0
    for t, b in rows:
        if b >= 0xF8:
            if b == 0xF8:
                clocks.append(t)
            elif b == 0xFA and start is None:
                start = t
            elif b == 0xFC:
                stop = t
            continue
        if b >= 0xF0:
            running, data = 0, []   # sysex / system common: not part of the performance
            continue
        if b >= 0x80 and running & 0xF0 == 0xB0 and len(data) == 1:
            # SD-1 firmware quirk: some track-setup controllers (CC 72 at sequence start) are
            # sent with a value byte >= 0x80. The firmware writes whole messages, so a status
            # byte can't legitimately land here; treating it as one would invent notes (e.g.
            # "48 9D 07 7F" -> note-on ch14). Drop the malformed controller, keep running status.
            malformed += 1
            data = []
            continue
        if b >= 0x80:
            running, data, t_msg = b, [], t
            continue
        if not running:
            continue
        if not data:
            t_msg = t
        data.append(b)
        if len(data) + 1 == LEN[running & 0xF0]:
            events.append((t_msg, [running] + data))
            data = []
    return events, clocks, start, stop, malformed


def tick_from_clocks(clocks):
    """Unrounded tick of a time, interpolated between the MIDI clocks around it."""
    def frac(t):
        if t <= clocks[0]:
            return 0.0
        j = bisect.bisect_right(clocks, t) - 1
        if j + 1 < len(clocks):
            span = clocks[j + 1] - clocks[j]
        else:
            span = clocks[j] - clocks[j - 1] if j > 0 else 0.5 / 24
        return TICKS_PER_CLOCK * (j + (t - clocks[j]) / span)
    return frac


BURST_GAP = 0.0013   # s; one 3-byte message on the wire takes 0.96 ms


def burst_ticks(events, frac, clocks=()):
    """The SD-1 sends everything due on one tick as a back-to-back burst, paced by the serial
    line, so the last messages of a big burst can be timestamped more than half a tick late (and
    round onto the next tick, or past a sequence's end). A message starting within BURST_GAP of
    the previous one, and less than a tick after the burst's first message, gets the first
    message's tick. (A longer run is ambiguous: the next tick's burst may have joined the queue.)
    A MIDI clock always starts a new tick, so a burst never spans one: notes sent just before the
    loop-restart clock must not pull the restart's notes back into the sequence.
    frac(t) is the unrounded tick."""
    out, prev, first = [], None, None
    for t, _ in events:
        f = frac(t)
        clock_between = prev is not None and bisect.bisect_right(clocks, t) > bisect.bisect_right(clocks, prev)
        if prev is None or t - prev > BURST_GAP or f - first >= 1.0 or clock_between:
            first = f
        out.append(round(first))
        prev = t
    return out


def tempo_map(clocks):
    """(tick, bpm) at each beat whose average clock spacing differs from the previous one."""
    out = []
    for beat in range(0, (len(clocks) - 1) // 24):
        span = clocks[(beat + 1) * 24] - clocks[beat * 24]
        bpm = round(60.0 / span, 2)
        if not out or abs(out[-1][1] - bpm) > 0.05:
            out.append((beat * PPQ, bpm))
    if not out and len(clocks) > 1:
        out.append((0, round(60.0 / ((clocks[-1] - clocks[0]) / (len(clocks) - 1) * 24), 2)))
    return out


def check_map(clocks, tmap):
    """Use the expected tempo map only if every section matches the measured clock within 2%."""
    worst = 0.0
    for i, (beat, bpm) in enumerate(tmap):
        a = round(beat * 24)
        b = round(tmap[i + 1][0] * 24) if i + 1 < len(tmap) else len(clocks) - 1
        b = min(b, len(clocks) - 1)
        if b - a < 2:
            continue
        measured = 60.0 * (b - a) / ((clocks[b] - clocks[a]) * 24)
        worst = max(worst, abs(measured - bpm) / bpm)
    return worst


def parse_sig(text):
    num, den = (int(x) for x in text.split("/"))
    if den & (den - 1) or not 1 <= num <= 99:
        raise ValueError("bad time signature %r" % text)
    return num, den


def convert(rows, name, bpm_fallback, nominal=None, tracknames=None, tmap=None,
            sigs=None, bars=None):
    events, clocks, start, stop, malformed = parse(rows)
    if start is not None:
        clocks = [c for c in clocks if c >= start]
    if stop is not None:
        events_play = [e for e in events if e[0] <= stop + 0.05]
    else:
        events_play = events
    if len(clocks) >= 2:
        frac = tick_from_clocks(clocks)
        tempos = tempo_map(clocks)
        timing = "midi-clock"
        measured = 60.0 * (len(clocks) - 1) / ((clocks[-1] - clocks[0]) * 24)
        if tmap:
            worst = check_map(clocks, tmap)
            if worst < 0.02:
                tempos = [(round(beat * PPQ), bpm) for beat, bpm in tmap]
                timing = "midi-clock, song tempo map (%d sections, worst section %.2f%% off)" % (len(tmap), worst * 100)
            else:
                timing = "midi-clock (tempo map rejected: %.1f%% off)" % (worst * 100)
        elif nominal and abs(measured - nominal) / nominal < 0.02:
            tempos = [(0, nominal)]
            timing = "midi-clock, set tempo %g (measured %.2f)" % (nominal, measured)
    else:
        t0 = start if start is not None else (events[0][0] if events else 0.0)
        frac = lambda t: max(0.0, (t - t0) * bpm_fallback / 60 * PPQ)
        tempos = [(0, bpm_fallback)]
        timing = "seconds@%gbpm" % bpm_fallback

    # With --bars and --timesig the sequence length is known: anything at or after it is the
    # loop restart (captures play looped and stop by clock count); note-offs are clamped to it.
    length = None
    if bars and sigs:
        n, d = sigs[0][1]
        length = bars * n * 4 * PPQ // d
    tracks = {}   # channel -> list of (tick, order, mido.Message)
    held = {}     # (ch, note) -> count
    trimmed = 0
    ticks_of = burst_ticks(events_play, frac, clocks)
    for i, (t, ev) in enumerate(events_play):
        st, ch = ev[0] & 0xF0, ev[0] & 0x0F
        tick = ticks_of[i]
        if length is not None and tick >= length:
            if st == 0x80 or (st == 0x90 and ev[2] == 0):
                tick = length
            else:
                trimmed += 1
                continue
        if st == 0x90 and ev[2] > 0:
            msg = mido.Message("note_on", channel=ch, note=ev[1], velocity=ev[2])
            held[(ch, ev[1])] = held.get((ch, ev[1]), 0) + 1
        elif st in (0x80, 0x90):
            msg = mido.Message("note_off", channel=ch, note=ev[1], velocity=ev[2] if st == 0x80 else 0)
            if held.get((ch, ev[1])):
                held[(ch, ev[1])] -= 1
        elif st == 0xB0:
            msg = mido.Message("control_change", channel=ch, control=ev[1], value=ev[2])
        elif st == 0xC0:
            msg = mido.Message("program_change", channel=ch, program=ev[1])
        elif st == 0xD0:
            msg = mido.Message("aftertouch", channel=ch, value=ev[1])
        elif st == 0xA0:
            msg = mido.Message("polytouch", channel=ch, note=ev[1], value=ev[2])
        else:
            msg = mido.Message("pitchwheel", channel=ch, pitch=(ev[2] << 7 | ev[1]) - 8192)
        tracks.setdefault(ch, []).append((tick, i, msg))
    ticks = [e[0] for v in tracks.values() for e in v]
    if stop is not None:
        ticks.append(round(frac(stop)))
    end_tick = max(ticks, default=0) if length is None else length
    hanging = 0
    for (ch, note), n in held.items():
        for _ in range(n):
            tracks[ch].append((end_tick, 10**9, mido.Message("note_off", channel=ch, note=note, velocity=0)))
            hanging += 1

    mid = mido.MidiFile(type=1, ticks_per_beat=PPQ)
    meta = mido.MidiTrack()
    meta.append(mido.MetaMessage("track_name", name=name, time=0))
    sigs = sigs or [(0, (4, 4))]
    metas = [(round(beat * PPQ), 0, mido.MetaMessage("time_signature", numerator=n, denominator=d))
             for beat, (n, d) in sigs]
    metas += [(tick, 1, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm))) for tick, bpm in tempos]
    last = 0
    for tick, _, msg in sorted(metas, key=lambda m: (m[0], m[1])):
        meta.append(msg.copy(time=tick - last))
        last = tick
    meta.append(mido.MetaMessage("end_of_track", time=max(0, end_tick - last)))
    mid.tracks.append(meta)
    notes = 0
    for ch in sorted(tracks):
        tr = mido.MidiTrack()
        label = "SD-1 ch %d" % (ch + 1)
        if tracknames and ch < len(tracknames) and tracknames[ch].lstrip("*"):
            label = "Track %d %s" % (ch + 1, tracknames[ch].lstrip("*"))
        tr.append(mido.MetaMessage("track_name", name=label, time=0))
        last = 0
        for tick, _, msg in sorted(tracks[ch], key=lambda e: (e[0], e[1])):
            tr.append(msg.copy(time=tick - last))
            last = tick
            notes += msg.type == "note_on"
        tr.append(mido.MetaMessage("end_of_track", time=max(0, end_tick - last)))
        mid.tracks.append(tr)
    info = {
        "name": name, "timing": timing, "tempos": tempos, "channels": [c + 1 for c in sorted(tracks)],
        "notes": notes, "clocks": len(clocks), "beats": round(end_tick / PPQ, 2),
        "seconds": round((stop if stop is not None else (rows[-1][0] if rows else 0)) - (start or 0), 3)
        if start is not None else None,
        "forced_note_offs": hanging,
        "malformed_cc_dropped": malformed,
        "trimmed_after_end": trimmed,
        "sd1_tracks": tracknames or [],
        "timesig": ["%g:%d/%d" % (b, n, d) for b, (n, d) in sigs],
    }
    if bars:
        # did the sequencer actually run for the whole length? (clocks played, not the trimmed end)
        n, d = sigs[0][1]
        expect = bars * n * 4 / d
        played = len(clocks) / 24
        info["bars"] = bars
        info["played_beats"] = round(played, 2)
        info["bars_check"] = "ok" if played >= expect - 0.5 else (
            "MISMATCH: %d bars of %d/%d = %g beats, sequencer only ran %g" % (bars, n, d, expect, played))
    return mid, info


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("capture")
    ap.add_argument("out")
    ap.add_argument("--name", default="SD-1 sequence")
    ap.add_argument("--bpm", type=float, default=120.0, help="tempo when the capture has no MIDI clock")
    ap.add_argument("--tempo", type=float, help="the sequence's set tempo (from the SD-1 display)")
    ap.add_argument("--tempo-map", help="beat:bpm,beat:bpm,... expected tempo per song section")
    ap.add_argument("--timesig", help="N/D, the sequence's time signature (SD-1 Locate page)")
    ap.add_argument("--timesig-map", help="beat:N/D,beat:N/D,... time signature per song section")
    ap.add_argument("--bars", type=int, help="bar count from the SD-1 INFO page, checked against the length")
    ap.add_argument("--tracks", help="'|'-separated SD-1 track program names, track N = channel N "
                    "(a leading * marks a track the SD-1 shows as holding data)")
    a = ap.parse_args()
    mid, info = convert(read_capture(a.capture), a.name, a.bpm, a.tempo or (a.bpm if a.bpm != 120.0 else None),
                        a.tracks.split("|") if a.tracks else None,
                        [(float(b), float(t)) for b, t in (x.split(":") for x in a.tempo_map.split(","))]
                        if a.tempo_map else None,
                        [(float(b), parse_sig(x)) for b, x in (e.split(":") for e in a.timesig_map.split(","))]
                        if a.timesig_map else ([(0.0, parse_sig(a.timesig))] if a.timesig else None),
                        a.bars)
    mid.save(a.out)
    info["args"] = sys.argv[1:]   # so tools/refresh.py can rebuild this file from its capture
    print(json.dumps(info))
    return 0 if info["notes"] else 2


if __name__ == "__main__":
    sys.exit(main())
