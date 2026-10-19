"""Generate a mame/sd1.lua step list that exports SD-1 sequences to MIDI.

For each sequence: select it, set all 12 tracks' MIDI status to BOTH (internal
voices + MIDI OUT), turn LOOP off so playback ends on its own, capture MIDI OUT
while it plays once, and convert the capture to .mid (done by sd1.lua).

usage: python3 -I tools/make_steps.py OUTDIR STATE BANK:SLOT:NAME [...] > steps
       python3 -I tools/make_steps.py --song OUTDIR STATE BANK:SLOT:SONGNAME BANK:SLOT:SEQ [...] > steps
  BANK 0-9, SLOT 1-6 (upper row L/M/R = 1-3, lower row = 4-6)

--song: prepare every listed sequence (the ones the song uses) the same way but answer
YES to SAVE CHANGES so the song plays them with MIDI on, then capture the song once.
Saving only changes the emulated SD-1's memory, never the disk image.
"""
import sys

SLOT = {1: "su1", 2: "su2", 3: "su3", 4: "sl1", 5: "sl2", 6: "sl3"}


def select(bank, slot, save=False, status="STOP"):
    # leaving an edited sequence asks SAVE CHANGES TO ...? -- YES upper right, NO lower right
    ans = "su3" if save else "sl3"
    return ["press seqbank", f"press b{bank}", f"press {SLOT[slot]}",
            f"ifpress SAVE CHANGES | {ans}", f"ifpress SAVE CHANGES | {ans}",
            f"status {status} 10"]


def setup_tracks(name):
    s = [f"note {name}: tracks 1-12 -> MIDI status BOTH, track N on channel N"]
    # Factory sequences often put every track on channel 1, which would merge them.
    for half, first in (("tracks16", 1), ("tracks712", 7)):
        # Tracks buttons toggle between the track-names page and the last parameter page
        s += [f"press {half}", f"ifpress CHANNEL | {half}", f"ifpress STATUS | {half}",
              "expect TRAX", f"dump {half}", f"grabtracks {first}",
              "seek midi 4 STATUS"]
        # MIDI-only tracks (e.g. driving an external module) exist too, so don't assume LOCAL
        for b in ("su1", "su2", "su3", "sl1", "sl2", "sl3"):
            s += [f"setword {b} BOTH"]
        s += [f"dump {half} status", "seek midi 4 CHANNEL"]
        for i, b in enumerate(("su1", "su2", "su3", "sl1", "sl2", "sl3")):
            s += [f"setnum {b} {first + i}"]
        s += [f"dump {half} channels"]
    return s


def meter_steps(name):
    """Time signature from the Locate page, bar count from Edit Seq > INFO (both read-only)."""
    return [f"note {name}: time signature + bars",
            "press locate", "expect LOCATE", f"dump LOCATE {name}", "grabinfo",
            "press seq", "ifpress !INFO | seq", "press su3", "expect BARS=", f"dump INFO {name}", "grabinfo"]


def steps_for(outdir, bank, slot, name):
    s = [f"item {name}", f"note {name}: select bank {bank} slot {slot}"]
    s += select(bank, slot)
    s += setup_tracks(name)
    s += meter_steps(name)
    # LOOP on + stop by clock count: with LOOP=OFF the SD-1 can stop early (it ended a
    # 16-bar factory sequence after 4 bars); the converter trims the loop restart.
    s += [f"note {name}: LOOP on",
          "press seqcontrol", "seek seqcontrol 3 LOOP=", "press sl3", "press up", "expect LOOP=ON",
          f"note {name}: playing + capturing MIDI OUT",
          f"capture {outdir}/cap/{name}.cap",
          "press play", "playlength 1800", "status STOP 30", "wait 1",
          "endcapture", "done"]
    return s


def song_track_steps(songtracks):
    """MIDI status BOTH + a channel for the song's own tracks that hold data: [(track, channel)]."""
    s = []
    for half, first in (("tracks16", 1), ("tracks712", 7)):
        mine = [(t, ch) for t, ch in songtracks if first <= t < first + 6]
        if not mine:
            continue
        btns = ("su1", "su2", "su3", "sl1", "sl2", "sl3")
        s += [f"press {half}", f"ifpress !TRAX | {half}", "expect TRAX", "seek midi 4 STATUS"]
        for t, _ in mine:
            s += [f"setword {btns[t - first]} BOTH"]
        s += ["seek midi 4 CHANNEL"]
        for t, ch in mine:
            s += [f"setnum {btns[t - first]} {ch}"]
        s += [f"dump song tracks {half}"]
    return s


def song_steps(outdir, songspec, seqspecs, songtracks=()):
    s = []
    for spec in seqspecs:
        bank, slot, name = spec.split(":", 2)
        s += [f"item prep {name}", f"note prepare {name} for the song (changes kept)"]
        s += select(int(bank), int(slot), save=True)
        s += setup_tracks(name) + ["done"]
    bank, slot, name = songspec.split(":", 2)
    s += [f"item {name}", f"note {name}: select song"]
    s += select(int(bank), int(slot), save=True, status="SNGS")
    if songtracks:
        s += [f"note {name}: song tracks {[t for t, _ in songtracks]} -> BOTH, channels {[c for _, c in songtracks]}"]
        s += song_track_steps(songtracks)
    s += [f"note {name}: LOOP off",
          "press seqcontrol", "seek seqcontrol 3 LOOP=", "press sl3", "press down", "expect LOOP=OFF",
          f"note {name}: playing song + capturing MIDI OUT",
          f"capture {outdir}/cap/{name}.cap",
          "press play", "midistop 3600",
          # a song can send MIDI Stop while its display stays on SNGP; stop it by hand
          "wait 2", "ifpress SNGP | stop", "status SNGS 30", "wait 1",
          "endcapture", "done"]
    return s


def main():
    if sys.argv[1] == "--song":
        outdir, state, songspec, seqs = sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5:]
        out = [f"note loading state '{state}'", f"load {state}", "wait 1"]
        out += song_steps(outdir, songspec, seqs)
        print("\n".join(out + ["note all done", "exit"]))
        return
    outdir, state, specs = sys.argv[1], sys.argv[2], sys.argv[3:]
    out = [f"note loading state '{state}'", f"load {state}", "wait 1",
           # SEND-CHAN=BASE (default) sends every track on the base channel; TRACK keeps
           # each track on its own channel. Global setting, MIDI Control page upper right.
           "note MIDI Control: SEND-CHAN=TRACK",
           "press midicontrol", "seek midicontrol 3 SEND=", "dump midi control",
           "ifpress SEND=BASE | su3 up", "expect SEND=TRACK"]
    for spec in specs:
        bank, slot, name = spec.split(":", 2)
        out += steps_for(outdir, int(bank), int(slot), name)
    out += ["note all done", "exit"]
    print("\n".join(out))


if __name__ == "__main__":
    main()
