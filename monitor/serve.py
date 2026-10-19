"""Local progress monitor for the MAME SD-1 MIDI export.

  python3 -I monitor/serve.py [--port 8017] [--exports out]   # then open http://127.0.0.1:8017/

Serves monitor/index.html, the live status that mame/sd1.lua writes to
mame/live/status.json, the MIDI files under the exports folder (default out/), and a
"kill MAME" endpoint. Binds to localhost only. tools/export_disk.py starts it for you.
"""
import argparse
import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATUS = os.path.join(ROOT, "mame", "live", "status.json")
EXPORTS = os.path.join(ROOT, "out")   # set by --exports
PATTERN = "mame"  # exact process name (pgrep -x): a -f pattern also matches shells whose command line mentions it


def mame_pids():
    r = subprocess.run(["pgrep", "-x", PATTERN], capture_output=True, text=True)
    return [int(p) for p in r.stdout.split()]


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


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            with open(os.path.join(ROOT, "monitor", "index.html"), "rb") as f:
                return self.send(200, f.read(), "text/html; charset=utf-8")
        if path == "/api/status":
            st = {}
            try:
                with open(STATUS) as f:
                    st = json.load(f)
                st["age"] = max(0, os.path.getmtime(STATUS))
            except (OSError, ValueError):
                pass
            st["mame_pids"] = mame_pids()
            return self.send(200, st)
        if path == "/api/exports":
            return self.send(200, exports())
        if path.startswith("/exports/"):
            p = os.path.realpath(os.path.join(EXPORTS, unquote(path[len("/exports/"):])))
            if p.startswith(os.path.realpath(EXPORTS) + os.sep) and os.path.isfile(p):
                with open(p, "rb") as f:
                    ctype = "audio/midi" if p.endswith(".mid") else "text/plain; charset=utf-8"
                    return self.send(200, f.read(), ctype)
        return self.send(404, {"error": "not found"})

    def do_POST(self):
        if urlparse(self.path).path == "/api/kill":
            pids = mame_pids()
            subprocess.run(["pkill", "-9", "-x", PATTERN])
            return self.send(200, {"killed": pids})
        return self.send(404, {"error": "not found"})


def main():
    global EXPORTS
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8017)
    ap.add_argument("--exports", default=EXPORTS, help="folder whose .mid files are listed (default out/)")
    a = ap.parse_args()
    EXPORTS = os.path.abspath(a.exports)
    os.makedirs(EXPORTS, exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    print("SD-1 monitor on http://127.0.0.1:%d/ (exports: %s)" % (a.port, EXPORTS), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
