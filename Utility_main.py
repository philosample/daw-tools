#!/usr/bin/env python3
"""
ableton_ramify.py
Flip Ableton Live AudioClip RAM flags to true in .als/.alc files.

Usage examples:
  python ableton_ramify.py "/path/to/Set.als" --in-place
  python ableton_ramify.py "/path/to/folder" --in-place
  python ableton_ramify.py "/path/to/folder" --in-place --recursive
  python ableton_ramify.py "/path/to/Set.als" --dry-run
"""

from __future__ import annotations

import argparse
import gzip
import os
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable, Tuple

SUPPORTED_EXTS = {".als", ".alc"}


def is_gzip(data: bytes) -> bool:
    return len(data) >= 2 and data[0] == 0x1F and data[1] == 0x8B


def read_als_like(path: Path) -> bytes:
    raw = path.read_bytes()
    if is_gzip(raw):
        return gzip.decompress(raw)
    # Some people rename things or already decompressed; handle plain XML too.
    return raw


def write_als_like(path: Path, xml_bytes: bytes) -> None:
    # Ableton expects gzip container in typical .als; gzip it unconditionally.
    gz = gzip.compress(xml_bytes)
    path.write_bytes(gz)


def iter_targets(root: Path, recursive: bool) -> Iterable[Path]:
    if root.is_file():
        if root.suffix.lower() in SUPPORTED_EXTS:
            yield root
        return

    if root.is_dir():
        if recursive:
            for p in root.rglob("*"):
                if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
                    yield p
        else:
            for p in root.glob("*"):
                if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
                    yield p
        return

    raise FileNotFoundError(f"Not found: {root}")


def flip_ram_flags(xml_bytes: bytes) -> Tuple[bytes, int, int]:
    """
    Returns (new_xml_bytes, audio_clips_seen, ram_flips_done)
    """
    # Preserve as much as possible by not "pretty printing".
    # ElementTree will rewrite some formatting, but Live generally tolerates it.
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        raise ValueError(f"XML parse failed: {e}") from e

    audio_clips_seen = 0
    flips = 0

    # Ableton XML usually has no namespaces; if it does, tags look like "{ns}AudioClip".
    def local(tag: str) -> str:
        return tag.split("}", 1)[-1] if "}" in tag else tag

    for elem in root.iter():
        if local(elem.tag) != "AudioClip":
            continue

        audio_clips_seen += 1

        # Look for Ram elements under this AudioClip only
        for sub in elem.iter():
            if local(sub.tag) != "Ram":
                continue

            # Ableton uses Value="true/false" most commonly
            v = sub.attrib.get("Value")
            if v is None:
                # Some versions may encode differently; skip safely
                continue
            if v.lower() != "true":
                sub.set("Value", "true")
                flips += 1

    new_xml = ET.tostring(root, encoding="utf-8", method="xml")
    return new_xml, audio_clips_seen, flips


def ensure_backup(path: Path) -> Path:
    bak = path.with_suffix(path.suffix + ".bak")
    if not bak.exists():
        shutil.copy2(path, bak)
    return bak


def process_file(path: Path, in_place: bool, dry_run: bool) -> Tuple[int, int]:
    xml_bytes = read_als_like(path)
    new_xml, audio_seen, flips = flip_ram_flags(xml_bytes)

    if flips == 0:
        return audio_seen, flips

    if dry_run:
        return audio_seen, flips

    if in_place:
        ensure_backup(path)
        write_als_like(path, new_xml)
    else:
        out = path.with_name(path.stem + ".ram" + path.suffix)
        write_als_like(out, new_xml)

    return audio_seen, flips


def main() -> int:
    ap = argparse.ArgumentParser(description="Flip Ableton AudioClip RAM flags to true.")
    ap.add_argument("path", type=str, help="A .als/.alc file or a folder")
    ap.add_argument("--recursive", action="store_true", help="Recurse into subfolders")
    ap.add_argument("--in-place", action="store_true",
                    help="Modify files in place (creates .bak once). Otherwise writes *.ram.als")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would change, but don’t write anything")
    args = ap.parse_args()

    root = Path(args.path).expanduser()

    total_files = 0
    total_audio = 0
    total_flips = 0
    failed = 0

    for p in iter_targets(root, args.recursive):
        total_files += 1
        try:
            audio_seen, flips = process_file(p, in_place=args.in_place, dry_run=args.dry_run)
            total_audio += audio_seen
            total_flips += flips
            action = "DRY" if args.dry_run else ("INPLACE" if args.in_place else "OUT")
            print(f"[{action}] {p} | AudioClips={audio_seen} | RamFlips={flips}")
        except Exception as e:
            failed += 1
            print(f"[FAIL] {p} | {e}", file=sys.stderr)

    print(f"\nDone. Files={total_files}, Failed={failed}, AudioClips={total_audio}, RamFlips={total_flips}")
    if args.dry_run and total_flips > 0:
        print("Re-run with --in-place to apply changes (backups will be created).")
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
