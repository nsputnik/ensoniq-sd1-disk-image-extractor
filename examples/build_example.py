"""Build examples/example-disk.hfe on the emulated SD-1, the way a person would at the real keyboard.

  python3 -I examples/build_example.py            # needs tools/setup.py done first (MAME, ROMs, seqos)

1. Format: a blank SD-1-formatted disk (made by the SD-1's own FORMAT, see make_blank()) as an HFE,
   because MAME saves HFE faithfully but not the Ensoniq .img layout.
2. SysEx: SYS-EX REC from MIDI IN with examples' own dump (manufacturer 7D), saved as a SystemExclusive file.
   (Done first: SYS-EX REC clears sequencer memory.)
3. Sequences: create and name each one (keyboard naming over MIDI IN), give each track a ROM sound, record
   every part from examples/make_parts.py into MIDI IN on external MIDI clock, quantize to 1/16, keep.
4. Song: chain the sequences, rename it, save everything as a 30-SEQ/SONGS file.
5. Convert the HFE back to an image and list it.

The parts are original (examples/make_parts.py); tracks only refer to the SD-1's ROM sounds by position,
and no Ensoniq program data is saved on the disk.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import config  # noqa: E402

WORK = os.path.join(ROOT, "work", "example")
PARTS = os.path.join(WORK, "parts")
BEAT = 0.5                      # seconds per beat at the SD-1's default 120 BPM

# ROM bank 0 positions (Replace Program: Cart -> RM0, bank button, soft button)
SOUNDS = {"ROCKIN-KIT": ("b9", "sl3"), "ELEC-BASS": ("b5", "su3"), "METAL-TINES": ("b1", "sl3"),
          "FUZZ-LEAD": ("b8", "sl1")}
TRACK_BTN = ["su1", "su2", "su3", "sl1", "sl2", "sl3"]

# name, bank-page soft button, beats per bar, bars, [(part, sound)] in track order
SEQUENCES = [
    ("GROOVE-A", "su3", 4, 4, [("groove-a-drums", "ROCKIN-KIT"), ("groove-a-bass", "ELEC-BASS"),
                                ("groove-a-keys", "METAL-TINES")]),
    ("GROOVE-B", "sl1", 4, 4, [("groove-b-drums", "ROCKIN-KIT"), ("groove-b-bass", "ELEC-BASS"),
                                ("groove-b-lead", "FUZZ-LEAD")]),
    ("FILL", "sl2", 4, 1, [("fill-drums", "ROCKIN-KIT")]),
    ("ENDING", "sl3", 3, 2, [("ending-keys", "METAL-TINES"), ("ending-bass", "ELEC-BASS")]),
]
SONG = [("GROOVE-A", 2), ("GROOVE-B", 2), ("FILL", 1), ("GROOVE-A", 1), ("ENDING", 1)]


def steps_sound(name):
    bank, slot = SOUNDS[name]
    return ["press replace", "wait 1", "seek cart 4 RM0", "press " + bank, "press " + slot,
            "press replace", "wait 1", "expect " + name]


def steps_quantize():
    """Snap the take to 1/16 (every part is on 16ths): a note sent on the same tick as a clock arrives a
    moment after the clock byte and can be stamped one tick late."""
    return ["press track", "ifpress !QUANTIZE | track", "press su3", "wait 1", "seek up 8 1/16 ",
            "expect TO 1/16 ", "press su3", "wait 2", "expect KEEP NEW TRACK", "press sl3", "wait 1"]


def steps_sequence(name, slot, beats, bars, tracks):
    bar = beats * BEAT
    s = ["note example: sequence %s (%d/4, %d bars)" % (name, beats, bars),
         "press seqbank", "press b0", "press " + slot, "wait 1", "expect CREATE NEW", "press su3", "wait 1",
         "expect CREATE SEQ", "midiin %s/name-%s.mid" % (PARTS, name), "wait 8", "expect NAME=" + name,
         "press su3", "wait 1", "expect TIME SIGNATURE"]
    if beats != 4:
        s += ["seek down 4 TIME SIGNATURE  %d/4" % beats]
    s += ["press su3", "wait 1",
          # follow MIDI clock from MIDI IN (the part files bring their own timing); SYS-EX REC resets it
          "press seqcontrol", "seek seqcontrol 3 CLOCK=", "ifpress CLOCK=INT | su1 up", "expect CLOCK=MIDI"]
    for i, (part, sound) in enumerate(tracks):
        s += ["note example: %s track %d %s (%s)" % (name, i + 1, part, sound),
              "press tracks16", "ifpress !TRAX | tracks16", "press " + TRACK_BTN[i], "wait 1"]
        s += steps_sound(sound)
        # The SD-1 follows MIDI clock (CLOCK=MIDI): Record+Play arms it, and the part file brings Start,
        # clock, notes and Stop, so every take is exact to the tick. On external clock there is no count-off.
        s += ["recplay", "wait 1", "midiin %s/%s-first.mid" % (PARTS, part),
              "until KEEP %d" % int(bars * bar + bar + 15), "wait 1"]
        if i == 0:      # the first take sets the length (the file's Stop ends it on the bar line)
            s += ["expect KEEP FIRST TRACK", "expect %03d BARS" % bars, "press su3", "wait 1"]
        else:
            s += ["expect KEEP NEW TRACK", "press sl3", "wait 1"]
        s += steps_quantize()
    return s


def steps_save_seq(filename, programs=0):
    s = ["note example: save %s" % filename, "press storage", "wait 1", "press sl2", "wait 1", "press sl1", "wait 2",
         "ifpress CHANGED | sl1", "wait 2", "expect SAVE FILE", "seek down 20 TYPE=30-SEQ", "press su3", "wait 1",
         "expect PROGRAMS IN SEQ FILE"]
    s += ["press up"] * {0: 0, 30: 1, 60: 2}[programs]
    s += ["press su3", "wait 1", "expect NAME=", "midiin %s/name-%s.mid" % (PARTS, filename), "wait 8",
          "expect NAME=" + filename, "press su3", "until COMPLETED 60", "wait 1"]
    return s


def steps_song():
    """Chain the sequences on the song step editor: SEQ (lower middle) and REPS (lower right) step with Up,
    STEP (lower left) moves to the next step, which starts out as *SONG-END*."""
    s = ["note example: song", "press seqbank", "press b0", "press su1", "wait 1", "expect SNGS",
         "press song", "ifpress !EDIT STEPS | song", "press sl3", "wait 1", "expect STEP=01"]
    for k, (seq, reps) in enumerate(SONG, start=1):
        # slowly: the SD-1 is still taking in one change when a quick next press arrives, and an Up then
        # lands on the wrong field (GROOVE-A became GROOVE-B)
        s += ["note example: song step %d = %s x%d" % (k, seq, reps), "until STEP=%02d   SEQ=*SONG-END* 5" % k,
              "press sl2", "slowseek up 8 SEQ=%s " % seq]
        if reps != 1:
            s += ["press sl3", "slowseek up 9 REPS=%02d" % reps, "expect SEQ=%s " % seq]
        s += ["press sl1", "wait 1", "press up", "wait 2"]
    s += ["until STEP=%02d   SEQ=*SONG-END* 5" % (len(SONG) + 1), "dump song steps done",
          "press seqbank", "wait 1", "ifpress SAVE CHANGES | su3", "wait 1", "dump after song"]
    return s


def steps_rename_song():
    """Edit Song -> INFO -> NAME: the field is '$' plus 10 characters; *SAVE* is the lower-left button."""
    return ["note example: name the song", "press seqbank", "press b0", "press su1", "wait 2", "expect SNGS",
            "press song", "wait 2", "expect EDIT SONG", "press su3", "wait 2", "expect SONG  NAME=",
            "press su1", "wait 2", "expect RENAME SONG", "midiin %s/name-EXAMPLE-SONG.mid" % PARTS, "wait 8",
            "expect NAME=$EXAMPLE", "press sl1", "wait 2", "press seqbank", "press b0", "wait 1",
            "expect $EXAMPLE"]


def steps_internal_clock():
    """Back to the internal clock before saving, so the file plays normally on a real SD-1."""
    return ["press seqcontrol", "seek seqcontrol 3 CLOCK=", "ifpress CLOCK=MIDI | su1 down", "expect CLOCK=INT"]


def build_steps(hfe):
    s = ["note example: setup", "load seqos", "wait 1", "reinsert",
         "press master", "seek master 4 KYBD-NAMING", "press sl3", "press up", "expect KYBD-NAMING=ON",

         # SysEx first: SYS-EX REC clears the sequencer memory
         "note example: SysEx dump", "press storage", "wait 1", "press sl2", "wait 1", "press su3", "wait 2",
         "expect WILL BE ERASED", "press su3", "wait 2", "expect WAITING",
         "midiin %s/example.syx" % PARTS, "wait 3", "expect COMPLETE",
         "press sl1", "wait 2", "ifpress CHANGED | sl1", "wait 2", "expect NAME=",
         "midiin %s/name-EXAMPLE.mid" % PARTS, "wait 8", "expect NAME=EXAMPLE",
         "press su3", "until COMPLETED 30", "press sl3", "wait 1"]
    for seq in SEQUENCES:
        s += steps_sequence(*seq)
    # remove the OS's empty default sequence (it can't go while it's the only one in memory)
    s += ["note example: erase SEQUENCE-01", "press seqbank", "press b0", "press su2", "wait 1",
          "press seq", "ifpress !ERASE | seq", "press sl1", "wait 1", "expect ERASE CURRENT SEQ SEQUENCE-01",
          "press su3", "wait 2", "press seqbank", "press b0", "wait 1", "expect $SONG-00      -BLANK-"]
    s += ["press seqbank", "press b0", "wait 1", "save example-sequences"]   # checkpoint for the song steps
    s += steps_song() + steps_rename_song() + steps_internal_clock()
    s += steps_save_seq("EXAMPLE")
    return s


def song_only_steps():
    """Iterate on the song from the checkpoint (no re-recording)."""
    return (["load example-sequences", "wait 1", "reinsert"] + steps_song() + steps_rename_song() +
            steps_internal_clock() + steps_save_seq("EXAMPLE"))


def run(steps, disk, name, seconds=900):
    path = os.path.join(WORK, name + ".steps")
    with open(path, "w") as f:
        f.write("\n".join(steps + ["dump end", "exit"]) + "\n")
    log = os.path.join(WORK, name + ".log")
    with open(log, "w") as out:
        subprocess.run([os.path.join(ROOT, "mame", "run.sh"), path, disk], stdout=out, stderr=subprocess.STDOUT,
                       env=dict(config.env(), SD1_SECONDS=str(seconds)), check=False)
    with open(log) as f:
        text = f.read()
    bad = [l for l in text.splitlines() if "FAILED" in l or "LUA ERROR" in l]
    return text, bad


def main():
    if not config.status()["ready"]:
        sys.exit("Finish tools/setup.py first (python3 -I tools/config.py shows what's missing).")
    os.makedirs(WORK, exist_ok=True)
    subprocess.run([sys.executable, "-I", os.path.join(HERE, "make_parts.py"), PARTS], check=True)
    blank = os.path.join(WORK, "blank.hfe")
    if not os.path.exists(blank):
        subprocess.run([sys.executable, "-I", os.path.join(HERE, "make_blank.py"), blank], check=True)
    disk = os.path.join(WORK, "build.hfe")
    shutil.copyfile(blank, disk)
    if "--song-only" in sys.argv:
        text, bad = run(song_only_steps(), disk, "build-song", seconds=600)
    else:
        text, bad = run(build_steps(disk), disk, "build")
    if bad:
        print("\n".join(text.splitlines()[-30:]))
        sys.exit("build failed: " + bad[0])
    # MAME's HFE -> image -> HFE again with tools/img_to_hfe.py, the same layout HxC/Gotek tools write
    img = os.path.join(WORK, "example-disk.img")
    for p in (img, os.path.join(HERE, "example-disk.hfe")):
        if os.path.exists(p):
            os.remove(p)
    subprocess.run([sys.executable, "-I", os.path.join(ROOT, "tools", "hfe_to_img.py"), disk, img], check=True)
    subprocess.run([sys.executable, "-I", os.path.join(ROOT, "tools", "img_to_hfe.py"), img,
                    os.path.join(HERE, "example-disk.hfe")], check=True)
    subprocess.run([sys.executable, "-I", os.path.join(ROOT, "tools", "sd1disk.py"), img], check=True)


if __name__ == "__main__":
    main()
