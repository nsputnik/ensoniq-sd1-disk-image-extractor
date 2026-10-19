#!/usr/bin/env bash
# run.sh <steps-file> [disk.img] [extra mame args...]  — sd132 with the Lua step driver.
# Always windowed: a -video none run still made MAME the frontmost app with no window,
# and when it hung it held the keyboard until a forced power-off (seen on macOS).
# If a run hangs, stop it with: pkill -9 -x mame  (plain SIGTERM is ignored),
# or the Kill MAME button on the monitor page (python3 -I monitor/serve.py).
# Env: MAME        path to the mame binary (default: mame on PATH)
#      SD1_ROMPATH folder holding sd132.zip (default: roms/)
#      SD1_SECONDS  emulated-seconds limit (default 900; ~17x faster than real time unthrottled)
#      SD1_MIDIOUT  also send MIDI OUT to a host port live, e.g. "IAC Driver Bus 1" (implies
#                   real-time speed so a DAW can follow the SD-1's MIDI clock)
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STEPS="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"; shift
FLOP=(); if [ -n "${1:-}" ] && [ "${1#-}" = "$1" ]; then FLOP=(-flop "$1"); shift; fi
SPEED=(-nothrottle); MOUT=()
if [ -n "${SD1_MIDIOUT:-}" ]; then SPEED=(); MOUT=(-midiout "$SD1_MIDIOUT"); fi
MAME="${MAME:-$(command -v mame || true)}"
[ -x "$MAME" ] || { echo "MAME not found: install it (e.g. brew install mame) or set MAME=/path/to/mame" >&2; exit 1; }
mkdir -p "$ROOT/mame/cfg" "$ROOT/mame/nvram" "$ROOT/mame/sta" "$ROOT/mame/live"
SD1_ROOT="$ROOT" SD1_STEPS="$STEPS" "$MAME" sd132 -rompath "${SD1_ROMPATH:-$ROOT/roms}" \
  -cfg_directory "$ROOT/mame/cfg" -nvram_directory "$ROOT/mame/nvram" -state_directory "$ROOT/mame/sta" \
  -window -nomaximize -sound none "${SPEED[@]}" -skip_gameinfo -seconds_to_run "${SD1_SECONDS:-900}" \
  "${FLOP[@]}" "${MOUT[@]}" -autoboot_script "$ROOT/mame/sd1.lua" -autoboot_delay 0 "$@" 2>&1 | grep -v "^Average speed"
