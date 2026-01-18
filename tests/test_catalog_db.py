from __future__ import annotations

import sqlite3

from abletools_catalog_db import create_schema


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_schema_has_new_columns() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        create_schema(conn)
        cols = _column_names(conn, "file_index")
        assert "path_hash" in cols
        assert "audio_duration" in cols
        assert "audio_codec" in cols
        doc_cols = _column_names(conn, "ableton_docs")
        assert "tempo" in doc_cols
    finally:
        conn.close()


def test_device_sequence_table_exists() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        create_schema(conn)
        cols = _column_names(conn, "doc_device_sequence")
        assert "device_name" in cols
    finally:
        conn.close()
