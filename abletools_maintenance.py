#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Run maintenance on Abletools catalog DB.")
    ap.add_argument("db", help="Path to abletools_catalog.sqlite")
    ap.add_argument("--analyze", action="store_true", help="Run ANALYZE")
    ap.add_argument("--optimize", action="store_true", help="Run PRAGMA optimize")
    ap.add_argument("--vacuum", action="store_true", help="Run VACUUM")
    args = ap.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")

    if not (args.analyze or args.optimize or args.vacuum):
        args.analyze = True
        args.optimize = True

    with sqlite3.connect(db_path) as conn:
        if args.analyze:
            conn.execute("ANALYZE")
        if args.optimize:
            conn.execute("PRAGMA optimize")
        if args.vacuum:
            conn.execute("VACUUM")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
