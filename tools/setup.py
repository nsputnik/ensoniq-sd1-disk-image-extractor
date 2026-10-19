"""One-time setup: check requirements, extract the display font, and make the Sequencer OS boot state.

  python3 -I tools/setup.py --os-disk path/to/disk-with-sequencer-os.img

You supply (none of this can be redistributed):
  - MAME (https://www.mamedev.org/; macOS: brew install mame): on PATH, or set in settings.json / $MAME
  - the MAME ROM sets sd132.zip and esq2x40_vfx.zip: in roms/, or a folder set in settings.json / $SD1_ROMPATH
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
import config  # noqa: E402
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
wait 1
ifpress WILL BE ERASED | su3
until COMPLETED 120
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

    st = config.status()
    for k in ("python", "mame", "roms"):
        if not st[k]["ok"]:
            bad = [f["name"] + ": " + f["status"] for f in st[k].get("files", []) if f["status"] != "ok"]
            fail(st[k]["message"] + ("\n  " + "\n  ".join(bad) if bad else ""))
    mame, roms = config.mame_path(), config.rom_path()
    print("%s; %s (%s)" % (st["mame"]["message"], st["roms"]["message"], roms))

    zpath, loose = os.path.join(roms, "esq2x40_vfx.zip"), os.path.join(roms, "esq2x40_vfx", "esqvfd_font_vfx.bin")
    if os.path.exists(zpath):
        with zipfile.ZipFile(zpath) as z:
            font = z.read("esqvfd_font_vfx.bin")
    elif os.path.exists(loose):   # MAME also accepts unzipped ROM folders
        with open(loose, "rb") as f:
            font = f.read()
    else:
        fail("can't read the display font from %s (esq2x40_vfx.zip)" % roms)
    os.makedirs(os.path.join(ROOT, "mame"), exist_ok=True)
    with open(config.FONT, "wb") as f:
        f.write(font)

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
    with open(steps, "w") as f:
        f.write(BOOT_STEPS)
    log = os.path.join(work, "setup.log")
    if os.path.exists(config.SEQOS):
        os.remove(config.SEQOS)   # so a failed run can't look like success
    print("Booting the emulated SD-1 in a MAME window (about a minute)...")
    with open(log, "w") as out:
        subprocess.run([os.path.join(ROOT, "mame", "run.sh"), steps, mount], stdout=out, stderr=subprocess.STDOUT,
                       env=dict(config.env(), SD1_SECONDS="300"), check=False)
    with open(log) as f:
        text = f.read()
    if "FAILED" in text or "LUA ERROR" in text or not os.path.exists(config.SEQOS):
        fail("couldn't load the sequencer OS; see %s" % log)
    print("Done: saved the 'seqos' state. Next: python3 -I tools/export_disk.py your-disk.img (or .hfe)")


if __name__ == "__main__":
    main()
