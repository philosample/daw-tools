from __future__ import annotations

import sqlite3

from abletools_analytics import (
    compute_audio_footprint,
    compute_device_chains,
    compute_missing_refs_by_path,
    compute_set_health,
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
