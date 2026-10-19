"""The setup checks read MAME's -listroms / -verifyroms output; test that parsing with recorded output."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import config  # noqa: E402

LISTROMS = """ROMs required for driver "sd132" (including device "esq2x40_vfx").
Name                                   Size Checksum
sd1_410_lo.bin                       131072 CRC(faa613a6) SHA1(60066765cddfa9d3b5d09057d8f83fb120f4e65e)
u37.bin                             1048576 CRC(d706cef3) SHA1(24ba35248509e9ca45110e2402b8085006ea0cfc)
esqvfd_font_vfx.bin                     192 CRC(58dc335b) SHA1(097fc3e1930a49ab61f73ea7a6191c892004f823)
"""
GOOD = "romset sd132 is good\n1 romsets found, 1 were OK.\n"
PARTIAL = """sd132       : u37.bin (1048576 bytes) - NOT FOUND
sd132       : esqvfd_font_vfx.bin (192 bytes) - INCORRECT CHECKSUM:
romset sd132 is bad
1 romsets found, 0 were OK.
"""
NONE = 'romset "sd132" not found!\n'


def fake(verify):
    def run(args, timeout=60):
        if "-version" in args:
            return 0, "0.283 (unknown)\n"
        if "-listfull" in args:
            return 0, 'Name:             Description:\nsd132             "SD-1 (32 voice)"\n'
        if "-listroms" in args:
            return 0, LISTROMS
        return 0, verify
    return run


class RomCheck(unittest.TestCase):
    def setUp(self):
        self.saved = config._run
        self.dir = tempfile.mkdtemp()
        self.mame = sys.executable   # any executable file passes the "is it a program" test

    def tearDown(self):
        config._run = self.saved

    def check(self, verify):
        config._run = fake(verify)
        return config.check_roms(self.mame, self.dir)

    def test_good(self):
        r = self.check(GOOD)
        self.assertTrue(r["ok"])
        self.assertEqual([f["status"] for f in r["files"]], ["ok"] * 3)

    def test_partial_names_each_bad_file(self):
        r = self.check(PARTIAL)
        self.assertFalse(r["ok"])
        st = {f["name"]: f["status"] for f in r["files"]}
        self.assertEqual(st["sd1_410_lo.bin"], "ok")
        self.assertEqual(st["u37.bin"], "NOT FOUND")
        self.assertTrue(st["esqvfd_font_vfx.bin"].startswith("INCORRECT CHECKSUM"))
        self.assertIn("2 of 3", r["message"])

    def test_no_romset(self):
        r = self.check(NONE)
        self.assertFalse(r["ok"])
        self.assertTrue(all(f["status"] == "NOT FOUND" for f in r["files"]))

    def test_missing_folder(self):
        r = config.check_roms(self.mame, os.path.join(self.dir, "nope"))
        self.assertFalse(r["ok"])
        self.assertIn("doesn't exist", r["message"])


if __name__ == "__main__":
    unittest.main()
