from __future__ import annotations

import sqlite3
from pathlib import Path

from abletools_catalog_db import create_schema
from abletools_catalog_ops import (
    backup_files,
    cleanup_catalog_dir,
    prune_db_file_index,
    prune_file_index_jsonl,
)


def test_cleanup_catalog_dir(tmp_path: Path) -> None:
    catalog = tmp_path / ".abletools_catalog"
    catalog.mkdir()
    paths = [
        catalog / "scan_log_20260101_010101.txt",
        catalog / "missing_refs_audit_20260101.txt",
        catalog / "ableton_xml_nodes.jsonl",
        catalog / "refs_graph.jsonl",
        catalog / "scan_state.json",
    ]
    for path in paths:
        path.write_text("x", encoding="utf-8")

    removed, freed = cleanup_catalog_dir(
        catalog,
        {
            "logs": True,
            "xml_nodes": True,
            "device_params": False,
            "refs_graph": True,
            "struct": False,
            "scan_state": True,
        },
    )
    assert removed == 5
    assert freed > 0


def test_backup_files_zips_and_cleans(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    f1 = root / "set.als"
    f2 = root / "song.als"
    f1.write_text("data", encoding="utf-8")
    f2.write_text("data", encoding="utf-8")

    dest = tmp_path / "dest"
    copied, skipped, archive = backup_files(
        [f1, f2],
        dest,
        root,
        "sets",
        timestamp="20260101_000000",
    )
    assert copied == 2
    assert skipped == 0
    assert archive
    assert archive.exists()
    folder = dest / "Abletools Backup" / "sets_20260101_000000"
    assert not folder.exists()


def test_prune_file_index_jsonl(tmp_path: Path) -> None:
    catalog = tmp_path / ".abletools_catalog"
    catalog.mkdir()
    path = catalog / "file_index.jsonl"
    path.write_text(
        "\n".join(
            [
                "{\"path\": \"a.als\", \"ext\": \".als\"}",
                "{\"path\": \"b.wav\", \"ext\": \".wav\"}",
                "{\"path\": \"c.txt\", \"ext\": \".txt\"}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    removed, freed = prune_file_index_jsonl(catalog)
    assert removed == 1
    assert freed >= 0
    contents = path.read_text(encoding="utf-8")
    assert "\"a.als\"" in contents
    assert "\"b.wav\"" in contents
    assert "\"c.txt\"" not in contents


def test_prune_db_file_index(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.sqlite"
    conn = sqlite3.connect(db_path)
    try:
        create_schema(conn)
        conn.execute(
            "INSERT INTO file_index (path, ext, size, mtime, kind, scanned_at) "
            "VALUES ('/tmp/a.als', '.als', 1, 1, 'ableton_doc', 1)"
        )
        conn.execute(
            "INSERT INTO file_index (path, ext, size, mtime, kind, scanned_at) "
            "VALUES ('/tmp/b.txt', '.txt', 1, 1, 'other', 1)"
        )
        conn.commit()
    finally:
        conn.close()
    removed, _ = prune_db_file_index(db_path)
    assert removed == 1
    conn = sqlite3.connect(db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM file_index").fetchone()[0]
    finally:
        conn.close()
    assert count == 1
