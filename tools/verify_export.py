"""Sanity-check an export: a song's notes on channels 1-12 (sequence tracks) should equal the
sum of its steps' sequences (times reps) when no step mutes tracks; notes on 13-16 are the
song's own tracks and are reported separately.

usage: python3 -I tools/verify_export.py out/<disk>/midi/<FILE>
"""
import itertools
import json
import os
import sys

import mido

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import layout  # noqa: E402


def notes_by_channel(path):
    out = {}
    for tr in mido.MidiFile(path).tracks:
        for m in tr:
            if m.type == "note_on" and m.velocity:
                out[m.channel + 1] = out.get(m.channel + 1, 0) + 1
    return out

d = sys.argv[1]
m = json.load(open(layout.manifest(d)))
info = {}   # name -> [(out, json)]: names can repeat in a bank (two sequences called VERSE)
ok = True
for x in m["sequences"]:
    p = layout.info(d, x["out"])
    if os.path.exists(p) and os.path.getsize(p):
        j = json.load(open(p))
        info.setdefault(x["name"], []).append((x["out"], j))
        bc = j.get("bars_check", "not read")
        ok &= bc in ("ok", "not read")
        print("  %-22s %5d notes %7.2f beats  tempo %-6s %s  bars %s" % (
            x["out"], j["notes"], j["beats"], j["tempos"][0][1] if j["tempos"] else "?",
            ",".join(e.split(":")[1] for e in j.get("timesig", [])) or "?", bc))
for s in m["songs"]:
    if not s["steps"]:
        print("  %-22s empty song (no steps), not exported" % s["out"])
        continue
    p = layout.info(d, s["out"])
    if not (os.path.exists(p) and os.path.getsize(p)):
        print("  %s: no export" % s["out"]); ok = False; continue
    j = json.load(open(p))

    def seqlen(j):   # bars x meter when known, else the captured length
        if j.get("bars") and j.get("timesig"):
            n, dd = (int(v) for v in j["timesig"][0].split(":")[1].split("/"))
            return j["bars"] * n * 4 / dd
        return round(j["beats"])
    ch = notes_by_channel(layout.mid(d, s["out"]))
    seq_notes = sum(n for c, n in ch.items() if c <= 12)
    song_notes = sum(n for c, n in ch.items() if c > 12)
    used = [st for st in s["steps"] if st["seq"] in info and isinstance(st["reps"], int)]
    # A step shows only the sequence's name. With repeated names, try each candidate per step
    # (one song can use both of two same-named sequences), or per name if that's too many combinations.
    amb = [i for i, st in enumerate(used) if len(info[st["seq"]]) > 1]
    per_step = 2 ** len(amb) <= 1 << 16
    if per_step:
        picks = itertools.product(*(info[used[i]["seq"]] for i in amb))
    else:
        names = sorted({used[i]["seq"] for i in amb})
        picks = (tuple(dict(zip(names, p))[used[i]["seq"]] for i in amb)
                 for p in itertools.product(*(info[n] for n in names)))
    for pick in picks:
        choice = [info[st["seq"]][0] for st in used]
        for i, c in zip(amb, pick):
            choice[i] = c
        exp = sum(c[1]["notes"] * st["reps"] for c, st in zip(choice, used))
        exp_beats = sum(seqlen(c[1]) * st["reps"] for c, st in zip(choice, used))
        good = exp == seq_notes and abs(exp_beats - j["beats"]) < 0.5
        if good:
            break
    ok &= good
    steps = " ".join("%s%s" % (st["seq"], "x%s" % st["reps"] if st["reps"] != 1 else "") for st in s["steps"])
    dup = ["step %d %s = %s" % (used[i]["step"], used[i]["seq"], choice[i][0]) for i in amb]
    print("  %-22s %5d notes on sequence tracks (steps sum %d), %d on song tracks; %.0f beats (steps sum %g)  %s\n"
          "    %s\n    steps: %s%s" % (
        s["out"], seq_notes, exp, song_notes, j["beats"], exp_beats, "OK" if good else "MISMATCH", j["timing"], steps,
        ("\n    repeated names: " + ", ".join(dup) + (" (the match)" if good else " (no candidate matches)")) if dup else ""))
sys.exit(0 if ok else 1)
