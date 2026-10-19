"""Converter tests on synthetic MIDI OUT captures (no MAME needed).

Each case is a firmware behaviour seen on real disks: a burst of messages sent back to back on one
tick, notes in the last 3 ticks (after the final MIDI clock), the loop restart that must be trimmed,
and the malformed CC 72 the SD-1 sends at song-step changes.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import cap2mid  # noqa: E402

BPM = 120.0
TICK = 60.0 / BPM / 96          # seconds per tick at 96 PPQ
BYTE = 0.00032                  # one MIDI byte on the wire


class Capture:
    def __init__(self):
        self.rows = []

    def send(self, t, *msg):
        for i, b in enumerate(msg):
            self.rows.append((t + i * BYTE, b))
        return t + len(msg) * BYTE


def sequence(extra):
    """1 bar of 4/4: Start, a clock every 4 ticks up to and including the loop restart (tick 384),
    then Stop. extra(cap, t_of_tick) adds the notes."""
    cap = Capture()
    t0 = 1.0
    cap.send(t0 - 0.001, 0xFA)
    for k in range(0, 385, 4):
        cap.send(t0 + k * TICK, 0xF8)
    extra(cap, lambda tick: t0 + tick * TICK + 0.0004)   # notes follow the clock byte on a clock tick
    cap.send(t0 + 386 * TICK, 0xFC)
    cap.rows.sort()
    return cap.rows


def notes(mid):
    out = []
    for tr in mid.tracks:
        t = 0
        for m in tr:
            t += m.time
            if m.type == "note_on" and m.velocity:
                out.append((t, m.channel, m.note))
    return sorted(out)


def convert(rows):
    mid, info = cap2mid.convert(rows, "test", BPM, nominal=BPM, sigs=[(0.0, (4, 4))], bars=1)
    return notes(mid), info


class Cap2Mid(unittest.TestCase):
    def test_burst_shares_one_tick(self):
        def add(cap, at):
            t = at(96)
            for n in range(6):                   # six notes due on tick 96, sent back to back
                t = cap.send(t, 0x90, 60 + n, 100)
        got, _ = convert(sequence(add))
        self.assertEqual([t for t, _, _ in got], [96] * 6)   # the last ones arrive > half a tick late

    def test_separate_ticks_stay_separate(self):
        def add(cap, at):
            for k in (100, 101, 102):
                cap.send(at(k), 0x90, 60, 100)
        got, _ = convert(sequence(add))
        self.assertEqual([t for t, _, _ in got], [100, 101, 102])

    def test_last_ticks_kept_and_restart_trimmed(self):
        def add(cap, at):
            cap.send(at(383), 0x90, 64, 100)     # after the final clock (tick 380)
            cap.send(at(383) + 0.002, 0x80, 64, 0)
            cap.send(at(384), 0x90, 65, 100)     # the loop starting again
        got, info = convert(sequence(add))
        self.assertEqual(got, [(383, 0, 64)])
        self.assertEqual(info["trimmed_after_end"], 1)
        self.assertEqual(info["bars_check"], "ok")

    def test_burst_never_spans_a_clock(self):
        def add(cap, at):
            for tick, first_note, next_note in ((383, 40, 65), (199, 50, 67)):
                # as captured: the next tick's first note follows its clock byte at once, 1.0 ms after
                # the end of a back-to-back burst that began early in the previous tick
                nxt = 1.0 + (tick + 1) * TICK + 0.0003
                starts, t = [], nxt - 0.0010
                while t > at(tick) + 0.0006:
                    starts.append(t)
                    t -= 3 * BYTE
                for k, t in enumerate(sorted(starts)):
                    cap.send(t, 0x90, first_note + k, 100)
                cap.send(nxt, 0x90, next_note, 100)
        got, _ = convert(sequence(add))
        self.assertIn((200, 0, 67), got)            # stays on its own tick, not pulled back to 199
        self.assertNotIn(65, [n for _, _, n in got])  # the loop restart's note is trimmed
        self.assertTrue(all(t in (199, 383) for t, _, n in got if n != 67))

    def test_malformed_cc72_is_dropped(self):
        def add(cap, at):
            cap.send(at(8), 0xB9, 0x47, 0x00, 0x48, 0x9D, 0x07, 0x7F)   # CC 72 with a value byte >= 0x80
            cap.send(at(12), 0x90, 60, 100)
        got, info = convert(sequence(add))
        self.assertEqual(got, [(12, 0, 60)])     # no phantom note on channel 14
        self.assertEqual(info["malformed_cc_dropped"], 1)


if __name__ == "__main__":
    unittest.main()
