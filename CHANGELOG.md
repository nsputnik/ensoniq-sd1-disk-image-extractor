# Changelog

## 0.1.0 (2026-10-18)

First public release.

- Sequences and songs → Standard MIDI Files by playing them on an emulated SD-1 (MAME `sd132`) and recording
  MIDI OUT, timed by the SD-1's own MIDI clock (96 PPQ), with time signatures, tempo maps and checks
  (bar count; song = sum of its steps).
- Programs and presets → SD-1 SysEx, including the 60 programs saved inside sequence files.
- SysEx dumps the SD-1 recorded from other gear → plain `.syx`.
- HxC `.hfe` → disk image with per-sector CRC checks; rebuilds the two blocks that hold no file data.
- `tools/export_disk.py`: everything from one disk in one command, with a live progress page.
- `tools/setup.py`: one-time setup (requirements, font, Sequencer OS boot state).
- Web page (`monitor/serve.py`): setup checks with a per-file ROM report, MAME/ROM locations saved in `settings.json`,
  drag-and-drop disk images, export jobs, live emulator view and downloadable results.
- License: MIT No Attribution (MIT-0).
- `examples/example-disk.hfe`: an original example disk built on the emulated SD-1 (`examples/build_example.py`),
  with a note-for-note check (`examples/compare.py`).
- `tools/img_to_hfe.py`; `mame/sd1.lua`: MIDI IN commands (`midiin`, `recplay`, `at`, `clocks`, `slowseek`),
  display-change waits, 5/S and 0/O folded in text matching, clean stop (no crash when MAME stops), time limit
  counted from the last state load.
