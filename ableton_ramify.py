#!/usr/bin/env python3
import gzip, shutil, argparse
import xml.etree.ElementTree as ET
from pathlib import Path


def is_gzip(b):
    return len(b) > 1 and b[:2] == b"\x1f\x8b"


def read(p):
    b = p.read_bytes()
    return gzip.decompress(b) if is_gzip(b) else b


def write(p, b):
    p.write_bytes(gzip.compress(b))


def flip(xml):
    root = ET.fromstring(xml)
    seen = flips = 0

    def t(x):
        return x.split("}", 1)[-1]

    for a in root.iter():
        if t(a.tag) == "AudioClip":
            seen += 1
            for r in a.iter():
                if t(r.tag) == "Ram" and r.attrib.get("Value", "").lower() != "true":
                    r.set("Value", "true")
                    flips += 1
    return ET.tostring(root, encoding="utf-8"), seen, flips


ap = argparse.ArgumentParser(
    description="Flip Ableton Live AudioClip RAM flags to true (.als)."
)
ap.add_argument("path", help="Set .als file or folder containing .als files")
ap.add_argument(
    "--in-place", action="store_true", help="Modify in place (creates .bak once)"
)
ap.add_argument("--dry-run", action="store_true", help="Show changes only")
ap.add_argument("--recursive", action="store_true", help="Recurse into subfolders")
args = ap.parse_args()

root = Path(args.path).expanduser()
files = []
if root.is_file():
    files = [root]
else:
    files = list(root.rglob("*.als") if args.recursive else root.glob("*.als"))

for f in files:
    xml = read(f)
    new, seen, flips = flip(xml)
    print(f"{f}: AudioClips={seen}, RamFlips={flips}")
    if flips and not args.dry_run:
        if args.in_place:
            bak = f.with_suffix(f.suffix + ".bak")
            if not bak.exists():
                shutil.copy2(f, bak)
            write(f, new)
        else:
            write(f.with_name(f.stem + ".ram" + f.suffix), new)
