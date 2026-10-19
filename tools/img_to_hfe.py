"""SD-1 disk image (.img, 819,200 bytes) -> HFE v1, for HxC / Gotek floppy emulators and for MAME.

Each side of each track is MFM-encoded with standard WD177x framing (ID and data address marks, CRCs,
gaps) and SD-1 sector numbering 0-9, filled out to one revolution at 300 rpm and 250 kbit/s.

MAME can write HFE but not the Ensoniq .img layout: when it saves an .img it renumbers sectors from 1 and
shifts every track by one sector. Mount an HFE when the emulated SD-1 is going to write to the disk.

usage: python3 -I tools/img_to_hfe.py <in.img> <out.hfe>
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hfe_to_img import SYNC, crc16  # noqa: E402

TRACKS, SIDES, SECTORS, SECTOR = 80, 2, 10, 512
SIDE_BYTES = 12522          # HFE bytes per side = 100,176 MFM cells: one revolution at 300 rpm, 250 kbit/s
GAP4A, GAP1, GAP2, GAP3 = 60, 40, 22, 30


def mfm(data, prev=0):
    """MFM cells for data bytes, as a '0'/'1' string (clock 1 only between two 0 data bits)."""
    out = []
    for byte in data:
        for i in range(7, -1, -1):
            bit = (byte >> i) & 1
            out.append("1" if (not bit and not prev) else "0")
            out.append(str(bit))
            prev = bit
    return "".join(out)


def side_cells(img, track, side):
    cells = mfm(b"\x4e" * GAP4A) + mfm(b"\x00" * 12) + mfm(b"\x4e" * GAP1, 0)
    for n in range(SECTORS):
        block = track * 20 + side * 10 + n
        data = img[block * SECTOR:(block + 1) * SECTOR]
        idf = bytes([track, side, n, 2])                       # size code 2 = 512 bytes
        cells += mfm(b"\x00" * 12) + SYNC * 3 + mfm(b"\xFE" + idf + struct.pack(">H", crc16(b"\xA1\xA1\xA1\xFE" + idf)), 1)
        cells += mfm(b"\x4e" * GAP2)
        cells += mfm(b"\x00" * 12) + SYNC * 3 + mfm(b"\xFB" + data + struct.pack(">H", crc16(b"\xA1\xA1\xA1\xFB" + data)), 1)
        cells += mfm(b"\x4e" * GAP3)
    total = SIDE_BYTES * 8
    if len(cells) > total:
        raise ValueError("track %d side %d doesn't fit one revolution" % (track, side))
    cells += mfm(b"\x4e" * ((total - len(cells)) // 16 + 1))
    cells = cells[:total]
    return bytes(int(cells[i:i + 8][::-1], 2) for i in range(0, total, 8))   # HFE stores bits LSB first


def to_hfe(img):
    header = bytearray(b"\xff" * 512)
    header[0:8] = b"HXCPICFE"
    header[8], header[9], header[10], header[11] = 0, TRACKS, SIDES, 0          # revision, tracks, sides, ISOIBM MFM
    header[12:14] = struct.pack("<H", 250)                                      # kbit/s
    header[14:16] = struct.pack("<H", 0)                                        # rpm (unused)
    header[16], header[17] = 7, 0xFF                                            # generic Shugart DD interface
    header[18:20] = struct.pack("<H", 1)                                        # track list in block 1
    lut, body = bytearray(b"\xff" * 512), bytearray()
    block = 2
    for t in range(TRACKS):
        s0, s1 = side_cells(img, t, 0), side_cells(img, t, 1)
        n = -(-SIDE_BYTES // 256) * 256
        s0, s1 = s0.ljust(n, b"\x4e"), s1.ljust(n, b"\x4e")
        data = b"".join(s0[i:i + 256] + s1[i:i + 256] for i in range(0, n, 256))
        lut[t * 4:t * 4 + 4] = struct.pack("<HH", block, SIDE_BYTES * 2)
        body += data
        block += len(data) // 512
    return bytes(header) + bytes(lut) + bytes(body)


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    with open(sys.argv[1], "rb") as f:
        img = f.read()
    if len(img) != TRACKS * SIDES * SECTORS * SECTOR:
        sys.exit("%s: %d bytes, expected 819200" % (sys.argv[1], len(img)))
    if os.path.exists(sys.argv[2]):
        sys.exit("%s exists; not overwriting" % sys.argv[2])
    with open(sys.argv[2], "wb") as f:
        f.write(to_hfe(img))
    print("wrote %s" % sys.argv[2])


if __name__ == "__main__":
    main()
