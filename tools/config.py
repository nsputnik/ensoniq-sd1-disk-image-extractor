"""Where MAME and the ROMs are, and whether everything needed is in place.

Settings live in settings.json at the project root (written by the web page or by hand):
  {"mame": "/path/to/mame", "rompath": "/path/to/roms"}
Environment variables MAME and SD1_ROMPATH override them. Defaults: `mame` on PATH, and roms/.

  python3 -I tools/config.py        # print the checks
"""
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SETTINGS = os.path.join(ROOT, "settings.json")
SEQOS = os.path.join(ROOT, "mame", "sta", "sd132", "seqos.sta")
FONT = os.path.join(ROOT, "mame", "esqvfd_font_vfx.bin")
DRIVER = "sd132"


def load():
    try:
        with open(SETTINGS) as f:
            s = json.load(f)
        return s if isinstance(s, dict) else {}
    except (OSError, ValueError):
        return {}


def save(**kw):
    s = load()
    for k, v in kw.items():
        if v is None:
            continue
        if v == "":
            s.pop(k, None)
        else:
            s[k] = os.path.abspath(os.path.expanduser(v))
    with open(SETTINGS, "w") as f:
        json.dump(s, f, indent=2)
    return s


def mame_path():
    p = os.environ.get("MAME") or load().get("mame")
    if p:
        return os.path.expanduser(p)
    return shutil.which("mame") or ""


def rom_path():
    return os.path.expanduser(os.environ.get("SD1_ROMPATH") or load().get("rompath") or os.path.join(ROOT, "roms"))


def env():
    """Environment for mame/run.sh and the tools: MAME and SD1_ROMPATH filled in from the settings."""
    e = dict(os.environ)
    if mame_path():
        e["MAME"] = mame_path()
    e["SD1_ROMPATH"] = rom_path()
    return e


def _run(args, timeout=60):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout + r.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return -1, str(e)


def check_mame(path=None):
    path = path if path is not None else mame_path()
    out = {"path": path, "ok": False, "version": "", "message": ""}
    if not path:
        out["message"] = "MAME not found on PATH. Install it (macOS: brew install mame; Windows/Linux: mamedev.org) or enter its path."
        return out
    if not (os.path.isfile(path) and os.access(path, os.X_OK)):
        out["message"] = "No program at %s." % path
        return out
    rc, txt = _run([path, "-version"], 30)
    if rc != 0:
        out["message"] = "%s didn't run as MAME: %s" % (path, txt.strip()[:200])
        return out
    out["version"] = txt.strip().split()[0] if txt.strip() else "?"
    rc, txt = _run([path, "-listfull", DRIVER], 30)
    if DRIVER not in txt:
        out["message"] = "This MAME build has no %s (Ensoniq SD-1) driver." % DRIVER
        return out
    out["ok"] = True
    out["message"] = "MAME %s with the %s driver" % (out["version"], DRIVER)
    return out


def check_roms(mame=None, rompath=None):
    """Per-file ROM check using MAME's own lists: -listroms for what's expected, -verifyroms for problems."""
    mame = mame if mame is not None else mame_path()
    rompath = rompath if rompath is not None else rom_path()
    out = {"path": rompath, "ok": False, "files": [], "message": ""}
    if not os.path.isdir(rompath):
        out["message"] = "Folder %s doesn't exist." % rompath
        return out
    zips = [z for z in ("sd132.zip", "esq2x40_vfx.zip") if not os.path.exists(os.path.join(rompath, z))]
    if not check_mame(mame)["ok"]:
        out["message"] = "Needs a working MAME to check the ROMs."
        out["missing_zips"] = zips
        return out
    rc, listing = _run([mame, "-rompath", rompath, "-listroms", DRIVER], 60)
    files = []
    for line in listing.splitlines():
        m = re.match(r"^(\S+\.bin)\s+(\d+)\s+CRC", line)
        if m:
            files.append({"name": m.group(1), "bytes": int(m.group(2)), "status": "ok"})
    rc, verify = _run([mame, "-rompath", rompath, "-verifyroms", DRIVER], 120)
    problems = {}
    for line in verify.splitlines():
        m = re.match(r"^\S+\s*:\s*(\S+)\s+\(\d+ bytes\)\s+-\s+(.*)$", line)
        if m:
            problems[m.group(1)] = m.group(2).strip()
    whole_missing = "not found" in verify.lower() and not problems
    for f in files:
        if whole_missing:
            f["status"] = "NOT FOUND"
        elif f["name"] in problems and "NO GOOD DUMP KNOWN" not in problems[f["name"]]:
            f["status"] = problems[f["name"]]
    out["files"] = files
    good = re.search(r"romset %s is (good|best available)" % DRIVER, verify) is not None
    out["ok"] = good
    bad = [f["name"] for f in files if f["status"] != "ok"]
    if good:
        out["message"] = "All %d ROM files verified by MAME." % len(files)
    elif whole_missing:
        out["message"] = "No %s ROM set in %s (expects sd132.zip and esq2x40_vfx.zip)." % (DRIVER, rompath)
    else:
        out["message"] = "%d of %d ROM files missing or wrong: %s" % (len(bad), len(files), ", ".join(bad))
    out["missing_zips"] = zips
    return out


def check_python():
    try:
        import mido  # noqa: F401
        return {"ok": True, "message": "Python %s with mido" % sys.version.split()[0]}
    except ImportError:
        return {"ok": False, "message": "Python package 'mido' is missing: pip install -r requirements.txt"}


def status():
    mame = check_mame()
    roms = check_roms() if mame["ok"] else {"path": rom_path(), "ok": False, "files": [],
                                              "message": "Waiting for MAME."}
    seq = {"ok": os.path.exists(SEQOS) and os.path.exists(FONT),
           "message": "Sequencer OS state saved." if os.path.exists(SEQOS) and os.path.exists(FONT)
           else "Not done yet: needs a disk image with a SEQUENCER-OS file."}
    py = check_python()
    return {"python": py, "mame": mame, "roms": roms, "seqos": seq,
            "ready": py["ok"] and mame["ok"] and roms["ok"] and seq["ok"]}


if __name__ == "__main__":
    s = status()
    for k in ("python", "mame", "roms", "seqos"):
        print("%-7s %-4s %s" % (k, "OK" if s[k]["ok"] else "--", s[k]["message"]))
    for f in s["roms"].get("files", []):
        if f["status"] != "ok":
            print("        %s: %s" % (f["name"], f["status"]))
    sys.exit(0 if s["ready"] else 1)
