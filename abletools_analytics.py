#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

SCOPES = ("live_recordings", "user_library", "preferences")
MAX_DEVICES_PER_DOC = 50
ACTIVITY_WINDOWS = (30, 90)
COLD_SAMPLE_CUTOFFS = (90, 180)
QUALITY_DEVICE_WARN = 150
QUALITY_SAMPLE_WARN = 500
BACKUP_EXCLUDE_CLAUSE = (
    "lower(path) NOT LIKE ? AND lower(path) NOT LIKE ? "
    "AND lower(path) NOT LIKE ? AND lower(path) NOT LIKE ? "
    "AND path NOT GLOB ?"
)
BACKUP_EXCLUDE_PARAMS = [
    "%/backup/%",
    "%\\backup\\%",
    "backup/%",
    "backup\\%",
    "*[[][0-9]*[]]*",
]


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


def compute_device_cooccurrence(conn: sqlite3.Connection, scope: str) -> None:
    suffix = scope_suffix(scope)
    doc_devices: dict[str, set[str]] = defaultdict(set)
    rows = conn.execute(
        f"SELECT doc_path, device_hint FROM doc_device_hints{suffix}"
    ).fetchall()
    for doc_path, device in rows:
        if device:
            doc_devices[doc_path].add(device)

    counts: Counter[tuple[str, str]] = Counter()
    for devices in doc_devices.values():
        if len(devices) > MAX_DEVICES_PER_DOC:
            continue
        sorted_devices = sorted(devices)
        for i in range(len(sorted_devices)):
            for j in range(i + 1, len(sorted_devices)):
                counts[(sorted_devices[i], sorted_devices[j])] += 1

    now_ts = int(time.time())
    for (a, b), count in counts.items():
        conn.execute(
            """
            INSERT OR REPLACE INTO device_cooccurrence
                (scope, device_a, device_b, usage_count, computed_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (scope, a, b, int(count), now_ts),
        )


def compute_doc_complexity(conn: sqlite3.Connection, scope: str) -> None:
    suffix = scope_suffix(scope)
    now_ts = int(time.time())
    conn.execute("DELETE FROM doc_complexity WHERE scope = ?", (scope,))
    conn.execute(
        f"""
        INSERT OR REPLACE INTO doc_complexity
            (scope, path, tracks_total, clips_total, devices_count,
             samples_count, missing_refs_count, computed_at)
        SELECT
            ?,
            d.path,
            d.tracks_total,
            d.clips_total,
            (SELECT COUNT(*) FROM doc_device_hints{suffix} dh WHERE dh.doc_path = d.path),
            (SELECT COUNT(*) FROM doc_sample_refs{suffix} ds WHERE ds.doc_path = d.path),
            (SELECT COUNT(*) FROM refs_graph{suffix} rg WHERE rg.src = d.path AND rg.ref_exists = 0),
            ?
        FROM ableton_docs{suffix} d
        """,
        (scope, now_ts),
    )


def compute_library_growth(conn: sqlite3.Connection, scope: str) -> None:
    suffix = scope_suffix(scope)
    now_ts = int(time.time())
    row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS file_count,
            COALESCE(SUM(size), 0) AS total_bytes,
            COALESCE(SUM(CASE WHEN kind = 'media' THEN size ELSE 0 END), 0) AS media_bytes,
            (SELECT COUNT(*) FROM ableton_docs{suffix}) AS doc_count
        FROM file_index{suffix}
        """
    ).fetchone()
    if not row:
        return
    conn.execute(
        """
        INSERT OR REPLACE INTO library_growth
            (scope, snapshot_at, file_count, total_bytes, media_bytes, doc_count)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (scope, now_ts, int(row[0]), int(row[1]), int(row[2]), int(row[3])),
    )


def compute_missing_refs_by_path(conn: sqlite3.Connection, scope: str) -> None:
    suffix = scope_suffix(scope)
    rows = conn.execute(
        f"SELECT ref_path FROM refs_graph{suffix} WHERE ref_exists = 0"
    ).fetchall()
    counts: Counter[str] = Counter()
    for (ref_path,) in rows:
        if not ref_path:
            continue
        parent = os.path.dirname(ref_path)
        counts[parent] += 1
    now_ts = int(time.time())
    conn.execute("DELETE FROM missing_refs_by_path WHERE scope = ?", (scope,))
    for parent, count in counts.items():
        conn.execute(
            """
            INSERT OR REPLACE INTO missing_refs_by_path
                (scope, ref_parent, missing_count, computed_at)
            VALUES (?, ?, ?, ?)
            """,
            (scope, parent, int(count), now_ts),
        )


def compute_set_health(conn: sqlite3.Connection, scope: str) -> None:
    now_ts = int(time.time())
    conn.execute("DELETE FROM set_health WHERE scope = ?", (scope,))
    rows = conn.execute(
        """
        SELECT path, tracks_total, clips_total, devices_count, samples_count, missing_refs_count
        FROM doc_complexity
        WHERE scope = ?
        """,
        (scope,),
    ).fetchall()
    for path, tracks, clips, devices, samples, missing in rows:
        devices = int(devices or 0)
        samples = int(samples or 0)
        missing = int(missing or 0)
        score = 100.0 - (missing * 10.0) - (devices * 1.0) - (samples * 0.2)
        if score < 0:
            score = 0.0
        conn.execute(
            """
            INSERT OR REPLACE INTO set_health
                (scope, path, tracks_total, clips_total, devices_count,
                 samples_count, missing_refs_count, health_score, computed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scope,
                path,
                int(tracks or 0),
                int(clips or 0),
                devices,
                samples,
                missing,
                float(score),
                now_ts,
            ),
        )


def compute_audio_footprint(conn: sqlite3.Connection, scope: str) -> None:
    suffix = scope_suffix(scope)
    now_ts = int(time.time())
    total_media = conn.execute(
        f"SELECT COALESCE(SUM(size), 0) FROM file_index{suffix} WHERE kind = 'media'"
    ).fetchone()[0]
    referenced_media = conn.execute(
        f"""
        SELECT COALESCE(SUM(fi.size), 0)
        FROM file_index{suffix} fi
        WHERE EXISTS (
            SELECT 1
            FROM doc_sample_refs{suffix} ds
            WHERE ds.sample_path = fi.path
               OR ds.sample_path = (fi.parent || '/' || fi.name)
        )
        """
    ).fetchone()[0]
    total_media = int(total_media or 0)
    referenced_media = int(referenced_media or 0)
    unreferenced = max(0, total_media - referenced_media)
    conn.execute(
        """
        INSERT OR REPLACE INTO audio_footprint
            (scope, total_media_bytes, referenced_media_bytes, unreferenced_media_bytes, computed_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (scope, total_media, referenced_media, unreferenced, now_ts),
    )


def compute_set_storage_summary(conn: sqlite3.Connection, scope: str) -> None:
    suffix = scope_suffix(scope)
    now_ts = int(time.time())
    total_row = conn.execute(
        f"SELECT COUNT(*), COALESCE(SUM(size), 0) "
        f"FROM file_index{suffix} WHERE kind = 'ableton_doc'"
    ).fetchone()
    non_backup_row = conn.execute(
        f"SELECT COUNT(*), COALESCE(SUM(size), 0) "
        f"FROM file_index{suffix} WHERE kind = 'ableton_doc' AND {BACKUP_EXCLUDE_CLAUSE}",
        BACKUP_EXCLUDE_PARAMS,
    ).fetchone()
    total_sets, total_bytes = total_row or (0, 0)
    non_backup_sets, non_backup_bytes = non_backup_row or (0, 0)
    conn.execute(
        """
        INSERT OR REPLACE INTO set_storage_summary
            (scope, total_sets, total_set_bytes, non_backup_sets, non_backup_bytes, computed_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            scope,
            int(total_sets or 0),
            int(total_bytes or 0),
            int(non_backup_sets or 0),
            int(non_backup_bytes or 0),
            now_ts,
        ),
    )


def compute_set_activity_stats(conn: sqlite3.Connection, scope: str) -> None:
    suffix = scope_suffix(scope)
    now_ts = int(time.time())
    conn.execute("DELETE FROM set_activity_stats WHERE scope = ?", (scope,))
    for days in ACTIVITY_WINDOWS:
        cutoff = now_ts - (days * 86400)
        row = conn.execute(
            f"""
            SELECT COUNT(*), COALESCE(SUM(size), 0)
            FROM file_index{suffix}
            WHERE kind = 'ableton_doc'
              AND {BACKUP_EXCLUDE_CLAUSE}
              AND mtime >= ?
            """,
            [*BACKUP_EXCLUDE_PARAMS, cutoff],
        ).fetchone()
        set_count, total_bytes = row or (0, 0)
        conn.execute(
            """
            INSERT OR REPLACE INTO set_activity_stats
                (scope, window_days, set_count, total_bytes, computed_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (scope, int(days), int(set_count or 0), int(total_bytes or 0), now_ts),
        )


def compute_set_size_top(
    conn: sqlite3.Connection, scope: str, limit: int = 10
) -> None:
    suffix = scope_suffix(scope)
    now_ts = int(time.time())
    conn.execute("DELETE FROM set_size_top WHERE scope = ?", (scope,))
    rows = conn.execute(
        f"""
        SELECT path, size, mtime
        FROM file_index{suffix}
        WHERE kind = 'ableton_doc' AND {BACKUP_EXCLUDE_CLAUSE}
        ORDER BY size DESC
        LIMIT ?
        """,
        [*BACKUP_EXCLUDE_PARAMS, limit],
    ).fetchall()
    for path, size, mtime in rows:
        conn.execute(
            """
            INSERT OR REPLACE INTO set_size_top
                (scope, path, size_bytes, mtime, computed_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (scope, path, int(size or 0), int(mtime or 0), now_ts),
        )


def compute_unreferenced_audio_by_path(conn: sqlite3.Connection, scope: str) -> None:
    suffix = scope_suffix(scope)
    now_ts = int(time.time())
    conn.execute("DELETE FROM unreferenced_audio_by_path WHERE scope = ?", (scope,))
    rows = conn.execute(
        f"""
        SELECT parent, COUNT(*), COALESCE(SUM(size), 0)
        FROM file_index{suffix} fi
        WHERE fi.kind = 'media'
          AND NOT EXISTS (
              SELECT 1
              FROM doc_sample_refs{suffix} ds
              WHERE ds.sample_path = fi.path
                 OR ds.sample_path = (fi.parent || '/' || fi.name)
          )
        GROUP BY parent
        ORDER BY COALESCE(SUM(size), 0) DESC
        """
    ).fetchall()
    for parent, count, total_bytes in rows:
        if not parent:
            continue
        conn.execute(
            """
            INSERT OR REPLACE INTO unreferenced_audio_by_path
                (scope, parent_path, file_count, total_bytes, computed_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (scope, parent, int(count or 0), int(total_bytes or 0), now_ts),
        )


def compute_quality_issues(conn: sqlite3.Connection, scope: str) -> None:
    now_ts = int(time.time())
    conn.execute("DELETE FROM quality_issues WHERE scope = ?", (scope,))
    rows = conn.execute(
        """
        SELECT path, tracks_total, clips_total, devices_count, samples_count, missing_refs_count
        FROM doc_complexity
        WHERE scope = ?
        """,
        (scope,),
    ).fetchall()
    for path, tracks, clips, devices, samples, missing in rows:
        tracks = int(tracks or 0)
        clips = int(clips or 0)
        devices = int(devices or 0)
        samples = int(samples or 0)
        missing = int(missing or 0)
        if tracks == 0:
            conn.execute(
                """
                INSERT OR REPLACE INTO quality_issues
                    (scope, path, issue, issue_value, computed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (scope, path, "zero_tracks", 0, now_ts),
            )
        if clips == 0:
            conn.execute(
                """
                INSERT OR REPLACE INTO quality_issues
                    (scope, path, issue, issue_value, computed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (scope, path, "zero_clips", 0, now_ts),
            )
        if missing > 0:
            conn.execute(
                """
                INSERT OR REPLACE INTO quality_issues
                    (scope, path, issue, issue_value, computed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (scope, path, "missing_refs", missing, now_ts),
            )
        if devices > QUALITY_DEVICE_WARN:
            conn.execute(
                """
                INSERT OR REPLACE INTO quality_issues
                    (scope, path, issue, issue_value, computed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (scope, path, "high_device_count", devices, now_ts),
            )
        if samples > QUALITY_SAMPLE_WARN:
            conn.execute(
                """
                INSERT OR REPLACE INTO quality_issues
                    (scope, path, issue, issue_value, computed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (scope, path, "high_sample_count", samples, now_ts),
            )


def compute_device_usage_recent(conn: sqlite3.Connection, scope: str) -> None:
    suffix = scope_suffix(scope)
    now_ts = int(time.time())
    conn.execute("DELETE FROM device_usage_recent WHERE scope = ?", (scope,))
    for days in ACTIVITY_WINDOWS:
        cutoff = now_ts - (days * 86400)
        rows = conn.execute(
            f"""
            SELECT dh.device_hint, COUNT(*)
            FROM doc_device_hints{suffix} dh
            JOIN file_index{suffix} fi ON fi.path = dh.doc_path
            WHERE fi.kind = 'ableton_doc'
              AND {BACKUP_EXCLUDE_CLAUSE}
              AND fi.mtime >= ?
            GROUP BY dh.device_hint
            """,
            [*BACKUP_EXCLUDE_PARAMS, cutoff],
        ).fetchall()
        for device_name, count in rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO device_usage_recent
                    (scope, window_days, device_name, usage_count, computed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (scope, int(days), device_name, int(count or 0), now_ts),
            )


def compute_set_activity_delta(conn: sqlite3.Connection, scope: str) -> None:
    suffix = scope_suffix(scope)
    now_ts = int(time.time())
    conn.execute("DELETE FROM set_activity_delta WHERE scope = ?", (scope,))
    for days in ACTIVITY_WINDOWS:
        current_cutoff = now_ts - (days * 86400)
        prev_cutoff = now_ts - (days * 2 * 86400)
        current_row = conn.execute(
            f"""
            SELECT COUNT(*), COALESCE(SUM(size), 0)
            FROM file_index{suffix}
            WHERE kind = 'ableton_doc'
              AND {BACKUP_EXCLUDE_CLAUSE}
              AND mtime >= ?
            """,
            [*BACKUP_EXCLUDE_PARAMS, current_cutoff],
        ).fetchone()
        previous_row = conn.execute(
            f"""
            SELECT COUNT(*), COALESCE(SUM(size), 0)
            FROM file_index{suffix}
            WHERE kind = 'ableton_doc'
              AND {BACKUP_EXCLUDE_CLAUSE}
              AND mtime >= ?
              AND mtime < ?
            """,
            [*BACKUP_EXCLUDE_PARAMS, prev_cutoff, current_cutoff],
        ).fetchone()
        current_sets, current_bytes = current_row or (0, 0)
        prev_sets, prev_bytes = previous_row or (0, 0)
        delta_bytes = int(current_bytes or 0) - int(prev_bytes or 0)
        conn.execute(
            """
            INSERT OR REPLACE INTO set_activity_delta
                (scope, window_days, current_sets, previous_sets, current_bytes, previous_bytes, delta_bytes, computed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scope,
                int(days),
                int(current_sets or 0),
                int(prev_sets or 0),
                int(current_bytes or 0),
                int(prev_bytes or 0),
                int(delta_bytes),
                now_ts,
            ),
        )


def compute_set_growth_by_parent(conn: sqlite3.Connection, scope: str) -> None:
    suffix = scope_suffix(scope)
    now_ts = int(time.time())
    conn.execute("DELETE FROM set_growth_by_parent WHERE scope = ?", (scope,))
    for days in ACTIVITY_WINDOWS:
        current_cutoff = now_ts - (days * 86400)
        prev_cutoff = now_ts - (days * 2 * 86400)
        rows = conn.execute(
            f"""
            SELECT parent,
                   SUM(CASE WHEN mtime >= ? THEN 1 ELSE 0 END) AS current_sets,
                   SUM(CASE WHEN mtime >= ? THEN size ELSE 0 END) AS current_bytes,
                   SUM(CASE WHEN mtime >= ? AND mtime < ? THEN 1 ELSE 0 END) AS previous_sets,
                   SUM(CASE WHEN mtime >= ? AND mtime < ? THEN size ELSE 0 END) AS previous_bytes
            FROM file_index{suffix}
            WHERE kind = 'ableton_doc' AND {BACKUP_EXCLUDE_CLAUSE}
            GROUP BY parent
            """,
            [
                current_cutoff,
                current_cutoff,
                prev_cutoff,
                current_cutoff,
                prev_cutoff,
                current_cutoff,
                *BACKUP_EXCLUDE_PARAMS,
            ],
        ).fetchall()
        for parent, current_sets, current_bytes, prev_sets, prev_bytes in rows:
            if not parent:
                continue
            delta_bytes = int(current_bytes or 0) - int(prev_bytes or 0)
            if current_sets is None and prev_sets is None:
                continue
            conn.execute(
                """
                INSERT OR REPLACE INTO set_growth_by_parent
                    (scope, window_days, parent_path, current_sets, previous_sets,
                     current_bytes, previous_bytes, delta_bytes, computed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scope,
                    int(days),
                    parent,
                    int(current_sets or 0),
                    int(prev_sets or 0),
                    int(current_bytes or 0),
                    int(prev_bytes or 0),
                    int(delta_bytes),
                    now_ts,
                ),
            )


def compute_sample_duplicate_groups(conn: sqlite3.Connection, scope: str) -> None:
    suffix = scope_suffix(scope)
    now_ts = int(time.time())
    conn.execute("DELETE FROM sample_duplicate_groups WHERE scope = ?", (scope,))
    rows = conn.execute(
        f"""
        SELECT sha1, COUNT(*) AS file_count, COALESCE(SUM(size), 0) AS total_bytes,
               MIN(path) AS example_path
        FROM file_index{suffix}
        WHERE kind = 'media' AND sha1 IS NOT NULL AND sha1 != ''
        GROUP BY sha1
        HAVING COUNT(*) > 1
        ORDER BY total_bytes DESC
        """
    ).fetchall()
    for sha1, file_count, total_bytes, example_path in rows:
        conn.execute(
            """
            INSERT OR REPLACE INTO sample_duplicate_groups
                (scope, sha1, file_count, total_bytes, example_path, computed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                scope,
                str(sha1),
                int(file_count or 0),
                int(total_bytes or 0),
                example_path,
                now_ts,
            ),
        )


def compute_cold_samples(conn: sqlite3.Connection, scope: str) -> None:
    suffix = scope_suffix(scope)
    now_ts = int(time.time())
    conn.execute("DELETE FROM cold_samples_summary WHERE scope = ?", (scope,))
    conn.execute("DELETE FROM cold_samples_by_path WHERE scope = ?", (scope,))
    doc_clause = (
        "lower(doc.path) NOT LIKE ? AND lower(doc.path) NOT LIKE ? "
        "AND lower(doc.path) NOT LIKE ? AND lower(doc.path) NOT LIKE ? "
        "AND doc.path NOT GLOB ?"
    )
    for cutoff_days in COLD_SAMPLE_CUTOFFS:
        cutoff_ts = now_ts - (cutoff_days * 86400)
        rows = conn.execute(
            f"""
            SELECT fi.path,
                   fi.parent,
                   fi.size,
                   MAX(doc.mtime) AS last_used
            FROM file_index{suffix} fi
            LEFT JOIN doc_sample_refs{suffix} ds
              ON ds.sample_path = fi.path
              OR ds.sample_path = (fi.parent || '/' || fi.name)
            LEFT JOIN file_index{suffix} doc
              ON doc.path = ds.doc_path
             AND doc.kind = 'ableton_doc'
             AND {doc_clause}
            WHERE fi.kind = 'media'
            GROUP BY fi.path, fi.parent, fi.size
            """
        ,
            BACKUP_EXCLUDE_PARAMS,
        ).fetchall()
        total_count = 0
        total_bytes = 0
        by_parent: dict[str, tuple[int, int]] = {}
        for path, parent, size, last_used in rows:
            last_used = int(last_used or 0)
            if last_used >= cutoff_ts:
                continue
            total_count += 1
            total_bytes += int(size or 0)
            if parent:
                current = by_parent.get(parent, (0, 0))
                by_parent[parent] = (
                    current[0] + 1,
                    current[1] + int(size or 0),
                )
        conn.execute(
            """
            INSERT OR REPLACE INTO cold_samples_summary
                (scope, cutoff_days, sample_count, total_bytes, computed_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (scope, int(cutoff_days), int(total_count), int(total_bytes), now_ts),
        )
        for parent, (count, bytes_total) in by_parent.items():
            conn.execute(
                """
                INSERT OR REPLACE INTO cold_samples_by_path
                    (scope, cutoff_days, parent_path, sample_count, total_bytes, computed_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    scope,
                    int(cutoff_days),
                    parent,
                    int(count),
                    int(bytes_total),
                    now_ts,
                ),
            )


def compute_routing_anomalies(conn: sqlite3.Connection, scope: str) -> None:
    suffix = scope_suffix(scope)
    now_ts = int(time.time())
    conn.execute("DELETE FROM routing_anomalies WHERE scope = ?", (scope,))
    rows = conn.execute(
        f"""
        SELECT doc_path,
               SUM(CASE WHEN value IS NULL OR TRIM(value) = '' THEN 1 ELSE 0 END) AS missing_count
        FROM ableton_routing{suffix}
        GROUP BY doc_path
        """
    ).fetchall()
    for doc_path, missing_count in rows:
        missing_count = int(missing_count or 0)
        if missing_count <= 0:
            continue
        conn.execute(
            """
            INSERT OR REPLACE INTO routing_anomalies
                (scope, path, issue, issue_value, computed_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (scope, doc_path, "missing_routing_value", missing_count, now_ts),
        )


def compute_device_pair_anomalies(conn: sqlite3.Connection, scope: str) -> None:
    now_ts = int(time.time())
    conn.execute("DELETE FROM device_pair_anomalies WHERE scope = ?", (scope,))
    rows = conn.execute(
        """
        SELECT device_a, device_b, usage_count
        FROM device_cooccurrence
        WHERE scope = ? AND usage_count <= 2
        ORDER BY usage_count ASC
        """,
        (scope,),
    ).fetchall()
    for device_a, device_b, usage_count in rows:
        conn.execute(
            """
            INSERT OR REPLACE INTO device_pair_anomalies
                (scope, device_a, device_b, usage_count, computed_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (scope, device_a, device_b, int(usage_count or 0), now_ts),
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
            compute_device_cooccurrence(conn, scope)
            compute_doc_complexity(conn, scope)
            compute_library_growth(conn, scope)
            compute_missing_refs_by_path(conn, scope)
            compute_set_health(conn, scope)
            compute_audio_footprint(conn, scope)
            compute_set_storage_summary(conn, scope)
            compute_set_activity_stats(conn, scope)
            compute_set_size_top(conn, scope)
            compute_unreferenced_audio_by_path(conn, scope)
            compute_quality_issues(conn, scope)
            compute_device_usage_recent(conn, scope)
            compute_set_activity_delta(conn, scope)
            compute_set_growth_by_parent(conn, scope)
            compute_sample_duplicate_groups(conn, scope)
            compute_cold_samples(conn, scope)
            compute_routing_anomalies(conn, scope)
            compute_device_pair_anomalies(conn, scope)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
