"""Export every sequence and song in one SD-1 sequence file on a disk image to MIDI.

  python3 -I tools/export_file.py "SD1-PALETTE" 60 --disk work/disk.img
  python3 -I tools/export_file.py " COUNTRY-*" 60
  python3 -I tools/export_file.py "ROCK-BEATS" 30

FILE is the name exactly as `tools/sd1disk.py` lists it (keep leading spaces); 60 or 30 is
the file type (SixtySequences / ThirtySequences). Runs MAME (windowed, via mame/run.sh)
several times; watch progress at http://127.0.0.1:8017/ (python3 -I monitor/serve.py).

  1. load   - boot the saved Sequencer-OS state, load FILE from the floppy, save a state
  2. map    - read the 10 sequencer banks; walk each song's step list
  3. export - every sequence with data -> <exports>/<FILE>/<b.s-NAME>.mid; then each song
              (all sequences prepared with MIDI on and changes kept, then one song capture)
  4. songs get a tempo map from their steps (sequence tempo + the song's tempo offset)

Writes <exports>/<FILE>/json/manifest.json describing banks, songs and outputs.
Only .mid files sit at the top of <exports>/<FILE>/; see tools/layout.py for cap/ json/ logs/.
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import layout  # noqa: E402
import make_steps  # noqa: E402

TYPE = {"60": "TYPE=60-SEQ", "30": "TYPE=30-SEQ"}


def run(steps, path, disk, seconds, log, fatal=True):
    with open(path, "w") as f:
        f.write("\n".join(steps + ["note all done", "exit"]) + "\n")
    env = dict(os.environ, SD1_SECONDS=str(seconds))
    with open(log, "w") as out:
        subprocess.run([os.path.join(ROOT, "mame", "run.sh"), path, disk], stdout=out,
                       stderr=subprocess.STDOUT, env=env, check=False)
    text = open(log).read()
    bad = re.findall(r"(FAILED: .*|LUA ERROR: .*)", text)
    if bad:
        msg = "MAME run failed (%s): %s" % (log, bad[0])
        if fatal:
            sys.exit(msg)
        print(msg)
    return text.splitlines()


def frames(lines, tag):
    """The two display rows printed after a dump line ending in tag."""
    out = []
    for i, l in enumerate(lines):
        if re.search(r"\] %s$" % re.escape(tag), l) and i + 2 < len(lines):
            out.append([lines[i + 1].strip()[1:-1], lines[i + 2].strip()[1:-1]])
    return out


def fields(rows):
    """Six (has_data, name) slots from a bank or tracks page."""
    out = []
    for row in rows:
        for k in range(3):
            col = 4 + 12 * k
            out.append((row[col:col + 1] == ".", row[col + 1:col + 12].strip()))
    return out


def clean(name):
    m = re.fullmatch(r"-(\w)-", name)
    if m:
        return m.group(1)
    return re.sub(r"[^A-Za-z0-9+=-]+", "_", name.strip("$ ")).strip("_") or "unnamed"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("type", choices=["60", "30"])
    ap.add_argument("--disk", required=True, help="disk image to mount (use a copy; tools/export_disk.py makes one)")
    ap.add_argument("--exports", default=os.path.join(ROOT, "out", "midi"),
                    help="parent folder for <exports>/<FILE>/ (e.g. one folder per disk)")
    ap.add_argument("--only", choices=["sequences", "songs"], help="skip the other half of the export")
    ap.add_argument("--skip-existing", action="store_true", help="don't redo sequences/songs that already have a .mid")
    a = ap.parse_args()

    slug = clean(a.file)
    outdir = os.path.join(os.path.abspath(a.exports), slug)
    stepdir = os.path.join(ROOT, "mame", "steps")
    os.makedirs(stepdir, exist_ok=True)
    layout.ensure(outdir)
    state = "file-" + slug.lower()
    disk = os.path.abspath(a.disk)

    # 1+2. load the file, save a state, read the banks
    show = a.file.rstrip()
    steps = [f"note loading {show} from disk", "load seqos", "wait 1", "reinsert",
             "press storage", "press sl2", "wait 1", "press sl2", "wait 1",
             f"seek down 12 {TYPE[a.type]}", "press su1", f"seek up 60 FILE={show}",
             "dump chosen", "press su3", "wait 1",
             # a 30-sequence file may ask where to load; take the default offered
             "until COMPLETED 240", "wait 2", "press seqbank", "wait 1", f"save {state}",
             "note reading banks"]
    for b in range(10):
        steps += [f"press b{b}", f"dump BANK{b}"]
    lines = run(steps, os.path.join(stepdir, f"{slug}-load.steps"), disk, 600,
                layout.log(outdir, "load"))
    seqs, songs = [], []
    for b in range(10):
        seen = frames(lines, "BANK%d" % b)
        if not seen:
            sys.exit("bank %d was not read; see %s" % (b, layout.log(outdir, "load")))
        for s, (data, name) in enumerate(fields(seen[-1]), start=1):
            if name in ("-BLANK-", ""):
                continue
            entry = {"bank": b, "slot": s, "name": name, "data": data}
            (songs if name.startswith("$") else seqs).append(entry)
    print("%s: %d sequences (%d with data), %d songs" % (
        a.file, len(seqs), sum(x["data"] for x in seqs), len(songs)))

    # song step lists. An empty placeholder like $SONG-00 has no steps (only *SONG-END*) and
    # would play its clock forever, so songs without steps are skipped below.
    for song in songs:
        st = [f"note reading steps of {song['name']}", f"load {state}", "wait 1"]
        st += make_steps.select(song["bank"], song["slot"], status="SNGS")
        for half in ("tracks16", "tracks712"):   # the song's own 12 tracks (EDIT TRACKS=SONG)
            st += [f"press {half}", f"ifpress !TRAX | {half}", f"dump SONG{half}"]
        st += ["press seqcontrol", "seek seqcontrol 3 TEMPO=", "dump SONGCTRL",
               "press song", "ifpress EDIT SONG | sl3", "expect STEP=", "press sl1"]
        for _ in range(99):
            st += ["dump STEP", "press up"]
        sl = run(st, os.path.join(stepdir, f"{slug}-songsteps.steps"), disk, 900,
                 layout.log(outdir, "songsteps-%d%d" % (song["bank"], song["slot"])))
        ctrl = frames(sl, "SONGCTRL")
        m = re.search(r"TEMPO=([+-][\dSO]+)", " ".join(ctrl[-1]) if ctrl else "")
        trk = [f for half in ("tracks16", "tracks712") for f in fields((frames(sl, "SONG" + half) or [["", ""]])[-1])]
        song["tracks"] = [{"track": i + 1, "name": n, "data": d} for i, (d, n) in enumerate(trk)]
        used = [t["track"] for t in song["tracks"] if t["data"]]
        # channels 13-16 are free (sequence track N plays on channel N)
        song["track_channels"] = [(t, 13 + i) for i, t in enumerate(used[:4])]
        if len(used) > 4:
            print("  WARNING: song %s has %d song tracks with data; only 4 free channels" % (song["name"], len(used)))
        song["tempo_offset"] = int(m.group(1).replace("S", "5").replace("O", "0")) if m else 0
        song["steps"] = []
        for rows in frames(sl, "STEP"):
            m = re.search(r"STEP=(\S+)\s+SEQ=\s*(.*?)\s+REPS=(\S+)", rows[1])
            if not m:
                continue
            if "SONG-END" in m.group(2):
                break
            num = int(m.group(1).replace("S", "5").replace("O", "0"))
            if song["steps"] and song["steps"][-1]["step"] == num:
                continue
            reps = m.group(3).replace("S", "5").replace("O", "0")
            song["steps"].append({"step": num, "seq": m.group(2), "reps": int(reps) if reps.isdigit() else reps})
        print("  song %s: %d steps, tempo offset %+d, song tracks with data: %s" % (
            song["name"], len(song["steps"]), song["tempo_offset"], used or "none"))

    for x in seqs:
        x["out"] = "%d.%d-%s" % (x["bank"], x["slot"], clean(x["name"]))
    for x in songs:
        x["out"] = "%d.%d-%s-SONG" % (x["bank"], x["slot"], clean(x["name"]))   # songs end in -SONG.mid

    # 3. sequences, then songs (prep keeps changes, so it goes last)
    steps = [f"note loading state '{state}'", f"load {state}", "wait 1",
             "note MIDI Control: SEND-CHAN=TRACK",
             "press midicontrol", "seek midicontrol 3 SEND=", "ifpress SEND=BASE | su3 up", "expect SEND=TRACK"]
    def have(x):
        return a.skip_existing and os.path.exists(os.path.join(outdir, x["out"] + ".mid"))
    if a.only != "songs":
        for x in seqs:
            if x["data"] and not have(x):
                steps += make_steps.steps_for(outdir, x["bank"], x["slot"], x["out"])
    playable = [x for x in songs if x["steps"] and not have(x)]
    for x in songs:
        if not x["steps"]:
            print("  skipping song %s: no steps" % x["name"])
    if a.only != "sequences" and playable:
        prepped = False
        for song in playable:
            spec = "%d:%d:%s" % (song["bank"], song["slot"], song["out"])
            preps = [] if prepped else ["%d:%d:%s" % (x["bank"], x["slot"], x["out"]) for x in seqs if x["data"]]
            steps += make_steps.song_steps(outdir, spec, preps, song["track_channels"])
            prepped = True
    if len(steps) > 8:
        run(steps, os.path.join(stepdir, f"export-{slug}.steps"), disk, 20000,
            layout.log(outdir, "run-resume" if a.skip_existing else "run"), fatal=False)

    # 4. song tempo maps from the exported sequences' set tempo and length
    info = {}
    for x in seqs:
        p = layout.info(outdir, x["out"])
        if os.path.exists(p) and os.path.getsize(p):
            info[x["name"]] = json.load(open(p))
    for song in songs if a.only != "sequences" else []:
        tmap, smap, beat, ok = [], [], 0.0, True
        for st in song["steps"]:
            j = info.get(st["seq"])
            if not j or not isinstance(st["reps"], int) or not j["tempos"]:
                ok = False
                break
            bpm = j["tempos"][0][1] + song["tempo_offset"]
            sig = (j.get("timesig") or ["0:4/4"])[0].split(":")[1]   # the sequence's meter
            for _ in range(st["reps"]):
                if not tmap or tmap[-1][1] != bpm:
                    tmap.append((round(beat, 2), bpm))
                if not smap or smap[-1][1] != sig:
                    smap.append((round(beat, 2), sig))
                beat += round(j["beats"])
        cap = layout.cap(outdir, song["out"])
        if not (ok and tmap and os.path.exists(cap)):
            continue
        cmd = [sys.executable, "-I", os.path.join(HERE, "cap2mid.py"), cap, layout.mid(outdir, song["out"]),
               "--name", song["name"], "--tempo-map", ",".join("%g:%g" % t for t in tmap),
               "--timesig-map", ",".join("%g:%s" % t for t in smap)]
        out = subprocess.run(cmd, capture_output=True, text=True).stdout
        open(layout.info(outdir, song["out"]), "w").write(out)
        song["timesig_map"] = smap
        print("  %s: %s" % (song["out"], json.loads(out)["timing"]))

    manifest = {"file": a.file, "type": a.type, "disk": os.path.relpath(disk, ROOT),
                "sequences": seqs, "songs": songs}
    json.dump(manifest, open(layout.manifest(outdir), "w"), indent=1)
    done = [x for x in seqs + songs if os.path.exists(os.path.join(outdir, x["out"] + ".mid"))]
    print("%s: %d MIDI files in %s" % (a.file, len(done), os.path.relpath(outdir, ROOT)))


if __name__ == "__main__":
    main()
