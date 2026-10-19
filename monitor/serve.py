"""The extractor's web page: setup checks, choose a disk, run the export, watch it live, download results.

  python3 -I monitor/serve.py [--port 8017] [--exports out] [--open]   # then open http://127.0.0.1:8017/

Serves monitor/index.html and a small JSON API:
  GET  /api/setup            MAME, ROM (per file), Python and Sequencer OS checks (tools/config.py)
  POST /api/settings         {"mame": path, "rompath": path}: save to settings.json, re-check
  POST /api/upload?name=X    raw .img/.hfe bytes -> work/uploads/, returns the disk's file list
  GET  /api/disks            uploaded disks and their contents
  POST /api/run-setup        {"disk": name}: tools/setup.py with that disk as the Sequencer OS disk
  POST /api/export           {"disk": name, "skip_existing": bool, "no_midi": bool}: tools/export_disk.py
  GET  /api/job              the running/last job and the tail of its log
  GET  /api/status           live emulator status written by mame/sd1.lua
  GET  /api/exports, /api/results, /exports/<path>   finished files under the exports folder (default out/)
  POST /api/kill             force-quit MAME

Binds to 127.0.0.1 only. Requests must name this host (stops DNS rebinding), and every POST needs the
header X-SD1: 1, which a page on another site can't send without permission this server never grants.
tools/export_disk.py also starts this server for command-line runs.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import config  # noqa: E402
from sd1disk import Disk, DiskError  # noqa: E402

STATUS = os.path.join(ROOT, "mame", "live", "status.json")
UPLOADS = os.path.join(ROOT, "work", "uploads")
EXPORTS = os.path.join(ROOT, "out")   # set by --exports
PATTERN = "mame"  # exact process name (pgrep -x): a -f pattern also matches shells whose command line mentions it
PY = [sys.executable, "-I"]
MAX_UPLOAD = 4 * 1024 * 1024
DOWNLOADABLE = (".mid", ".syx", ".txt", ".json", ".img")
PORT = 8017


def mame_pids():
    r = subprocess.run(["pgrep", "-x", PATTERN], capture_output=True, text=True)
    return [int(p) for p in r.stdout.split()]


# --- jobs: one setup or export at a time ---------------------------------------------------------

class Job:
    lock = threading.Lock()
    current = None   # dict

    @classmethod
    def start(cls, kind, label, cmd, out_dir=None):
        with cls.lock:
            if cls.current and cls.current["proc"].poll() is None:
                return None, "A %s is already running." % cls.current["kind"]
            if mame_pids():
                return None, "MAME is already running (another export?). Stop it first."
            os.makedirs(os.path.join(ROOT, "work"), exist_ok=True)
            log = os.path.join(ROOT, "work", "job.log")
            fh = open(log, "w")
            proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, cwd=ROOT, env=config.env())
            cls.current = {"kind": kind, "label": label, "proc": proc, "log": log, "started": time.time(),
                           "out": out_dir}
            return cls.current, None

    @classmethod
    def info(cls):
        j = cls.current
        if not j:
            return {"kind": None}
        rc = j["proc"].poll()
        try:
            with open(j["log"], errors="replace") as f:
                tail = f.read().splitlines()[-80:]
        except OSError:
            tail = []
        return {"kind": j["kind"], "label": j["label"], "running": rc is None, "exit": rc,
                "elapsed": round(time.time() - j["started"]), "log": tail,
                "out": os.path.relpath(j["out"], EXPORTS) if j["out"] and j["out"].startswith(EXPORTS) else None}


# --- disks ---------------------------------------------------------------------------------------

def safe_name(name):
    base = os.path.basename(name or "")
    stem, ext = os.path.splitext(base)
    stem = re.sub(r"[^A-Za-z0-9 ._+()-]+", "_", stem).strip(" .") or "disk"
    return stem + ext.lower()


def disk_image(name):
    """Path of a readable .img for an uploaded disk (an .hfe is converted once, beside it)."""
    path = os.path.join(UPLOADS, name)
    if name.endswith(".img"):
        return path, ""
    img = os.path.join(UPLOADS, os.path.splitext(name)[0] + " (from hfe).img")
    report = ""
    if not os.path.exists(img):
        r = subprocess.run(PY + [os.path.join(ROOT, "tools", "hfe_to_img.py"), path, img],
                           capture_output=True, text=True)
        report = "\n".join(l for l in (r.stdout + r.stderr).strip().splitlines() if not l.startswith("wrote "))
        if r.returncode not in (0, 1):
            raise DiskError(report or "HFE conversion failed")
        with open(img + ".report.txt", "w") as f:
            f.write(report)
    else:
        try:
            with open(img + ".report.txt") as f:
                report = f.read()
        except OSError:
            pass
    return img, report


def describe(name):
    out = {"name": name, "ok": False, "files": [], "report": "", "error": ""}
    try:
        img, report = disk_image(name)
        out["report"] = report.strip()
        d = Disk(img)
        for e in d.entries():
            out["files"].append({"name": e.name, "type": e.type_name, "bytes": e.size,
                                 "programs": e.has_programs, "sequences": e.type in (0x12, 0x13)})
        out["sequencer_os"] = any(f["type"] == "SequencerOs" for f in out["files"])
        out["sequence_files"] = sum(f["sequences"] for f in out["files"])
        out["ok"] = True
    except (OSError, DiskError) as e:
        out["error"] = str(e).replace(os.path.join(UPLOADS, ""), "")   # no server paths in messages
    return out


def disks():
    if not os.path.isdir(UPLOADS):
        return []
    names = sorted(f for f in os.listdir(UPLOADS) if f.endswith((".img", ".hfe")) and "(from hfe)" not in f)
    names.sort(key=lambda f: -os.path.getmtime(os.path.join(UPLOADS, f)))
    return [describe(n) for n in names]


# --- results -------------------------------------------------------------------------------------

def exports():
    out = []
    for dirpath, _, files in os.walk(EXPORTS):
        for fn in files:
            if not fn.endswith(".mid"):
                continue
            p = os.path.join(dirpath, fn)
            info = {}
            side = os.path.join(dirpath, "json", fn[:-4] + ".json")   # tools/layout.py
            if os.path.exists(side):
                try:
                    with open(side) as f:
                        info = json.load(f)
                except ValueError:
                    pass
            out.append({"path": os.path.relpath(p, EXPORTS), "bytes": os.path.getsize(p),
                        "mtime": os.path.getmtime(p), "info": info})
    out.sort(key=lambda e: e["mtime"])
    return out


def results():
    out = []
    if not os.path.isdir(EXPORTS):
        return out
    for d in sorted(os.listdir(EXPORTS)):
        base = os.path.join(EXPORTS, d)
        if not os.path.isfile(os.path.join(base, "summary.txt")):
            continue
        with open(os.path.join(base, "summary.txt"), errors="replace") as f:
            summary = f.read()
        midi = []
        mdir = os.path.join(base, "midi")
        if os.path.isdir(mdir):
            for fd in sorted(os.listdir(mdir)):
                p = os.path.join(mdir, fd)
                if os.path.isdir(p):
                    midi.append({"file": fd, "mids": sorted("%s/midi/%s/%s" % (d, fd, m) for m in os.listdir(p)
                                                            if m.endswith(".mid"))})
        listing = lambda sub: sorted("%s/%s/%s" % (d, sub, f) for f in os.listdir(os.path.join(base, sub))
                                     if f.endswith((".syx", ".txt"))) if os.path.isdir(os.path.join(base, sub)) else []
        thirty = []
        pdir = os.path.join(base, "programs")
        if os.path.isdir(pdir):
            for fd in sorted(os.listdir(pdir)):
                if os.path.isdir(os.path.join(pdir, fd)):
                    thirty += sorted("%s/programs/%s/%s" % (d, fd, f) for f in os.listdir(os.path.join(pdir, fd)))
        out.append({"disk": d, "summary": summary, "midi": midi, "programs": listing("programs") + thirty,
                    "sysex": listing("sysex"), "mtime": os.path.getmtime(os.path.join(base, "summary.txt"))})
    out.sort(key=lambda r: -r["mtime"])
    return out


# --- HTTP ----------------------------------------------------------------------------------------

class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json", download=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if download:
            self.send_header("Content-Disposition", 'attachment; filename="%s"' % download.replace('"', ""))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def host_ok(self):
        host = (self.headers.get("Host") or "").lower()
        return host in ("127.0.0.1:%d" % PORT, "localhost:%d" % PORT)

    def body_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 65536:
            return None
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return None

    def do_GET(self):
        if not self.host_ok():
            return self.send(403, {"error": "bad host"})
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            with open(os.path.join(ROOT, "monitor", "index.html"), "rb") as f:
                return self.send(200, f.read(), "text/html; charset=utf-8")
        if path == "/api/status":
            st = {}
            try:
                with open(STATUS) as f:
                    st = json.load(f)
            except (OSError, ValueError):
                pass
            st["mame_pids"] = mame_pids()
            return self.send(200, st)
        if path == "/api/setup":
            st = config.status()
            st["settings"] = config.load()
            st["defaults"] = {"rompath": os.path.join(ROOT, "roms")}
            return self.send(200, st)
        if path == "/api/disks":
            return self.send(200, disks())
        if path == "/api/job":
            return self.send(200, Job.info())
        if path == "/api/exports":
            return self.send(200, exports())
        if path == "/api/results":
            return self.send(200, results())
        if path.startswith("/exports/"):
            p = os.path.realpath(os.path.join(EXPORTS, unquote(path[len("/exports/"):])))
            if p.startswith(os.path.realpath(EXPORTS) + os.sep) and os.path.isfile(p) and p.endswith(DOWNLOADABLE):
                with open(p, "rb") as f:
                    data = f.read()
                if p.endswith(".txt") or p.endswith(".json"):
                    return self.send(200, data, "text/plain; charset=utf-8")
                return self.send(200, data, "audio/midi" if p.endswith(".mid") else "application/octet-stream",
                                 download=os.path.basename(p))
        return self.send(404, {"error": "not found"})

    def do_POST(self):
        if not self.host_ok() or self.headers.get("X-SD1") != "1":
            return self.send(403, {"error": "forbidden"})
        url = urlparse(self.path)
        if url.path == "/api/kill":
            pids = mame_pids()
            subprocess.run(["pkill", "-9", "-x", PATTERN])
            return self.send(200, {"killed": pids})
        if url.path == "/api/settings":
            b = self.body_json()
            if b is None:
                return self.send(400, {"error": "bad request"})
            config.save(mame=b.get("mame"), rompath=b.get("rompath"))
            st = config.status()
            st["settings"] = config.load()
            return self.send(200, st)
        if url.path == "/api/upload":
            name = safe_name(parse_qs(url.query).get("name", [""])[0])
            n = int(self.headers.get("Content-Length") or 0)
            if not name.endswith((".img", ".hfe")):
                return self.send(400, {"error": "Choose a .img or .hfe disk image."})
            if not 0 < n <= MAX_UPLOAD:
                return self.send(400, {"error": "File is empty or too big for a floppy image."})
            data = self.rfile.read(n)
            os.makedirs(UPLOADS, exist_ok=True)
            path = os.path.join(UPLOADS, name)
            for stale in (path, os.path.join(UPLOADS, os.path.splitext(name)[0] + " (from hfe).img")):
                for p in (stale, stale + ".report.txt"):
                    if os.path.exists(p):
                        os.remove(p)
            with open(path, "wb") as f:
                f.write(data)
            d = describe(name)
            if not d["ok"]:
                os.remove(path)
                return self.send(400, {"error": d["error"]})
            return self.send(200, d)
        if url.path in ("/api/run-setup", "/api/export"):
            b = self.body_json() or {}
            name = safe_name(b.get("disk", ""))
            if not os.path.isfile(os.path.join(UPLOADS, name)):
                return self.send(400, {"error": "Upload the disk image first."})
            img, _ = disk_image(name)
            if url.path == "/api/run-setup":
                job, err = Job.start("setup", name, PY + [os.path.join(ROOT, "tools", "setup.py"), "--os-disk", img])
            else:
                if not config.status()["ready"] and not b.get("no_midi"):
                    return self.send(400, {"error": "Finish setup first (see the Setup panel)."})
                out = os.path.join(EXPORTS, os.path.splitext(name)[0])
                cmd = PY + [os.path.join(ROOT, "tools", "export_disk.py"), os.path.join(UPLOADS, name),
                            "--out", out, "--no-monitor"]
                if b.get("skip_existing"):
                    cmd.append("--skip-existing")
                if b.get("no_midi"):
                    cmd.append("--no-midi")
                job, err = Job.start("export", name, cmd, out)
            if err:
                return self.send(409, {"error": err})
            return self.send(200, Job.info())
        return self.send(404, {"error": "not found"})


def main():
    global EXPORTS, PORT
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--exports", default=EXPORTS, help="folder for results (default out/)")
    ap.add_argument("--open", action="store_true", help="open the page in your browser")
    a = ap.parse_args()
    EXPORTS, PORT = os.path.abspath(a.exports), a.port
    os.makedirs(EXPORTS, exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    url = "http://127.0.0.1:%d/" % a.port
    print("SD-1 disk image extractor: %s (results in %s)" % (url, EXPORTS), flush=True)
    if a.open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    srv.serve_forever()


if __name__ == "__main__":
    main()
