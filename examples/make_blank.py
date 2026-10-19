"""Make a blank SD-1 floppy, formatted by the emulated SD-1 itself.

  python3 -I examples/make_blank.py [out.hfe]        # default work/example/blank.hfe

An all-zero 800 KB image is converted to HFE (tools/img_to_hfe.py: valid sector framing, zero data),
mounted in MAME, and formatted with Storage -> Disk -> Format. It has to be an HFE: MAME can read the
Ensoniq .img layout but not write it, and saving an .img renumbers each track's sectors from 1, which
shifts every track by one sector.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import config  # noqa: E402
from img_to_hfe import to_hfe  # noqa: E402
from hfe_to_img import read_hfe, decode_track  # noqa: E402

STEPS = """note example: format a blank disk
load seqos
wait 1
reinsert
press storage
wait 1
press sl2
wait 1
press su1
wait 1
expect FORMAT DISK
press su3
wait 2
until COMPLETED 400
wait 2
exit
"""


def check(hfe):
    """The structure a freshly formatted SD-1 disk has (see FINDINGS.md section 1)."""
    sides = read_hfe(hfe)
    img = bytearray(1600 * 512)
    for t in range(80):
        for s in range(2):
            for n, data in decode_track(sides[(t, s)], t, s).items():
                b = t * 20 + s * 10 + n
                img[b * 512:(b + 1) * 512] = data
    blk = lambda b: img[b * 512:(b + 1) * 512]
    problems = []
    if blk(1)[0x26:0x28] != b"ID":
        problems.append("no ID in block 1")
    if blk(2)[0x1C:0x1E] != b"OS" or int.from_bytes(blk(2)[0:4], "big") != 1577:
        problems.append("OS block")
    if [b for b in range(23) if blk(b)[510:] == b"DR"] != [4, 16, 18, 20, 22]:
        problems.append("directory markers")
    if any(blk(b)[510:] != b"FB" for b in range(5, 15)):
        problems.append("FAT markers")
    return problems


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "work", "example", "blank.hfe")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if not config.status()["ready"]:
        sys.exit("Finish tools/setup.py first.")
    with open(out, "wb") as f:
        f.write(to_hfe(bytes(1600 * 512)))
    steps = out + ".steps"
    with open(steps, "w") as f:
        f.write(STEPS)
    log = out + ".log"
    with open(log, "w") as fh:
        subprocess.run([os.path.join(ROOT, "mame", "run.sh"), steps, out], stdout=fh, stderr=subprocess.STDOUT,
                       env=dict(config.env(), SD1_SECONDS="600"), check=False)
    with open(log) as f:
        text = f.read()
    if "FAILED" in text or "LUA ERROR" in text:
        sys.exit("format failed; see %s" % log)
    problems = check(out)
    if problems:
        sys.exit("formatted disk looks wrong: %s" % ", ".join(problems))
    print("wrote %s: SD-1-formatted, 1577 blocks free" % out)


if __name__ == "__main__":
    main()
