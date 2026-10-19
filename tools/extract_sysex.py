"""Save every SystemExclusive file on an SD-1 disk image as a plain .syx.

The SD-1 can record a SysEx dump from any MIDI device and save it to disk. On disk such a file is an
8-byte header followed by the raw F0 ... F7 messages exactly as received. This strips the header,
checks that the messages are complete, and names the sender from its manufacturer ID.

usage: python3 -I tools/extract_sysex.py <disk.img> <outdir>
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sd1disk import Disk  # noqa: E402

SYSEX = 0x14   # directory file type
HEADER = 8
MAKERS = {0x01: "Sequential", 0x04: "Moog", 0x06: "Lexicon", 0x07: "Kurzweil", 0x0F: "Ensoniq",
          0x10: "Oberheim", 0x18: "E-mu", 0x1A: "ART", 0x40: "Kawai", 0x41: "Roland", 0x42: "Korg",
          0x43: "Yamaha", 0x44: "Casio", 0x47: "Akai", 0x7D: "non-commercial"}


def split(syx):
    """[messages], or None if the stream isn't a run of complete F0 ... F7 messages."""
    msgs, j = [], 0
    while j < len(syx):
        if syx[j] != 0xF0 or 0xF7 not in syx[j:]:
            return None
        k = syx.index(0xF7, j)
        if any(x >= 0x80 for x in syx[j + 1:k]):
            return None
        msgs.append(syx[j:k + 1])
        j = k + 1
    return msgs


def maker(m):
    if len(m) > 3 and m[1] == 0x00:
        return "maker 00 %02X %02X" % (m[2], m[3])
    return MAKERS.get(m[1], "maker %02X" % m[1]) if len(m) > 1 else "unknown"


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    disk = Disk(sys.argv[1])
    outdir = sys.argv[2]
    os.makedirs(outdir, exist_ok=True)
    for e in disk.entries():
        if e.type != SYSEX:
            continue
        syx = e.data()[HEADER:]
        msgs = split(syx)
        who = maker(msgs[0]) if msgs else "unchecked"
        fn = os.path.join(outdir, ("%s - %s.syx" % (" ".join(e.name.split()), who)).replace("/", "-"))
        open(fn, "wb").write(syx)
        if msgs:
            kinds = sorted({x[:5].hex(" ") for x in msgs})
            print("%s: %d messages, %d bytes; starts %s" % (os.path.basename(fn), len(msgs), len(syx), ", ".join(kinds)))
        else:
            print("%s: %d bytes, NOT a clean run of F0...F7 messages (saved as-is)" % (os.path.basename(fn), len(syx)))


if __name__ == "__main__":
    main()
