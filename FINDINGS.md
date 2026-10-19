# Findings: Ensoniq SD-1 disks, data formats, firmware behaviour and the MAME harness

What this project learned about SD-1 / VFX-SD floppies, their file formats, the SD-1's sequencer and MIDI behaviour,
and driving MAME's `sd132` emulation, organised by topic. [README.md](README.md) explains how to use the tools. Byte
offsets are 0-based. "Verified" means checked against real disks (Ensoniq factory disks and a set of user floppies),
not just read from a document.

Much of the format detail in sections 1–3 was first worked out by Joe McMahon's
[sd1diskutil](https://github.com/joemcmahon/sd1diskutil); references to its source are given where they apply. This
project adds the program offset in 30-sequence files, the ThirtyPrograms layout, the HxC IMG-export problem, the SD-1's
MIDI and sequencer behaviour, and the MAME notes.

---

## 1. The floppy disk

### Geometry
- 3.5" DD, **80 tracks × 2 sides × 10 sectors × 512 bytes** = 819,200 bytes (1,600 blocks). Sectors are numbered **0–9**
  (a PC uses 1–9/1–18). Data fills side 0 then side 1 of a track before moving on, so **block = track×20 + side×10 + sector**.
- Blocks 0–22 are reserved (sd1cli: "23 reserved, 1577 usable").

### Reserved blocks (verified on factory and user disks)
| Block | Contents |
|---|---|
| 0 | Unused. Holds format filler: `6D B6` repeated. Losing it costs nothing |
| 1 | Device ID block: geometry words, `ID` signature at 0x26 |
| 2 | OS block: **free-block count** (big-endian u32 at offset 0), `OS` at 0x1C. The rest is leftover format junk (identical on every disk) |
| 3–4 | Root directory: four entries `sub direct 1…4` pointing to the sub-directories; ends with `DR` |
| 5–14 | FAT: 170 entries × 3 bytes per block, big-endian. Entry *n* is for block *n* (block 5 entry 0 = disk block 0). **0 = free**, 1 = end of file, **2 = bad block**, otherwise the next block (sd1diskutil `fat.rs`) |
| 15–22 | Four sub-directories, 2 blocks each, **39 entries × 26 bytes** |

- The free count in block 2 equals the number of zero FAT entries (verified on a full and a blank disk). So a lost
  block 2 can be rebuilt (`tools/hfe_to_img.py` does this).
- `sd1cli inspect` "Free blocks" prints the block-2 counter; the "FAT:" line is the real count.

### Directory entry (26 bytes)
| Offset | Field |
|---|---|
| 0 | `type_info`: 0x20 = sequence file **saved with programs**; 0x2F/0x0F appear on factory disks; 0x00 after an sd1cli rebuild |
| 1 | File type (table below) |
| 2–12 | Name, 11 bytes, space-padded. **Leading spaces and symbols are part of the name** (`" COUNTRY-*"`, `" BRASS-STAB"`) |
| 13 | 0 |
| 14–15 | Size in blocks |
| 16–17 | Contiguous blocks |
| 18–21 | First block |
| 22 | File number (bank position on the SD-1's file list) |
| 23–25 | Size in bytes (24-bit) |

### File types (directory byte 1)
| Code | Type | Code | Type |
|---|---|---|---|
| 0x0A | OneProgram | 0x11 | OneSequence |
| 0x0B | SixPrograms | 0x12 | ThirtySequences (30-SEQ/SONGS) |
| 0x0C | ThirtyPrograms | 0x13 | SixtySequences (60-SEQ/SONGS) |
| 0x0D | SixtyPrograms | 0x14 | SystemExclusive |
| 0x0E | OnePreset | 0x15 | SystemSetup |
| 0x0F | TenPresets | 0x16 | SequencerOs |
| 0x10 | TwentyPresets | | |

To read a file, start at its first block and follow the FAT until it reaches end of file (1). Then cut the data to the
byte size in the directory.

---

## 2. What is inside each file type

### Programs (patches)
- One program = **530 bytes**. Its name is 11 bytes at **offset 498**. Names can start with a symbol (`*KICK+SNARE`,
  `/SWELL-SAW`, `/BRASS-STAB`).
- **OneProgram**: the 530 bytes.
- **SixtyPrograms** (31,800 bytes): two streams interleaved byte by byte. **Even bytes are programs 0–29, odd bytes are
  programs 30–59** (sd1diskutil `interleave_sixty_programs`). Verified: de-interleaving gives SysEx identical to `sd1cli extract`.
- **ThirtyPrograms** (15,900 bytes): 30 programs **one after another, not interleaved** (the names read directly at 498 + k×530).
  sd1cli can't handle this type. On the SD-1 it loads into one half of internal memory.
- Internal program *i* is bank `i // 6`, slot `i % 6 + 1` (10 banks × 6).
- The SD-1 also has 120 **ROM** programs (names in sd1diskutil's `ROM_ALL_PROGRAMS`) and **cartridge** programs, which the
  display shows as `CART-SND-n` when no cartridge is inserted.

### Presets
- **TwentyPresets** (960 bytes) = 20 × 48-byte presets, stored as-is (no interleave). Verified identical to `sd1cli extract`.

### Sequence files (30-SEQ/SONGS and 60-SEQ/SONGS)
- Layout (sd1diskutil `disk_to_allsequences` / `disk_to_thirty_sequences`): N × 188-byte sequence headers (bytes 183–185 = event
  data size), a 21-byte global section, zero padding, then the event data, each sequence padded to a whole block.
  Event data starts at byte **6144** (30-SEQ) or **11776** (60-SEQ) when the file has no programs.
- **Programs saved inside sequence files.** When saving, the SD-1 asks `SAVE PROGRAMS IN SEQ FILE`: NO, 30 (30-SEQ only:
  the bank half that matches the sequences) or 60 (manual §11). On the load page such a file shows a flashing **P** after
  its name (e.g. `LOAD FILE=MY SONG    P`). Loading it replaces the internal programs. The directory `type_info` is 0x20.
- **Files saved with 60 programs** hold them interleaved exactly like a SixtyPrograms file, at byte **6144** in a 30-SEQ
  file and **11776** in a 60-SEQ file (sd1diskutil knows only the 60-SEQ offset). Verified two ways on 17 user files: the 60-SEQ
  names match `sd1cli dump-programs`, and for every 30-SEQ file each program the exported tracks use (read off the emulated
  SD-1 after loading the file) is in that file's 60, is a ROM program, or is a cartridge program; nothing is unexplained.
- Not yet seen: a sequence file saved with **30** programs. Its layout is unknown; expect 15,900 bytes at 6144.
- `sd1cli` doesn't decode the events inside sequences, so it can't make MIDI. That's why this project plays them in MAME instead.

### SystemExclusive files (SysEx the SD-1 recorded from other gear)
- An **8-byte header** (e.g. `00 01 8E 7E 00 01 09 00`), then the raw `F0 … F7` messages exactly as received.
- Any device's SysEx can be stored this way (on the disks examined: a sound module's preset banks, its program map and its
  master settings, each saved under the name of the song it went with). `tools/extract_sysex.py` strips the header and names
  the sender from the manufacturer ID.

---

## 3. SD-1 SysEx messages (for sending patches to a real SD-1)

- `F0 0F 05 00 <channel> <type> <payload> F7`. 0x0F = Ensoniq, 0x05 = VFX family. The payload is sent as **nybbles, high
  then low** (each byte becomes two bytes 0–15).
- Types (sd1diskutil `sysex.rs`): 00 Command, 01 Error, **02 OneProgram** (1,067 bytes), **03 AllPrograms** (63,607 bytes,
  60 programs **in order**, not interleaved), 04 OnePreset, **05 AllPresets** (1,927 bytes), 09 SingleSequence, 0A AllSequences,
  0B TrackParameters.
- **There is no 30-program dump.** A ThirtyPrograms file becomes 30 single-program dumps. A single-program dump goes to the
  edit buffer, to be written to a slot by hand. An AllPrograms dump **replaces all 60 internal programs**.
- `sd1cli extract` on a sequence file writes sd1diskutil's *library* format. **Don't send it to a real SD-1.**
- `tools/extract_programs.py` builds 02/03/05 dumps from any program or preset file and from the programs inside sequence files.
  Checked on the sample disk: all 21 program files and 4 preset files are byte-identical to `sd1cli extract`.

---

## 4. Imaging floppies

- **HxC software: 80 tracks, double-sided, save as HFE.** HFE keeps the raw track data and is what `sd1cli hfe-to-img` and
  the recovery tools read.
- **Don't use HxC's IMG export.** It doesn't know the Ensoniq format (sectors 0–9). With an unreadable sector it **drops the
  sector without leaving a gap** (one bad sector gave 818,688 bytes = 1,599 blocks), so every later block shifts by one and the image is useless.
- `sd1cli hfe-to-img` stops at the first missing sector (`HFE missing sector at track 0 side 0 sector 2`).
- `tools/hfe_to_img.py` decodes the MFM stream itself, checks every sector's CRC, puts each one at its block number, and reports
  what's missing. It rebuilds block 0 and block 2, which hold no file data. Any other missing block is a real
  loss, so re-read that track while the disk is in the drive.
- HxC reported "first sector bad" on one disk; the unreadable sector was actually **sector 2** (the OS block). Read the HFE
  rather than trusting the summary.
- For badly damaged disks, read flux (`.scp`, 3 revolutions) and use sd1diskutil's `scp_to_img.py` / `merge_scp_hfe.py` /
  `triage_sequences.py` / `extract_intact_sequences.py`.
- `img → HFE → img` through sd1cli is byte-identical. Sojus VST3 ≥ 0.9.8 reads `.img`; older versions need HFE.

---

## 5. SD-1 sequencer and firmware behaviour

### Track MIDI settings
- Each track has a **MIDI STATUS**: LOCAL (internal sound only), MIDI (MIDI OUT only), BOTH, \*EXT\*. It's on the Performance MIDI
  page (press MIDI until `STATUS`). **Down steps MIDI → LOCAL → BOTH** and stops at BOTH. Status, channel, LOOP and tempo are
  stored **per sequence**.
- Factory sequences put every track on channel 1 with status LOCAL. Playing them sends only Start/clock/Stop.
- **MIDI-only tracks exist in real data.** Users drove external modules from tracks set to MIDI (the SD-1 names such a
  track `MIDI-CH-n`; `**MIDI-CH-9` on the track page). An exporter that assumes LOCAL (one Down press) turns them into LOCAL and loses them.
  Press until the field reads BOTH (`setword`).
- `SEND=TRACK` on the MIDI Control page sends each track on its own channel. BASE sends everything on the base channel.

### Clock, timing and transmission
- With `CLOCK=INT`, Play sends Start (`FA`), **24 clocks per beat** (`F8`) and Stop (`FC`). The sequencer's resolution is
  **96 PPQ**, so one clock = 4 ticks.
- At a clock tick the clock byte goes out **first**, then that tick's notes.
- **Everything due on one tick goes out as one back-to-back burst**, paced by the serial line: about **0.96 ms per
  3-byte message**. In a big chord or drum hit the last messages arrive more than half a tick late, so rounding each
  message's time separately puts them on the next tick. Grouping bursts (a message within 1.3 ms of the previous one and less than
  one tick after the burst's first) moved 9,042 of 43,454 sample-disk notes back by exactly one tick. The share on a 16th grid rose
  from 42.5% to 58.8%. Without the one-tick limit, dense passages chain into the next tick (shifts up to −7).
  **A burst never spans a MIDI clock:** a clock always starts a new tick. Without that rule, notes sent just before the
  loop-restart clock pulled the restart's first note back into the sequence (seen once in 179,000 events).
- **The last clock of a sequence is at tick length − 4.** Notes in the final 3 ticks come after it. Stopping on that clock cuts
  them. Wait for the loop-restart clock (tick = length), then trim everything at or after the length.
- **LOOP=OFF isn't a reliable end.** It stopped the 16-bar `SWNG4/4-16B` after 4 bars. Capture with LOOP on and stop after
  bars × meter clocks.
- After Stop the SD-1 sends a reset: program changes, volume CCs and note-offs.

### Songs
- A song (`$` name) is a list of steps (sequence × reps, per-step mutes/transposes), 12 song tracks of its own, and a tempo
  offset (`TEMPO=+03`). Song tracks default to LOCAL.
- **A song step shows only the sequence's name, not its number.** Banks can hold several sequences with the same name
  (seen: two VERSEs; two "CHORUS 1"s of different length and tempo), and one song
  can use **both** same-named sequences at different steps. Work out which one each step used from its length and notes
  (`verify_export.py` tries every combination per step).
- **Songs played MIDI-status tracks even when the sequences' own status had been changed to LOCAL** (seen once; the
  exporter now sets BOTH everywhere, so it doesn't matter).
- Songs end with their own MIDI Stop. **Empty songs** (step 1 = `*SONG-END*`, e.g. `$SONG-00` placeholders) never stop. Skip them.
- After its Stop, a song's display can **stay on SNGP**. Press Stop instead of waiting for SNGS.
- At song-step changes the firmware sends track setup controllers, and **CC 72 goes out with a value byte ≥ 0x80**. Any receiver
  would read the stray bytes as a note-on (`B9 47 00 48 9D 07 7F`). Drop it.
- Notes recorded right at the end of a sequence play at the downbeat of the next song step.
- Leaving an edited sequence asks **SAVE CHANGES TO …?**. YES keeps the edit in RAM only; the disk is never written unless you save.

### Meters
- The Locate page shows the meter (`LOCATE SEQ=… TRACK=01 6/4`). Edit Seq → INFO shows `BARS=`, `TIME=`, `SIZE=`.
- Meters seen: 4/4, 2/4, 3/4, 5/4, 6/4, 7/4, 12/8 and **1/4** (Ensoniq's fills and odd lengths).

---

## 6. Front panel and display

- 2 × 40 VFD, read from MAME outputs `vfd0..79` and decoded with the font ROM. **5/S and 0/O share a glyph**, so every number
  field maps S→5 and O→0 (`TEMPO=11S`, `STEP=0S`). `-` and `/` can also be confused: the ROM program INDO-AFRO reads as `INDO/AFRO`.
- The sequencer status is the first 4 characters of row 2: `STOP`, `PLAY`, `SNGS` (song selected), `SNGP` (song playing).
- Soft buttons: upper row L/M/R and lower row L/M/R. On track pages they're tracks 1–3 / 4–6. The Tracks 1-6 / 7-12 buttons toggle
  between names and the last parameter page.
- On track-name pages `*` marks a track with data (`**` when the program name also starts with `*`).
- Storage → Disk → Load: choose the type, then the file list. The list **starts at the first file, and Up steps forward**. A 30-SEQ file asks
  for banks 0–4 or 5–9.
- Button numbers are in `docs/mame-esqpanel-vfx-FrontPanel.js`, mirrored in `BTN` in `mame/sd1.lua`.

---

## 7. MAME (`sd132`) harness

- **ROMs:** MAME's `sd132` set (SD-1/32, OS 4.10) plus `esq2x40_vfx.zip`, the display font.
- **Booting:** a fresh `sd132` boots to the INT0 program page in about 20 emulated seconds, with no sequencer. The SD-1 loads
  its sequencer from disk: Storage → Disk → Load, step the TYPE with **Up** to `SEQUENCER-OS` (file `VERSION-410`, which the VFD
  shows as `VERSION-)10`), answer YES; `LOADING …` then `DISK COMMAND COMPLETED` follow, and the Seq bank page appears.
  `tools/setup.py` does this once and saves the state every export starts from.
- **Safety:** always `-window -nomaximize` with `-seconds_to_run`. A `-video none` MAME became the frontmost app with no window,
  hung, and forced a power-off. SIGTERM is ignored: use `pkill -9 -x mame`. Never use `pgrep -f`/`pkill -f` with "mame" in the
  pattern, because it matches the shell loop running it.
- `emu.register_start` in an autoboot script may already have fired. Run at top level with coroutines + `emu.wait`. The
  driver has no screen, so frame callbacks come about once per emulated second.
- MIDI OUT = 68681 DUART channel A transmit, a write tap at `0x280007`. Timestamps are **emulated** seconds.
- The emulated clock runs about **0.3% slow** with ±1 ms jitter, so place events by MIDI clock, not seconds. Emulation is
  deterministic: the same button path from the same saved state gives the same capture. A different boot
  state shifts about 1% of notes by ±1 tick.
- **A saved state remembers the directory of the disk it was saved with.** After loading the state with a different
  floppy mounted, the SD-1 still lists the old disk's files. Unload and reload the floppy image (`reinsert`) so the OS sees a disk change.
- Runs about 17× real time. Most of an export goes on button presses. A 30-SEQ file takes about 5–10 minutes.

---

## 8. sd1cli (sd1diskutil v1.18) limits

- It can't extract ThirtyPrograms, SixPrograms or SequencerOs files, or the programs inside sequence files
  (`dump-programs` only lists them, and only for 60-SEQ).
- `extract` picks a file **by name**, so when two files share a name (e.g. a program bank and a presets file with the same name) you can't choose.
  Names are case-sensitive (despite its README) and leading spaces count.
- Rebuilding a sequence file from SysEx drops its programs and turns 30-SEQ into 60-SEQ. Copy disks as `.img`/HFE.
- `hfe-to-img` gives up on the first missing sector (use `tools/hfe_to_img.py`).

---

## 9. How exports are checked

- **Bar check:** the sequencer sent bars × meter clocks.
- **Song = sum of steps:** a song's notes on channels 1–12 and its length equal the sum of its steps' sequences × reps.
  This caught the malformed CC, the silent MIDI tracks, the cut last tick and the burst rounding.
- **Grid share:** the fraction of notes on a 16th position. Quantized music should go up when timing gets more accurate.
- **Programs:** every track's program is found in the file's saved programs, in ROM, or on a cartridge.
- **SysEx:** compared byte for byte with `sd1cli` wherever it supports the type, and every message checked to be a complete `F0…F7`.

---

## 10. Writing to disks on the emulated SD-1 (how the example disk was made)

- **MAME can read but not write the Ensoniq `.img` layout.** Saving an `.img` renumbers each track's sectors from 1,
  so every track shifts by one sector and sector 0 is lost; the SD-1 then reports `DISK ERROR - BAD DIRECTORY`.
  **Mount an HFE** for anything the SD-1 writes: MAME saves HFE faithfully. `tools/img_to_hfe.py` makes one.
- A freshly formatted disk (verified against the SD-1's own FORMAT): blocks 0 and 23+ are `6D B6` filler; block 1 repeats a
  40-byte device-ID record ending in `ID`; block 2 repeats a 30-byte OS record (free count, `00 01`, `OS`); block 3 holds
  the four `sub direct 1..4` entries; **every directory's last block ends in `DR`** (blocks 4, 16, 18, 20, 22) and
  **every FAT block ends in `FB`** (blocks 5–14). The SD-1 checks these markers.
- **MIDI IN from a file:** MAME's `sd132` takes a `.mid` or `.syx` as its MIDI IN, played from the moment it's mounted.
  SMF escape events (`F7 01 FA`, `F7 01 F8`, `F7 01 FC`) arrive as raw MIDI Start, Clock and Stop.
- **Recording:** Hold Record and press Play. The first take sets the sequence length from where Stop lands, and its
  bar 1 is the click's bar in which the first note falls. The click grid doesn't start at a fixed time after
  Play, and the SD-1 sends **no MIDI clock while recording**, so a take can't be timed from outside. Instead set
  **Seq Control CLOCK=MIDI** and let the recorded file bring Start, Clock and Stop: every take is then exact. On
  external clock there is no count-off, and Stop ends a first take exactly on the bar line. A note sent on the same
  tick as a clock can be stamped one tick late, so quantize to the grid afterwards (Edit Track → QUANTIZE).
- **Keyboard naming over MIDI** (Master page 3, KYBD-NAMING=ON): white keys from C2 type 0–9 then A–Z; black keys are
  cursor left, cursor right, space, dash, plus. The cursor doesn't advance by itself, so follow every character
  with cursor-right. Sequence names are 11 characters. Song names are `$` plus 10.
- **SYS-EX REC** (Storage → Disk) clears the sequencer memory first ("SEQUENCER DATA WILL BE ERASED"), and with it
  the CLOCK setting. Record SysEx before making sequences.
- **The last sequence in memory can't be erased.** The OS keeps its default SEQUENCE-01 until another sequence exists.
- **Song step editor:** SEQ (lower middle) and REPS (lower right) step with Up; STEP (lower left) + Up moves to the
  next step, which starts as `*SONG-END*`. **Press slowly:** a quick press can be taken twice on the SEQ field.
- **The display updates about once per emulated second**, so after a press wait until the text changes before reading it.
- **Saving a state while a file is mounted on MIDI IN** and loading it in a later session crashes MAME (0.283). So does
  any MAME API call from a script coroutine resumed after the machine has stopped. `-seconds_to_run` is absolute
  emulated time, so loading a state saved later than that limit stops MAME at once.

---

## 11. Open items

- A song's expected tempo map is built from step *names*. With same-named sequences of different tempo it's rejected
  and the file uses the clock-measured tempo, about 0.3% low. Build it from the steps `verify_export.py` picks.
- A sequence file saved with 30 programs hasn't been seen yet, and `extract_programs.py` would skip it. SixPrograms and TenPresets
  files aren't handled.
- Reading sequencer RAM directly (OS memory layout undocumented) would replace most button presses.
