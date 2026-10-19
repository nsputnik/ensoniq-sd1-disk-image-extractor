"""Disk reader and HFE decoder tests on synthetic images (no real disks needed)."""
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import hfe_to_img  # noqa: E402
from sd1disk import Disk, DiskError  # noqa: E402


def set_fat(img, block, value):
    o = (5 + block // 170) * 512 + (block % 170) * 3
    img[o:o + 3] = value.to_bytes(3, "big")


def make_image(chain_end=1):
    """A blank image holding one 2-block OneProgram file, 'TEST-PROG', in blocks 23 -> 24."""
    img = bytearray(1600 * 512)
    for b in range(23):
        set_fat(img, b, 1)
    set_fat(img, 23, 24)
    set_fat(img, 24, chain_end)
    img[23 * 512:23 * 512 + 512] = bytes(range(256)) * 2
    img[24 * 512:24 * 512 + 18] = b"second block data!"
    e = bytearray(26)
    e[1] = 0x0A
    e[2:13] = b"TEST-PROG  "
    e[14:16] = struct.pack(">H", 2)
    e[18:22] = struct.pack(">I", 23)
    e[23:26] = (530).to_bytes(3, "big")
    img[15 * 512:15 * 512 + 26] = e
    return img


def write_tmp(data, suffix):
    f = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    f.write(data)
    f.close()
    return f.name


class DiskReader(unittest.TestCase):
    def test_list_and_read(self):
        d = Disk(write_tmp(make_image(), ".img"))
        (e,) = list(d.entries())
        self.assertEqual((e.name, e.type_name, e.size), ("TEST-PROG", "OneProgram", 530))
        self.assertEqual(e.data()[512:530], b"second block data!")
        self.assertEqual(d.free_blocks(), 1600 - 25)

    def test_bad_block_in_chain_is_an_error(self):
        d = Disk(write_tmp(make_image(chain_end=2), ".img"))
        with self.assertRaises(DiskError):
            next(d.entries()).data()

    def test_wrong_size_rejected(self):
        with self.assertRaises(DiskError):
            Disk(write_tmp(b"\0" * 1000, ".img"))


# --- a minimal MFM / HFE v1 writer, enough to test the decoder -----------------------------------

def mfm(data, prev=0):
    """MFM-encode bytes -> '0'/'1' string (clock bit 1 only between two 0 data bits)."""
    out = []
    for byte in data:
        for i in range(7, -1, -1):
            bit = (byte >> i) & 1
            out.append("1" if (not bit and not prev) else "0")
            out.append(str(bit))
            prev = bit
    return "".join(out)


def track_bits(track, side, sectors, corrupt=()):
    bits = mfm(b"\x4e" * 60)
    for n, data in sectors.items():
        idf = bytes([track, side, n, 2])
        crc = hfe_to_img.crc16(b"\xA1\xA1\xA1\xFE" + idf)
        bits += mfm(b"\0" * 12) + hfe_to_img.SYNC * 3 + mfm(b"\xFE" + idf + struct.pack(">H", crc), 1)
        bits += mfm(b"\x4e" * 22)
        crc = hfe_to_img.crc16(b"\xA1\xA1\xA1\xFB" + data)
        if n in corrupt:
            crc ^= 0xFFFF
        bits += mfm(b"\0" * 12) + hfe_to_img.SYNC * 3 + mfm(b"\xFB" + data + struct.pack(">H", crc), 1)
        bits += mfm(b"\x4e" * 40)
    bits += "0" * (-len(bits) % 8)
    return bytes(int(bits[i:i + 8][::-1], 2) for i in range(0, len(bits), 8))   # LSB first


def make_hfe(disk, corrupt=None):
    tracks = []
    for t in range(80):
        s0 = track_bits(t, 0, {n: disk[(t * 20 + n) * 512:][:512] for n in range(10)},
                        (corrupt or {}).get((t, 0), ()))
        s1 = track_bits(t, 1, {n: disk[(t * 20 + 10 + n) * 512:][:512] for n in range(10)},
                        (corrupt or {}).get((t, 1), ()))
        n = max(len(s0), len(s1))
        n += -n % 256
        s0, s1 = s0.ljust(n, b"\0"), s1.ljust(n, b"\0")
        tracks.append(b"".join(s0[i:i + 256] + s1[i:i + 256] for i in range(0, n, 256)))
    header = bytearray(512)
    header[0:8] = b"HXCPICFE"
    header[9], header[10] = 80, 2
    header[18:20] = struct.pack("<H", 1)
    lut, body, block = bytearray(512), bytearray(), 2
    for i, tr in enumerate(tracks):
        lut[i * 4:i * 4 + 4] = struct.pack("<HH", block, len(tr))
        tr = tr.ljust(-(-len(tr) // 512) * 512, b"\0")
        body += tr
        block += len(tr) // 512
    return bytes(header) + bytes(lut) + bytes(body)


class HfeDecoder(unittest.TestCase):
    def test_round_trip_and_bad_sectors(self):
        disk = make_image()
        disk[0:512] = b"\x6d\xb6" * 256
        disk[2 * 512:2 * 512 + 4] = struct.pack(">I", 1575)
        disk[2 * 512 + 0x1C:2 * 512 + 0x1E] = b"OS"
        for b in range(25, 1600):
            disk[b * 512:b * 512 + 4] = struct.pack(">I", b)
        # corrupt the data CRC of block 2 (rebuildable) and block 45 (track 2 side 0 sector 5: lost)
        hfe = write_tmp(make_hfe(disk, corrupt={(0, 0): (2,), (2, 0): (5,)}), ".hfe")
        out = hfe + ".img"
        with self.assertRaises(SystemExit) as cm:
            sys.argv = ["hfe_to_img", hfe, out]
            hfe_to_img.main()
        self.assertEqual(cm.exception.code, 1)   # one block lost
        with open(out, "rb") as f:
            got = f.read()
        lost = [b for b in range(1600) if got[b * 512:(b + 1) * 512] != disk[b * 512:(b + 1) * 512]]
        self.assertEqual(lost, [2, 45])
        self.assertEqual(struct.unpack(">I", got[1024:1028])[0], 1575)   # rebuilt free count
        self.assertEqual(got[1024 + 0x1C:1024 + 0x1E], b"OS")


if __name__ == "__main__":
    unittest.main()
