"""Save every SD-1 program and preset on a disk image as SysEx (.syx) a real SD-1 accepts.

  OneProgram          -> <NAME>.syx                    one-program dump (lands in the edit buffer)
  SixtyPrograms       -> <NAME> - 60 programs.syx      all-programs dump (replaces all 60 internal programs)
  ThirtyPrograms      -> <NAME> - 30 programs/NN <PROGRAM>.syx   one dump per program (SysEx has no
                         half-bank dump; the SD-1 itself loads a 30-program file into one half)
  TwentyPresets       -> <NAME> - 20 presets.syx       all-presets dump
  30/60-SEQ files saved with programs (directory type_info 0x20, "P" on the load page)
                      -> <NAME> - programs from sequence file.syx   all-programs dump of the 60
                         programs stored in the file: the sounds the sequences were made with

Also writes index.txt listing every program by internal bank.slot (bank 0-9, slot 1-6).
Message layout: F0 0F 05 00 <channel> <type> <payload as high/low nybbles> F7,
type 02 = one program, 03 = all programs, 05 = all presets. On disk, 60 programs are a byte interleave
of programs 0-29 (even bytes) and 30-59 (odd bytes); the dump lists them in order.

usage: python3 -I tools/extract_programs.py <disk.img> <outdir>
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sd1disk import Disk  # noqa: E402

PROG = 530
NAME_AT = 498   # program name: 11 bytes at this offset
ONE, ALL, PRESETS = 0x02, 0x03, 0x05
T_ONE, T_SIX, T_THIRTY, T_SIXTY, T_PRESETS, T_SEQ30, T_SEQ60 = 0x0A, 0x0B, 0x0C, 0x0D, 0x10, 0x12, 0x13


def sysex(kind, payload, channel=0):
    return bytes([0xF0, 0x0F, 0x05, 0x00, channel, kind]) + \
        b"".join(bytes([x >> 4, x & 15]) for x in payload) + b"\xF7"


def deinterleave(block):
    """31800 on-disk bytes -> programs 0-59 in order."""
    return block[0::2] + block[1::2]


def pname(p):
    return p[NAME_AT:NAME_AT + 11].decode("latin1")


def safe(s):
    return " ".join(s.replace("/", "-").split()) or "unnamed"


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    disk = Disk(sys.argv[1])
    out = sys.argv[2]
    os.makedirs(out, exist_ok=True)
    index = []

    def listing(title, progs):
        index.append(title)
        for i, p in enumerate(progs):
            index.append("  %d.%d  %s" % (i // 6, i % 6 + 1, pname(p)))

    for e in disk.entries():
        kind, name = e.type, e.name
        if kind in (T_ONE, T_SIX, T_THIRTY, T_SIXTY, T_PRESETS, T_SEQ30, T_SEQ60):
            data = e.data()
            if kind == T_ONE:
                fn = "%s.syx" % safe(name)
                open(os.path.join(out, fn), "wb").write(sysex(ONE, data[:PROG]))
                index.append("%s: one program, %s" % (fn, pname(data)))
            elif kind == T_SIXTY:
                progs = deinterleave(data[:60 * PROG])
                fn = "%s - 60 programs.syx" % safe(name)
                open(os.path.join(out, fn), "wb").write(sysex(ALL, progs))
                listing(fn, [progs[k * PROG:(k + 1) * PROG] for k in range(60)])
            elif kind == T_THIRTY:
                sub_dir = "%s - 30 programs" % safe(name)
                os.makedirs(os.path.join(out, sub_dir), exist_ok=True)
                progs = [data[k * PROG:(k + 1) * PROG] for k in range(30)]
                for k, p in enumerate(progs):
                    open(os.path.join(out, sub_dir, "%02d %s.syx" % (k + 1, safe(pname(p)))), "wb").write(sysex(ONE, p))
                index.append("%s/: 30 one-program dumps (file order; the SD-1 loads them as one bank half)" % sub_dir)
                index += ["  %02d  %s" % (k + 1, pname(p)) for k, p in enumerate(progs)]
            elif kind == T_PRESETS:
                fn = "%s - 20 presets.syx" % safe(name)
                open(os.path.join(out, fn), "wb").write(sysex(PRESETS, data))
                index.append("%s: 20 presets" % fn)
            elif kind == T_SIX:
                index.append("%s: SixPrograms file, not handled" % name)
            elif e.has_programs:
                # sequence file with 60 programs: they follow the headers + global section
                at = 6144 if kind == T_SEQ30 else 11776
                progs = deinterleave(data[at:at + 60 * PROG])
                plist = [progs[k * PROG:(k + 1) * PROG] for k in range(60)]
                if not all(32 <= c < 127 for p in plist for c in p[NAME_AT:NAME_AT + 11]):
                    index.append("%s: flagged as holding programs, but no program names at %d; skipped" % (name, at))
                else:
                    fn = "%s - programs from sequence file.syx" % safe(name)
                    open(os.path.join(out, fn), "wb").write(sysex(ALL, progs))
                    listing(fn, plist)
            else:
                index.append("%s: sequence file without programs" % name)
    open(os.path.join(out, "index.txt"), "w").write("\n".join(index) + "\n")
    print("\n".join(l for l in index if not l.startswith("  ")))


if __name__ == "__main__":
    main()
