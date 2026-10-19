"""One-time setup: check requirements, extract the display font, and make the Sequencer OS boot state.

  python3 -I tools/setup.py --os-disk path/to/disk-with-sequencer-os.img

You supply (none of this can be redistributed):
  - MAME (https://www.mamedev.org/; macOS: brew install mame), on PATH or in $MAME
  - the MAME ROM sets sd132.zip and esq2x40_vfx.zip, in roms/ or in $SD1_ROMPATH
  - an SD-1 disk image holding the SEQUENCER-OS file (the SD-1 loads its sequencer from disk;
    Ensoniq's sequencer OS disk, or any disk that has a SEQUENCER-OS file on it)

Setup boots the emulated SD-1 (in a MAME window), loads the sequencer OS from that disk and saves
the MAME state 'seqos' in mame/sta/. Every export starts from it.
"""
import argparse
import os
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from sd1disk import Disk, DiskError  # noqa: E402

BOOT_STEPS = """note setup: booting the SD-1
wait 20
note setup: loading the sequencer OS from disk
press storage
press sl2
wait 1
press sl2
wait 1
seek up 20 TYPE=SEQUENCER-OS
dump sequencer os file
press su3
until LOADING 20
untilnot LOADING 120
wait 2
press seqbank
wait 1
expect SEQ0
dump sequencer ready
save seqos
note setup: done
exit
"""


def fail(msg):
    sys.exit("setup: " + msg)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--os-disk", required=True, help="disk image (.img) with a SEQUENCER-OS file")
    a = ap.parse_args()

    try:
        import mido  # noqa: F401
    except ImportError:
        fail("Python package 'mido' is missing: pip install -r requirements.txt")
    mame = os.environ.get("MAME") or shutil.which("mame")
    if not mame or not os.access(mame, os.X_OK):
        fail("MAME not found: install it (macOS: brew install mame) or set MAME=/path/to/mame")
    roms = os.environ.get("SD1_ROMPATH") or os.path.join(ROOT, "roms")
    for z in ("sd132.zip", "esq2x40_vfx.zip"):
        if not os.path.exists(os.path.join(roms, z)):
            fail("%s not found in %s (put the ROM sets there or set SD1_ROMPATH)" % (z, roms))
    r = subprocess.run([mame, "-rompath", roms, "-verifyroms", "sd132"], capture_output=True, text=True)
    if r.returncode != 0:
        fail("MAME says the sd132 ROMs are incomplete or wrong:\n" + r.stdout + r.stderr)
    print("MAME: %s, ROMs verified (%s)" % (mame, roms))

    with zipfile.ZipFile(os.path.join(roms, "esq2x40_vfx.zip")) as z:
        font = z.read("esqvfd_font_vfx.bin")
    os.makedirs(os.path.join(ROOT, "mame"), exist_ok=True)
    open(os.path.join(ROOT, "mame", "esqvfd_font_vfx.bin"), "wb").write(font)

    try:
        disk = Disk(a.os_disk)
    except (OSError, DiskError) as e:
        fail(str(e))
    if not any(e.type == 0x16 for e in disk.entries()):
        fail("%s has no SEQUENCER-OS file" % a.os_disk)
    work = os.path.join(ROOT, "work")
    os.makedirs(work, exist_ok=True)
    mount = os.path.join(work, "os-disk.img")   # MAME mounts a copy, never your file
    shutil.copyfile(a.os_disk, mount)
    steps = os.path.join(work, "setup.steps")
    open(steps, "w").write(BOOT_STEPS)
    log = os.path.join(work, "setup.log")
    print("Booting the emulated SD-1 in a MAME window (about a minute)...")
    with open(log, "w") as out:
        subprocess.run([os.path.join(ROOT, "mame", "run.sh"), steps, mount], stdout=out, stderr=subprocess.STDOUT,
                       env=dict(os.environ, SD1_SECONDS="300", SD1_ROMPATH=roms), check=False)
    text = open(log).read()
    if "FAILED" in text or "LUA ERROR" in text or not os.path.exists(os.path.join(ROOT, "mame", "sta", "sd132", "seqos.sta")):
        fail("couldn't load the sequencer OS; see %s" % log)
    print("Done: saved the 'seqos' state. Next: python3 -I tools/export_disk.py your-disk.img (or .hfe)")


if __name__ == "__main__":
    main()
