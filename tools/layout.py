"""Where an export's files live. Only .mid files sit at the top of <FILE>/:

  <FILE>/<name>.mid        the MIDI files
  <FILE>/cap/<name>.cap    raw MIDI OUT capture ("<emulated-seconds> <byte>" per line)
  <FILE>/json/<name>.json  per-file summary + the converter args that made it
  <FILE>/json/manifest.json  banks, songs (steps, tempo offset, meters) and output names
  <FILE>/logs/*.log        MAME run logs (every display dump, step and conversion)
"""
import os


def mid(d, name):
    return os.path.join(d, name + ".mid")


def cap(d, name):
    return os.path.join(d, "cap", name + ".cap")


def info(d, name):
    return os.path.join(d, "json", name + ".json")


def manifest(d):
    return os.path.join(d, "json", "manifest.json")


def log(d, name):
    return os.path.join(d, "logs", name + ".log")


def from_cap(path):
    """X/cap/name.cap -> (X, name)"""
    return os.path.dirname(os.path.dirname(path)), os.path.basename(path)[:-4]


def ensure(d):
    for sub in ("cap", "json", "logs"):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
