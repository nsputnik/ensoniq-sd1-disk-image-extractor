# Example disk

`example-disk.hfe` is an SD-1 floppy image made for this project, so you can try the extractor without a disk of
your own:

```sh
python3 -I tools/export_disk.py examples/example-disk.hfe      # or drop it on the web page
```

## What's on it

| File | Type | Contents |
|---|---|---|
| `EXAMPLE` | 30-SEQ/SONGS | four sequences and a song (below) |
| `EXAMPLE` | SystemExclusive | two SysEx messages with the non-commercial manufacturer ID `7D` |

| Sequence | Meter | Bars | Tracks (ROM sound) |
|---|---|---|---|
| GROOVE-A | 4/4 | 4 | drums (ROCKIN-KIT), bass (ELEC-BASS), keys (METAL-TINES) |
| GROOVE-B | 4/4 | 4 | drums (ROCKIN-KIT), bass (ELEC-BASS), lead (FUZZ-LEAD) |
| FILL | 4/4 | 1 | drums (ROCKIN-KIT) |
| ENDING | 3/4 | 2 | keys (METAL-TINES), bass (ELEC-BASS) |

Song `$EXAMPLE`: GROOVE-A ×2, GROOVE-B ×2, FILL, GROOVE-A, ENDING (90 beats, with the 4/4 → 3/4 change at the end).

## What the extractor gives back

- `midi/EXAMPLE/`: one `.mid` per sequence plus `0.1-EXAMPLE-SONG.mid`. Every note matches the parts that were
  recorded, to the tick (`python3 -I examples/compare.py out/example-disk/midi/EXAMPLE` checks this), and the song has the
  notes and length of its five steps.
- `sysex/EXAMPLE - non-commercial.syx`: byte for byte the dump that was recorded.
- `programs/`: nothing. The sequence file was saved without programs, because the SD-1's internal programs are
  Ensoniq's factory patches. Tracks only refer to the ROM sounds by their position.

## How it was made

Entirely on the emulated SD-1, the way a person would at the keyboard, by `build_example.py`:

1. `make_blank.py`: the SD-1 formats a blank disk (Storage → Disk → Format).
2. SYS-EX REC records `example.syx` from MIDI IN and saves it to disk.
3. Each sequence is created and named. The name is typed on the keyboard over MIDI IN, with KYBD-NAMING on.
   Each track gets a ROM sound and is recorded from MIDI IN, with the sequencer on external clock
   (CLOCK=MIDI). Each part file carries MIDI Start, Clock, the notes and Stop, so the timing is the file's,
   exact to the tick. Each take is then quantized to 1/16 to remove MIDI-wire jitter.
4. The song steps are entered on the step editor, the song is renamed, the clock is set back to internal, and
   everything is saved as a 30-SEQ/SONGS file.
5. The disk image is converted to HFE with `tools/img_to_hfe.py`.

The music (`make_parts.py`) is original and written for this disk. To rebuild it (about 10 minutes, after
`tools/setup.py`):

```sh
python3 -I examples/build_example.py
```

Two things learned along the way are described in FINDINGS.md. MAME can't save the Ensoniq `.img` layout, so the
SD-1 always writes to an HFE. And the SD-1 sends no MIDI clock while recording, so external clock is the only way to
time a take exactly.
