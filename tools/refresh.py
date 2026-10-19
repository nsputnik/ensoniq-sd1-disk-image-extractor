"""Rebuild every exported .mid from its .cap capture with the current cap2mid.py.

Each .json records the converter arguments it was made with ("args"); older ones are
reconstructed from what the .json says (name, SD-1 track names, set tempo or song tempo
map). No emulation is involved, so this takes seconds.

usage: python3 -I tools/refresh.py [out/<disk>/midi/<FILE> ...]     (default: every export under out/)
"""
import glob
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import layout  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def args_for(cap, info):
    if info.get("args"):
        return info["args"][2:]   # drop the old capture / output paths
    a = ["--name", info["name"]]
    tr = info.get("sd1_tracks") or []
    if any(tr):
        a.append("--tracks=" + "|".join(tr))
    timing = info.get("timing", "")
    if "song tempo map" in timing:
        a += ["--tempo-map", ",".join("%g:%g" % (tick / 96, bpm) for tick, bpm in info["tempos"])]
    elif "set tempo" in timing:
        a += ["--tempo", "%g" % info["tempos"][0][1]]
    return a


def main():
    dirs = sys.argv[1:] or sorted(os.path.dirname(os.path.dirname(m)) for m in
                                  glob.glob(os.path.join(ROOT, "out", "*", "midi", "*", "json", "manifest.json")))
    for d in dirs:
        for cap in sorted(glob.glob(os.path.join(d, "cap", "*.cap"))):
            name = os.path.basename(cap)[:-4]
            jp, mp = layout.info(d, name), layout.mid(d, name)
            info = {}
            if os.path.exists(jp) and os.path.getsize(jp):
                info = json.load(open(jp))
            if not info:
                print("  %s: no .json, skipped" % os.path.relpath(cap, ROOT))
                continue
            cmd = [sys.executable, "-I", os.path.join(HERE, "cap2mid.py"), cap, mp] + args_for(cap, info)
            r = subprocess.run(cmd, capture_output=True, text=True)
            if not r.stdout.strip():
                print("  %s: FAILED %s" % (os.path.relpath(cap, ROOT), r.stderr.strip().splitlines()[-1:]))
                continue
            new = json.loads(r.stdout)
            new["args"] = [os.path.basename(cap), os.path.basename(mp)] + args_for(cap, info)
            open(jp, "w").write(json.dumps(new))
            note = ""
            if new["notes"] != info.get("notes"):
                note = "  notes %s -> %s" % (info.get("notes"), new["notes"])
            if new.get("malformed_cc_dropped"):
                note += "  (%d malformed CC dropped)" % new["malformed_cc_dropped"]
            if note or new["timing"] != info.get("timing"):
                print("  %-44s%s" % (os.path.relpath(mp, ROOT), note))


if __name__ == "__main__":
    main()
