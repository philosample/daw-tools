#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import time
import sys
from collections import Counter, defaultdict
from pathlib import Path

SCOPES = ("live_recordings", "user_library", "preferences")


def scope_suffix(scope: str) -> str:
    return "" if scope == "live_recordings" else f"_{scope}"


def compute_device_usage(conn: sqlite3.Connection, scope: str) -> None:
    suffix = scope_suffix(scope)
    rows = conn.execute(
        f"SELECT device_hint, COUNT(*) FROM doc_device_hints{suffix} GROUP BY device_hint"
    ).fetchall()
    now_ts = int(time.time())
    for device_name, count in rows:
        conn.execute(
            """
            INSERT OR REPLACE INTO device_usage
                (scope, device_name, usage_count, computed_at)
            VALUES (?, ?, ?, ?)
            """,
            (scope, device_name, int(count), now_ts),
        )


def compute_device_chains(conn: sqlite3.Connection, scope: str, chain_len: int) -> None:
    suffix = scope_suffix(scope)
    sequences: dict[str, list[str]] = defaultdict(list)
    try:
        rows = conn.execute(
            f"SELECT doc_path, ord, device_name FROM doc_device_sequence{suffix} ORDER BY doc_path, ord"
        ).fetchall()
    except sqlite3.Error:
        return
    for doc_path, ord_idx, name in rows:
        sequences[doc_path].append(name)

    chain_counts: Counter[str] = Counter()
    for seq in sequences.values():
        if len(seq) < chain_len:
            continue
        for idx in range(0, len(seq) - chain_len + 1):
            chain = " > ".join(seq[idx : idx + chain_len])
            chain_counts[chain] += 1

    now_ts = int(time.time())
    for chain, count in chain_counts.items():
        conn.execute(
            """
            INSERT OR REPLACE INTO device_chain_stats
                (scope, chain, chain_len, usage_count, computed_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (scope, chain, chain_len, int(count), now_ts),
        )


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Compute Abletools analytics and store in DB.")
    ap.add_argument("db", help="Path to abletools_catalog.sqlite")
    ap.add_argument("--chain-len", type=int, default=3, help="Length of device chains")
    args = ap.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")

    with sqlite3.connect(db_path) as conn:
        for scope in SCOPES:
            compute_device_usage(conn, scope)
            compute_device_chains(conn, scope, args.chain_len)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
