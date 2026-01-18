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
import sys
from pathlib import Path

from ramify_core import iter_targets, process_file


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
            audio_seen, flips, _wrote = process_file(
                p, in_place=args.in_place, dry_run=args.dry_run
            )
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
