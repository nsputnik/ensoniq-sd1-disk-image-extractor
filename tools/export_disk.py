"""Extract everything from one SD-1 / VFX-SD disk image: sequences and songs as MIDI files, programs and
presets as SD-1 SysEx, and any SysEx dumps saved on the disk.

  python3 -I tools/export_disk.py my-disk.img            # or my-disk.hfe straight from HxC
  python3 -I tools/export_disk.py my-disk.img --out out/my-disk --skip-existing

Output (default out/<disk name>/):
  midi/<FILE>/*.mid     one per sequence (<bank>.<slot>-<NAME>.mid) and per song (...-SONG.mid);
                        cap/ json/ logs/ beside them hold the raw capture, summaries and MAME logs
  programs/             program and preset dumps, including the programs saved inside sequence files;
                        index.txt lists every program by bank.slot
  sysex/                SystemExclusive files the SD-1 recorded from other gear, as plain .syx
  summary.txt           what was found and whether every export passed its checks

The live progress page (monitor/serve.py) is started if it isn't running: http://127.0.0.1:8017/ (--port)
MAME runs in a window; stop it any time with the page's Kill MAME button or: pkill -9 -x mame
Run tools/setup.py once first.
"""
import argparse
import os
import shutil
import socket
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from sd1disk import Disk, DiskError  # noqa: E402
from export_file import clean  # noqa: E402

PY = [sys.executable, "-I"]
PORT = 8017


def monitor_running(port):
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def start_monitor(exports_root, port):
    if monitor_running(port):
        print("Something is already serving port %d; if it's the monitor: http://127.0.0.1:%d/" % (port, port))
        return
    log = open(os.path.join(ROOT, "work", "monitor.log"), "w")
    subprocess.Popen(PY + [os.path.join(ROOT, "monitor", "serve.py"), "--port", str(port), "--exports", exports_root],
                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    print("Progress page: http://127.0.0.1:%d/" % port)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("disk", help=".img (819,200 bytes) or .hfe")
    ap.add_argument("--out", help="output folder (default out/<disk name>)")
    ap.add_argument("--skip-existing", action="store_true", help="keep MIDI files already exported")
    ap.add_argument("--no-midi", action="store_true", help="only extract programs and SysEx (no MAME)")
    ap.add_argument("--no-monitor", action="store_true", help="don't start the progress page")
    ap.add_argument("--port", type=int, default=PORT, help="progress page port (default %d)" % PORT)
    a = ap.parse_args()

    base = os.path.splitext(os.path.basename(a.disk))[0]
    out = os.path.abspath(a.out or os.path.join(ROOT, "out", base))
    work = os.path.join(ROOT, "work")
    os.makedirs(work, exist_ok=True)
    os.makedirs(out, exist_ok=True)

    img = a.disk
    if a.disk.lower().endswith(".hfe"):
        img = os.path.join(out, base + ".img")
        if not os.path.exists(img):
            print("Converting HFE to a disk image:")
            r = subprocess.run(PY + [os.path.join(HERE, "hfe_to_img.py"), a.disk, img])
            if r.returncode not in (0, 1):
                sys.exit("HFE conversion failed")
            if r.returncode == 1:
                print("WARNING: some blocks were lost; files that use them may be damaged.")
    try:
        disk = Disk(img)
        files = list(disk.entries())
    except (OSError, DiskError) as e:
        sys.exit(str(e))

    summary = ["Disk: %s" % a.disk, ""]
    seqs = [e for e in files if e.type in (0x12, 0x13)]
    print("%d files on the disk, %d sequence files" % (len(files), len(seqs)))

    # programs, presets and SysEx dumps: no emulation needed
    r = subprocess.run(PY + [os.path.join(HERE, "extract_programs.py"), img, os.path.join(out, "programs")],
                       capture_output=True, text=True)
    summary += ["Programs and presets (programs/):"] + ["  " + l for l in r.stdout.splitlines()] + [""]
    if any(e.type == 0x14 for e in files):
        r = subprocess.run(PY + [os.path.join(HERE, "extract_sysex.py"), img, os.path.join(out, "sysex")],
                           capture_output=True, text=True)
        summary += ["SysEx dumps (sysex/):"] + ["  " + l for l in r.stdout.splitlines()] + [""]

    if seqs and not a.no_midi:
        if not os.path.exists(os.path.join(ROOT, "mame", "sta", "sd132", "seqos.sta")):
            sys.exit("No 'seqos' state: run tools/setup.py --os-disk <disk with SEQUENCER-OS> first")
        if subprocess.run(["pgrep", "-x", "mame"], capture_output=True).returncode == 0:
            sys.exit("MAME is already running; only one export can run at a time")
        mount = os.path.join(work, "mount.img")   # MAME mounts a copy, never your file
        shutil.copyfile(img, mount)
        midi = os.path.join(out, "midi")
        os.makedirs(midi, exist_ok=True)
        if not a.no_monitor:
            start_monitor(os.path.join(ROOT, "out") if out.startswith(os.path.join(ROOT, "out")) else out, a.port)
        summary.append("MIDI (midi/):")
        for e in seqs:
            kind = "30" if e.type == 0x12 else "60"
            print("\n=== %s (%s sequences)" % (e.name, kind))
            cmd = PY + [os.path.join(HERE, "export_file.py"), e.name, kind, "--disk", mount, "--exports", midi]
            if a.skip_existing:
                cmd.append("--skip-existing")
            ok = subprocess.run(cmd).returncode == 0
            d = os.path.join(midi, clean(e.name))
            v = subprocess.run(PY + [os.path.join(HERE, "verify_export.py"), d], capture_output=True, text=True)
            print(v.stdout, end="")
            n = len([f for f in os.listdir(d) if f.endswith(".mid")]) if os.path.isdir(d) else 0
            state = "all checks pass" if ok and v.returncode == 0 else "CHECK FAILED (see %s)" % os.path.relpath(d, out)
            summary.append("  %-12s %3d MIDI files, %s" % (e.name, n, state))
        summary.append("")
    open(os.path.join(out, "summary.txt"), "w").write("\n".join(summary) + "\n")
    print("\n" + "\n".join(summary))
    print("Output: %s" % out)


if __name__ == "__main__":
    main()
