# ensoniq-sd1-disk-image-extractor

Get everything off Ensoniq **SD-1 / VFX-SD** floppy disks:

- **Sequences and songs → Standard MIDI Files.** Each sequence is played on an emulated SD-1 (MAME's `sd132` driver)
  and its MIDI OUT is recorded, timed by the synth's own MIDI clock. Multitrack, 96 PPQ, with tempo, time signatures
  and song tempo maps.
- **Programs and presets → SD-1 SysEx** that a real SD-1 accepts, including the 60 programs that can be saved
  *inside* a sequence file (the exact sounds the sequences were made with).
- **SysEx dumps saved on the disk → `.syx`.** The SD-1 can record any device's SysEx to floppy; this gets it back out.
- **HxC `.hfe` → disk image**, sector by sector with CRC checks, recovering what a bad sector would otherwise break.

Everything runs from a local web page: it checks your setup (MAME, ROMs file by file), takes a disk image by
drag and drop, runs the export while you watch the emulated SD-1 play, and hands you the files. Command-line
tools do the same for scripting.

## What you need

| | |
|---|---|
| **MAME** | [mamedev.org](https://www.mamedev.org/). macOS: `brew install mame`. Found on `PATH`, or set its location on the page |
| **ROM sets** | `sd132.zip` and `esq2x40_vfx.zip` (MAME's names) in `roms/`, or point the page at any folder that has them (an existing MAME ROM folder works). Not included: they're Ensoniq's |
| **Sequencer OS disk** | Any SD-1 disk image with a `SEQUENCER-OS` file. The SD-1 loads its sequencer from disk |
| **Python 3.9+** | `pip install -r requirements.txt` (just [mido](https://mido.readthedocs.io/)) |

Tested on macOS with MAME 0.283. The disk tools (`hfe_to_img.py`, `extract_programs.py`, `extract_sysex.py`,
`sd1disk.py`) need only Python.

## Quick start (web page)

```sh
pip install -r requirements.txt
python3 -I monitor/serve.py --open          # http://127.0.0.1:8017/
```

1. **Setup** shows a ✓ or ✗ for Python, MAME and the ROMs. MAME's own checksums verify every ROM file, so a missing or
   bad file is named. Enter a MAME path or ROM folder if they aren't found; it's remembered in `settings.json`.
2. **Disk images:** drop an `.hfe` or `.img` on the page. It lists the files on the disk and reports any unreadable sectors.
   The first time, drop a disk that has the `SEQUENCER-OS` file and press **Use for setup** (the SD-1 loads its
   sequencer from disk; this takes about a minute and is done once).
3. Press **Export everything**. A MAME window opens on the emulated front panel, and the page shows its display, live MIDI,
   a piano roll and the log. A 30-sequence file takes about 5–10 minutes. **Programs & SysEx only** needs no MAME.
4. **Results** has every file to download, per disk.

The page only listens on your own machine (127.0.0.1) and refuses requests from other web sites.

## Quick start (command line)

```sh
python3 -I tools/setup.py --os-disk sequencer-os.img      # once
python3 -I tools/export_disk.py my-disk.hfe                # or my-disk.img; also starts the progress page
python3 -I tools/config.py                                 # what's set up, and what isn't
```

`MAME=/path/to/mame` and `SD1_ROMPATH=/path/to/roms` override `settings.json`.

## Output

```
out/my-disk/
  my-disk.img            (when you started from .hfe)
  midi/<FILE>/           0.2-VERSE.mid, 1.4-CHORUS_2.mid ... one per sequence; 0.1-MYSONG-SONG.mid per song
             cap/ json/ logs/   raw MIDI capture, per-file summary + manifest, MAME logs
  programs/              <FILE> - programs from sequence file.syx, <NAME> - 60 programs.syx, <NAME>.syx,
                         <NAME> - 30 programs/NN <PROGRAM>.syx, <NAME> - 20 presets.syx, index.txt (every program by bank.slot)
  sysex/                 <NAME> - <maker>.syx
  summary.txt            what was found, and whether every export passed its checks
```

`python3 -I tools/sd1disk.py my-disk.img` lists a disk.

## Imaging floppies

With HxC software: **80 tracks, double-sided, save as HFE.** Don't use HxC's IMG export: on a disk with an unreadable
sector it drops the sector without leaving a gap, so every later block is off by one. `tools/hfe_to_img.py` (run for
you by `export_disk.py`) reports every unreadable sector. Blocks 0 and 2 hold no file data and are rebuilt; any
other loss is listed, so re-read that track while the disk is in the drive.

## How it works

1. **Drive the panel.** `mame/sd1.lua` presses front-panel buttons through MAME's input ports, reads the 2×40 display as
   text through the font ROM, and runs plain-text step lists that `tools/make_steps.py` generates.
2. **Per file:** load it from the floppy, read the ten sequencer banks, and walk each song's steps.
3. **Per sequence:** set all 12 tracks to MIDI status **BOTH** with track N on channel N, read the time signature
   (Locate page) and bar count (INFO page), play with LOOP on, and press Stop once the SD-1 has sent bars × meter MIDI clocks.
4. **Per song:** prepare every sequence the same way (emulator RAM only; your disk is never written), then play the song.
5. **Capture:** a write tap on the 68681 DUART's MIDI transmit register logs every byte with its emulated timestamp.
   `tools/cap2mid.py` turns the capture into a type-1 SMF.

## Accuracy and checks

- **Timing comes from the SD-1's own MIDI clock** (24 per beat), not from seconds: the emulated clock runs about 0.3%
  slow, which would drift 10 ticks per 8 bars. The file's tempo is the sequence's set tempo.
- **Bursts:** the SD-1 sends everything due on one tick back to back at wire speed (about 1 ms per message), so the end
  of a big chord arrives up to a tick late. The converter puts each burst back on its tick.
- **Bar check:** the sequencer really ran for bars × meter (LOOP=OFF is unreliable: it once stopped a 16-bar sequence
  after 4 bars).
- **Songs:** a song's notes and length must equal the sum of its steps, which catches dropped or phantom notes.
  This found a real firmware quirk: at song-step changes the SD-1 sends CC 72 with an invalid value byte that any
  receiver would read as a note. The converter drops it.
- Emulation is deterministic: the same disk and the same setup give byte-identical MIDI. A different boot state (a new
  `setup.py` run) puts about 1% of notes one tick earlier or later (the same ±1 ms jitter real MIDI hardware shows);
  every note is still there.

[FINDINGS.md](FINDINGS.md) has everything learned along the way: the disk layout, every file format, the SysEx
messages, the sequencer's MIDI behaviour, display quirks and MAME gotchas.

## Tools

| Script | Does |
|---|---|
| `monitor/serve.py [--open]` | The web page (setup, disks, export, live view, results). `--port`, `--exports` |
| `tools/setup.py --os-disk X.img` | One-time setup: requirements, display font, Sequencer OS boot state |
| `tools/config.py` | Prints the setup checks; holds the MAME / ROM settings the other tools use |
| `tools/export_disk.py DISK` | Everything from one disk (`.img` or `.hfe`), with the progress page |
| `tools/export_file.py FILE 30\|60 --disk X.img` | MIDI for one sequence file |
| `tools/verify_export.py out/.../midi/FILE` | Bar checks; song notes and length vs. the sum of steps |
| `tools/refresh.py DIR...` | Rebuild `.mid` from captures with the current converter (no emulation) |
| `tools/hfe_to_img.py IN.hfe OUT.img` | HFE → disk image with CRC checks |
| `tools/extract_programs.py IMG DIR` | Programs/presets → SD-1 SysEx + `index.txt` |
| `tools/extract_sysex.py IMG DIR` | Saved SysEx dumps → `.syx` |
| `tools/sd1disk.py IMG` | List a disk (also the disk-reading module the others use) |
| `tools/cap2mid.py CAP OUT.mid` | Capture → `.mid` |
| `mame/run.sh STEPS [disk.img]` | Windowed MAME + `sd1.lua`. Env: `MAME`, `SD1_ROMPATH`, `SD1_SECONDS`, `SD1_MIDIOUT` |

Run the tests (no MAME or ROMs needed): `python3 -m unittest discover -s tests`

## Safety: MAME runs in a window

`run.sh` always runs MAME windowed with a time limit. A windowless MAME (`-video none`) once became the frontmost app on
macOS, hung, and held the keyboard until the machine was powered off. MAME ignores a plain `kill`: use the Kill MAME
button or `pkill -9 -x mame`. Only one export runs at a time.

## Sending patches to a real SD-1

- `… - 60 programs.syx` and `… - programs from sequence file.syx` are all-programs dumps: they **replace all 60
  internal programs**.
- A single-program dump lands in the edit buffer; write it to a slot on the SD-1.
- SysEx has no 30-program dump, so a 30-program file becomes 30 single-program dumps. (The SD-1 itself can load the
  original file into one half of memory.)
- Tracks that used ROM programs need no dump. Programs shown as `CART-SND-n` came from a sound cartridge, which isn't on
  the disk.

## Credits

- **[sd1diskutil](https://github.com/joemcmahon/sd1diskutil)** by Joe McMahon. Much of the disk and file-format detail
  this project relies on was first worked out there: the program and preset layouts, the 60-program interleave, the
  sequence-file structure, the file-type codes and the SysEx message format. Its `sd1cli` tool is what the program and
  preset dumps here were checked against (byte for byte), and its sample disk was the test disk this project was
  developed on. Use `sd1cli` for jobs this project doesn't do, such as writing files back to disk images or creating new ones.
- **[MAME](https://www.mamedev.org/)** and its `sd132` driver (GPL-2.0+; used unmodified as a separate program, not included).
- Gary Giebler's *Ensoniq Floppy Diskette Formats* article, and the SD-1 Musician's Manual
  ([polynominal.com](https://www.polynominal.com/ensoniq-sd1/)).

## License

[MIT No Attribution (MIT-0)](LICENSE): use, change and share it for anything, no credit required. Ensoniq ROMs, disks and
manuals are not part of this project.
