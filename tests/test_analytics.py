from __future__ import annotations

import sqlite3
import time

from abletools_analytics import (
    compute_audio_footprint,
    compute_device_chains,
    compute_device_usage_recent,
    compute_missing_refs_by_path,
    compute_set_health,
    compute_set_activity_stats,
    compute_set_size_top,
    compute_set_storage_summary,
    compute_quality_issues,
    compute_unreferenced_audio_by_path,
)
from abletools_catalog_db import create_schema


def test_compute_set_health() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        create_schema(conn)
        conn.execute(
            "INSERT INTO doc_complexity (scope, path, tracks_total, clips_total, devices_count, samples_count, missing_refs_count, computed_at) "
            "VALUES ('live_recordings', '/tmp/set.als', 2, 3, 5, 10, 1, 1)"
        )
        compute_set_health(conn, "live_recordings")
        row = conn.execute(
            "SELECT health_score, missing_refs_count, devices_count, samples_count FROM set_health WHERE path = ?",
            ("/tmp/set.als",),
        ).fetchone()
        assert row is not None
        score, missing, devices, samples = row
        assert missing == 1
        assert devices == 5
        assert samples == 10
        assert score < 100
    finally:
        conn.close()


def test_compute_audio_footprint() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        create_schema(conn)
        conn.execute(
            "INSERT INTO file_index (path, ext, size, mtime, kind, scanned_at) "
            "VALUES ('/tmp/a.wav', '.wav', 100, 1, 'media', 1)"
        )
        conn.execute(
            "INSERT INTO file_index (path, ext, size, mtime, kind, scanned_at) "
            "VALUES ('/tmp/b.wav', '.wav', 200, 1, 'media', 1)"
        )
        conn.execute(
            "INSERT INTO doc_sample_refs (doc_path, sample_path, scanned_at) VALUES ('/tmp/set.als', '/tmp/a.wav', 1)"
        )
        compute_audio_footprint(conn, "live_recordings")
        row = conn.execute(
            "SELECT total_media_bytes, referenced_media_bytes, unreferenced_media_bytes FROM audio_footprint WHERE scope = ?",
            ("live_recordings",),
        ).fetchone()
        assert row == (300, 100, 200)
    finally:
        conn.close()


def test_compute_missing_refs_by_path() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        create_schema(conn)
        conn.execute(
            "INSERT INTO refs_graph (src, src_kind, ref_kind, ref_path, scanned_at, ref_exists) "
            "VALUES ('/tmp/set.als', 'set', 'sample', '/Volumes/Drive/Samples/kick.wav', 1, 0)"
        )
        conn.execute(
            "INSERT INTO refs_graph (src, src_kind, ref_kind, ref_path, scanned_at, ref_exists) "
            "VALUES ('/tmp/set.als', 'set', 'sample', '/Volumes/Drive/Samples/snare.wav', 1, 0)"
        )
        compute_missing_refs_by_path(conn, "live_recordings")
        row = conn.execute(
            "SELECT missing_count FROM missing_refs_by_path WHERE ref_parent = ?",
            ("/Volumes/Drive/Samples",),
        ).fetchone()
        assert row == (2,)
    finally:
        conn.close()


def test_compute_device_chains() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        create_schema(conn)
        conn.executemany(
            "INSERT INTO doc_device_sequence (doc_path, ord, device_name) VALUES (?, ?, ?)",
            [
                ("/tmp/set.als", 0, "EQ Eight"),
                ("/tmp/set.als", 1, "Compressor"),
                ("/tmp/set.als", 2, "Reverb"),
            ],
        )
        compute_device_chains(conn, "live_recordings", 2)
        row = conn.execute(
            "SELECT usage_count FROM device_chain_stats WHERE chain = ? AND chain_len = ?",
            ("EQ Eight > Compressor", 2),
        ).fetchone()
        assert row == (1,)
    finally:
        conn.close()


def test_compute_set_storage_summary() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        create_schema(conn)
        conn.execute(
            "INSERT INTO file_index (path, ext, size, mtime, kind, scanned_at) "
            "VALUES ('Sets/A.als', '.als', 100, 1, 'ableton_doc', 1)"
        )
        conn.execute(
            "INSERT INTO file_index (path, ext, size, mtime, kind, scanned_at) "
            "VALUES ('Backup/Sets/B.als', '.als', 200, 1, 'ableton_doc', 1)"
        )
        compute_set_storage_summary(conn, "live_recordings")
        row = conn.execute(
            "SELECT total_sets, total_set_bytes, non_backup_sets, non_backup_bytes "
            "FROM set_storage_summary WHERE scope = ?",
            ("live_recordings",),
        ).fetchone()
        assert row == (2, 300, 1, 100)
    finally:
        conn.close()


def test_compute_set_activity_stats() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        create_schema(conn)
        now_ts = int(time.time())
        conn.execute(
            "INSERT INTO file_index (path, ext, size, mtime, kind, scanned_at) "
            "VALUES ('Sets/A.als', '.als', 100, ?, 'ableton_doc', 1)",
            (now_ts,),
        )
        compute_set_activity_stats(conn, "live_recordings")
        row = conn.execute(
            "SELECT set_count FROM set_activity_stats "
            "WHERE scope = ? AND window_days = 30",
            ("live_recordings",),
        ).fetchone()
        assert row == (1,)
    finally:
        conn.close()


def test_compute_set_size_top() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        create_schema(conn)
        conn.execute(
            "INSERT INTO file_index (path, ext, size, mtime, kind, scanned_at) "
            "VALUES ('Sets/A.als', '.als', 100, 1, 'ableton_doc', 1)"
        )
        conn.execute(
            "INSERT INTO file_index (path, ext, size, mtime, kind, scanned_at) "
            "VALUES ('Sets/B.als', '.als', 300, 1, 'ableton_doc', 1)"
        )
        compute_set_size_top(conn, "live_recordings", limit=1)
        row = conn.execute(
            "SELECT path, size_bytes FROM set_size_top WHERE scope = ?",
            ("live_recordings",),
        ).fetchone()
        assert row == ("Sets/B.als", 300)
    finally:
        conn.close()


def test_compute_unreferenced_audio_by_path() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        create_schema(conn)
        conn.execute(
            "INSERT INTO file_index (path, ext, size, mtime, kind, scanned_at, parent, name) "
            "VALUES ('Audio/a.wav', '.wav', 100, 1, 'media', 1, '/root/Audio', 'a.wav')"
        )
        conn.execute(
            "INSERT INTO file_index (path, ext, size, mtime, kind, scanned_at, parent, name) "
            "VALUES ('Audio/b.wav', '.wav', 200, 1, 'media', 1, '/root/Audio', 'b.wav')"
        )
        conn.execute(
            "INSERT INTO doc_sample_refs (doc_path, sample_path, scanned_at) "
            "VALUES ('Sets/A.als', '/root/Audio/a.wav', 1)"
        )
        compute_unreferenced_audio_by_path(conn, "live_recordings")
        row = conn.execute(
            "SELECT file_count, total_bytes FROM unreferenced_audio_by_path "
            "WHERE scope = ? AND parent_path = ?",
            ("live_recordings", "/root/Audio"),
        ).fetchone()
        assert row == (1, 200)
    finally:
        conn.close()


def test_compute_quality_issues() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        create_schema(conn)
        conn.execute(
            "INSERT INTO doc_complexity "
            "(scope, path, tracks_total, clips_total, devices_count, samples_count, missing_refs_count, computed_at) "
            "VALUES ('live_recordings', 'Sets/A.als', 0, 0, 2, 3, 1, 1)"
        )
        compute_quality_issues(conn, "live_recordings")
        rows = conn.execute(
            "SELECT issue FROM quality_issues WHERE scope = ? AND path = ?",
            ("live_recordings", "Sets/A.als"),
        ).fetchall()
        issues = {row[0] for row in rows}
        assert {"zero_tracks", "zero_clips", "missing_refs"}.issubset(issues)
    finally:
        conn.close()


def test_compute_device_usage_recent() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        create_schema(conn)
        now_ts = int(time.time())
        conn.execute(
            "INSERT INTO file_index (path, ext, size, mtime, kind, scanned_at) "
            "VALUES ('Sets/A.als', '.als', 100, ?, 'ableton_doc', 1)",
            (now_ts,),
        )
        conn.execute(
            "INSERT INTO doc_device_hints (doc_path, device_hint) "
            "VALUES ('Sets/A.als', 'EQ Eight')"
        )
        compute_device_usage_recent(conn, "live_recordings")
        row = conn.execute(
            "SELECT usage_count FROM device_usage_recent "
            "WHERE scope = ? AND window_days = 30 AND device_name = ?",
            ("live_recordings", "EQ Eight"),
        ).fetchone()
        assert row == (1,)
    finally:
        conn.close()
