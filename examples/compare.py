"""Compare an exported example sequence with the parts that were played in: per track, the tick offset of
the recorded notes from the source (0 = exact) and whether every note arrived.

  python3 -I examples/compare.py <exported midi folder>
"""
import collections
import os
import sys

import mido

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_example as B  # noqa: E402
import make_parts as P  # noqa: E402


def source(part):
    events, bars, beats = P.PARTS[part]
    return sorted((s * P.S, n) for s, l, n, v in events)


def recorded(path):
    tracks = collections.defaultdict(list)
    for tr in mido.MidiFile(path).tracks:
        t = 0
        for m in tr:
            t += m.time
            if m.type == "note_on" and m.velocity:
                tracks[m.channel + 1].append((t, m.note))
    return {k: sorted(v) for k, v in tracks.items()}


def main():
    d = sys.argv[1]
    ok = True
    for name, slot, beats, bars, tracks in B.SEQUENCES:
        mids = [f for f in os.listdir(d) if f.split("-", 1)[-1] == name + ".mid"]
        if not mids:
            print("%-9s not exported" % name); ok = False; continue
        rec = recorded(os.path.join(d, mids[0]))
        for i, (part, sound) in enumerate(tracks):
            src, got = source(part), rec.get(i + 1, [])
            if not got:
                print("%-9s track %d %-15s NO NOTES" % (name, i + 1, part)); ok = False; continue
            offs = collections.Counter(g[0] - s[0] for s, g in zip(src, got))
            same_notes = [n for _, n in src] == [n for _, n in got]
            off = offs.most_common(1)[0][0]
            exact = len(src) == len(got) and same_notes and set(offs) == {0}
            ok &= exact
            print("%-9s track %d %-15s %3d/%3d notes, offset %+5d ticks (%+.2f beats)%s" % (
                name, i + 1, part, len(got), len(src), off, off / 96, "  EXACT" if exact else
                ("  notes ok" if same_notes and len(src) == len(got) else "  NOTES DIFFER")))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
