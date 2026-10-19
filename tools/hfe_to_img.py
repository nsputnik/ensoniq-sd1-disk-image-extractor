"""HFE (from HxC software / Gotek) -> 819,200-byte SD-1 disk image, tolerating bad sectors.

Read the floppy with 80 tracks, double-sided, and save as HFE. Don't use HxC's own IMG export: it drops
unreadable sectors without leaving a gap, which shifts every later block.

This decodes the MFM bit stream of every track, checks each sector's CRC, and places it at
block = track*20 + side*10 + sector (SD-1 sectors are numbered 0-9). It reports anything missing. Two
blocks hold no file data and are rebuilt when they're unreadable:
  block 0  format filler (0x6DB6 repeated)
  block 2  OS block: free-block count (recounted from the FAT) and the "OS" tag
Any other missing block is lost data (left zeroed and listed): re-read that track.

Supports HFE v1 ("HXCPICFE"), the format HxC writes by default.

usage: python3 -I tools/hfe_to_img.py <in.hfe> <out.img>
"""
import os
import struct
import sys

SYNC = "0100010010001001"   # 0xA1 with a missing clock bit (MFM 0x4489)
SECTOR = 512


def crc16(data, crc=0xFFFF):
    """CRC-CCITT (poly 0x1021), as used by the WD177x floppy controller."""
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021 if crc & 0x8000 else crc << 1) & 0xFFFF
    return crc


def read_hfe(path):
    """{(track, side): bytes of the raw MFM stream, bit 0 first}"""
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:8] != b"HXCPICFE":
        sys.exit("%s: not an HFE v1 file (header %r)" % (path, raw[:8]))
    tracks, sides = raw[9], raw[10]
    lut = struct.unpack("<H", raw[18:20])[0] * 512
    out = {}
    for t in range(tracks):
        off, length = struct.unpack("<HH", raw[lut + t * 4:lut + t * 4 + 4])
        data = raw[off * 512:off * 512 + length]
        for s in range(sides):
            # the two sides alternate in 256-byte chunks
            out[(t, s)] = b"".join(data[i + s * 256:i + s * 256 + 256] for i in range(0, len(data), 512))
    return out


def bits_of(stream):
    return "".join(format(b, "08b")[::-1] for b in stream)   # HFE stores each byte's bits LSB first


def mfm_bytes(bits, start, count):
    """Decode count bytes of MFM starting at bit start (clock, data, clock, data ...)."""
    out = bytearray()
    for i in range(count):
        cell = bits[start + i * 16:start + i * 16 + 16]
        if len(cell) < 16:
            return None
        out.append(int(cell[1::2], 2))
    return bytes(out)


def decode_track(stream, track, side):
    """{sector: 512 bytes} for every sector whose ID and data CRCs both check."""
    bits = bits_of(stream)
    bits += bits[:len(bits) // 4]   # a sector may straddle the index; read a bit past one revolution
    found, pos, want = {}, 0, None
    while True:
        p = bits.find(SYNC * 3, pos)
        if p < 0:
            return found
        pos = p + 48
        mark = mfm_bytes(bits, pos, 1)
        if mark is None:
            return found
        if mark[0] == 0xFE:                      # ID address mark
            idf = mfm_bytes(bits, pos + 16, 6)
            want = None
            if idf and crc16(b"\xA1\xA1\xA1\xFE" + idf[:4]) == struct.unpack(">H", idf[4:6])[0]:
                if idf[0] == track and idf[1] == side and idf[3] == 2:
                    want = idf[2]
        elif mark[0] in (0xFB, 0xF8) and want is not None:   # data address mark after a good ID
            body = mfm_bytes(bits, pos + 16, SECTOR + 2)
            if body and crc16(b"\xA1\xA1\xA1" + mark + body[:SECTOR]) == struct.unpack(">H", body[SECTOR:])[0]:
                found.setdefault(want, body[:SECTOR])
            want = None


def fat_free(img):
    """Free blocks = FAT entries that are 0 (FAT = blocks 5-14, 170 three-byte entries per block)."""
    return sum(img[(5 + b // 170) * 512 + (b % 170) * 3:][:3] == b"\0\0\0" for b in range(1600))


def os_block(img):
    blk = bytearray(SECTOR)
    blk[0:4] = struct.pack(">I", fat_free(img))
    blk[8:10] = b"\x00\x01"
    blk[0x1C:0x1E] = b"OS"
    return bytes(blk)


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    src, dst = sys.argv[1], sys.argv[2]
    if os.path.exists(dst):
        sys.exit("%s exists; not overwriting" % dst)
    sides = read_hfe(src)
    out = bytearray(1600 * SECTOR)
    missing = []
    for t in range(80):
        for s in range(2):
            secs = decode_track(sides.get((t, s), b""), t, s)
            for n in range(10):
                b = t * 20 + s * 10 + n
                if n in secs:
                    out[b * SECTOR:(b + 1) * SECTOR] = secs[n]
                else:
                    missing.append(b)
    lost = []
    for b in missing:
        if b == 0:
            out[0:SECTOR] = b"\x6d\xb6" * 256
            print("block 0 unreadable: filled with format filler (holds no data)")
        elif b == 2:
            out[2 * SECTOR:3 * SECTOR] = os_block(out)
            print("block 2 unreadable: OS block rebuilt, %d free blocks counted from the FAT" % fat_free(out))
        else:
            lost.append(b)
    for b in lost:
        print("block %d LOST (track %d side %d sector %d): left zeroed" % (b, b // 20, (b % 20) // 10, b % 10))
    print("%d/1600 sectors read, %d lost" % (1600 - len(missing), len(lost)))
    with open(dst, "wb") as f:
        f.write(out)
    print("wrote %s" % dst)
    sys.exit(1 if lost else 0)


if __name__ == "__main__":
    main()
