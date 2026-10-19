"""Read an Ensoniq SD-1 / VFX-SD disk image (.img, 819,200 bytes): directory, FAT, file data.

Layout (see FINDINGS.md section 1): 1600 blocks of 512 bytes; FAT in blocks 5-14 (170 three-byte entries per
block: 0 free, 1 end of file, 2 bad block, else the next block); four sub-directories in blocks 15-22, each
39 entries of 26 bytes.

  python3 -I tools/sd1disk.py disk.img        # list the files
"""
import struct
import sys

BLOCK = 512
BLOCKS = 1600
TYPES = {
    0x0A: "OneProgram", 0x0B: "SixPrograms", 0x0C: "ThirtyPrograms", 0x0D: "SixtyPrograms",
    0x0E: "OnePreset", 0x0F: "TenPresets", 0x10: "TwentyPresets", 0x11: "OneSequence",
    0x12: "ThirtySequences", 0x13: "SixtySequences", 0x14: "SystemExclusive", 0x15: "SystemSetup",
    0x16: "SequencerOs",
}


class DiskError(Exception):
    pass


class Entry:
    def __init__(self, disk, raw, subdir):
        self.type_info, self.type = raw[0], raw[1]
        self.name = raw[2:13].decode("latin1").rstrip()   # leading spaces are part of the name
        self.blocks = struct.unpack(">H", raw[14:16])[0]
        self.first = struct.unpack(">I", raw[18:22])[0]
        self.number = raw[22]
        self.size = int.from_bytes(raw[23:26], "big")
        self.subdir = subdir
        self._disk = disk

    @property
    def type_name(self):
        return TYPES.get(self.type, "type %02X" % self.type)

    @property
    def has_programs(self):
        """A sequence file saved with programs (the SD-1 load page shows a flashing P)."""
        return self.type in (0x12, 0x13) and self.type_info in (0x20, 0x2F)

    def data(self):
        return self._disk.read_chain(self.first)[:self.size]


class Disk:
    def __init__(self, path):
        with open(path, "rb") as f:
            self.raw = f.read()
        if len(self.raw) != BLOCKS * BLOCK:
            raise DiskError("%s: %d bytes, expected %d" % (path, len(self.raw), BLOCKS * BLOCK))

    def block(self, n):
        return self.raw[n * BLOCK:(n + 1) * BLOCK]

    def fat(self, n):
        o = (5 + n // 170) * BLOCK + (n % 170) * 3
        return int.from_bytes(self.raw[o:o + 3], "big")

    def read_chain(self, first):
        out, b, seen = [], first, set()
        while True:
            if b in seen or not 0 < b < BLOCKS:
                raise DiskError("broken FAT chain at block %d" % b)
            seen.add(b)
            out.append(self.block(b))
            n = self.fat(b)
            if n == 1:
                return b"".join(out)
            if n == 0:
                raise DiskError("FAT chain runs into a free block after block %d" % b)
            if n == 2:
                raise DiskError("FAT marks block %d as bad" % b)
            b = n

    def entries(self):
        for sub in range(4):
            raw = self.raw[(15 + sub * 2) * BLOCK:(17 + sub * 2) * BLOCK]
            for i in range(39):
                e = raw[i * 26:(i + 1) * 26]
                if e[1] in TYPES:   # unused entries are zeros, or format filler (6D B6) on a fresh disk
                    yield Entry(self, e, sub + 1)

    def free_blocks(self):
        return sum(1 for n in range(BLOCKS) if self.fat(n) == 0)


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    d = Disk(sys.argv[1])
    print("%-13s %-16s %7s %8s  %s" % ("NAME", "TYPE", "BLOCKS", "BYTES", "NOTE"))
    for e in d.entries():
        print("%-13r %-16s %7d %8d  %s" % (e.name, e.type_name, e.blocks, e.size,
                                           "programs saved in file" if e.has_programs else ""))
    print("%d free blocks" % d.free_blocks())


if __name__ == "__main__":
    main()
