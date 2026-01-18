#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class CatalogPaths:
    root: Path
    file_index: Path
    docs: Path
    refs: Path
    scan_state: Path


def resolve_catalog_paths(catalog_dir: Path) -> CatalogPaths:
    return CatalogPaths(
        root=catalog_dir,
        file_index=catalog_dir / "file_index.jsonl",
        docs=catalog_dir / "ableton_docs.jsonl",
        refs=catalog_dir / "refs_graph.jsonl",
        scan_state=catalog_dir / "scan_state.json",
    )


def iter_jsonl(path: Path) -> Iterable[dict]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def insert_many(conn: sqlite3.Connection, sql: str, rows: Iterable[tuple]) -> None:
    batch: list[tuple] = []
    for row in rows:
        batch.append(row)
        if len(batch) >= 1000:
            conn.executemany(sql, batch)
            batch.clear()
    if batch:
        conn.executemany(sql, batch)


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=NORMAL;

        CREATE TABLE IF NOT EXISTS file_index (
            path TEXT PRIMARY KEY,
            ext TEXT NOT NULL,
            size INTEGER NOT NULL,
            mtime INTEGER NOT NULL,
            kind TEXT NOT NULL,
            scanned_at INTEGER NOT NULL,
            sha1 TEXT,
            sha1_error TEXT
        );

        CREATE TABLE IF NOT EXISTS ableton_docs (
            path TEXT PRIMARY KEY,
            ext TEXT NOT NULL,
            kind TEXT NOT NULL,
            scanned_at INTEGER NOT NULL,
            error TEXT,
            tracks_audio INTEGER,
            tracks_midi INTEGER,
            tracks_return INTEGER,
            tracks_master INTEGER,
            tracks_total INTEGER,
            clips_audio INTEGER,
            clips_midi INTEGER,
            clips_total INTEGER
        );

        CREATE TABLE IF NOT EXISTS doc_sample_refs (
            doc_path TEXT NOT NULL,
            sample_path TEXT NOT NULL,
            scanned_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS doc_device_hints (
            doc_path TEXT NOT NULL,
            device_hint TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS refs_graph (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            src TEXT NOT NULL,
            src_kind TEXT NOT NULL,
            ref_kind TEXT NOT NULL,
            ref_path TEXT NOT NULL,
            scanned_at INTEGER NOT NULL,
            exists INTEGER
        );

        CREATE TABLE IF NOT EXISTS scan_state (
            path TEXT PRIMARY KEY,
            size INTEGER NOT NULL,
            mtime INTEGER NOT NULL,
            sha1 TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_file_index_kind ON file_index(kind);
        CREATE INDEX IF NOT EXISTS idx_file_index_ext ON file_index(ext);
        CREATE INDEX IF NOT EXISTS idx_file_index_sha1 ON file_index(sha1);
        CREATE INDEX IF NOT EXISTS idx_ableton_docs_scanned_at ON ableton_docs(scanned_at);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_doc_sample_refs ON doc_sample_refs(doc_path, sample_path);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_doc_device_hints ON doc_device_hints(doc_path, device_hint);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_refs_graph ON refs_graph(src, ref_kind, ref_path);
        CREATE INDEX IF NOT EXISTS idx_doc_sample_refs_doc_path ON doc_sample_refs(doc_path);
        CREATE INDEX IF NOT EXISTS idx_doc_sample_refs_sample_path ON doc_sample_refs(sample_path);
        CREATE INDEX IF NOT EXISTS idx_doc_device_hints_device ON doc_device_hints(device_hint);
        CREATE INDEX IF NOT EXISTS idx_refs_graph_src ON refs_graph(src);
        CREATE INDEX IF NOT EXISTS idx_refs_graph_ref_path ON refs_graph(ref_path);
        CREATE INDEX IF NOT EXISTS idx_refs_graph_ref_kind ON refs_graph(ref_kind);
        """
    )


def ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def load_file_index(conn: sqlite3.Connection, path: Path) -> None:
    if not path.exists():
        return
    insert_many(
        conn,
        """
        INSERT OR REPLACE INTO file_index
            (path, ext, size, mtime, kind, scanned_at, sha1, sha1_error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (
                rec.get("path"),
                rec.get("ext"),
                rec.get("size"),
                rec.get("mtime"),
                rec.get("kind"),
                rec.get("scanned_at"),
                rec.get("sha1"),
                rec.get("sha1_error"),
            )
            for rec in iter_jsonl(path)
        ),
    )


def load_ableton_docs(conn: sqlite3.Connection, path: Path) -> None:
    if not path.exists():
        return
    doc_rows: list[tuple] = []
    sample_rows: list[tuple] = []
    device_rows: list[tuple] = []

    def flush() -> None:
        if doc_rows:
            insert_many(
                conn,
                """
                INSERT OR REPLACE INTO ableton_docs
                    (
                        path, ext, kind, scanned_at, error,
                        tracks_audio, tracks_midi, tracks_return, tracks_master, tracks_total,
                        clips_audio, clips_midi, clips_total
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                doc_rows,
            )
            doc_rows.clear()
        if sample_rows:
            insert_many(
                conn,
                """
                INSERT OR REPLACE INTO doc_sample_refs (doc_path, sample_path, scanned_at)
                VALUES (?, ?, ?)
                """,
                sample_rows,
            )
            sample_rows.clear()
        if device_rows:
            insert_many(
                conn,
                """
                INSERT OR REPLACE INTO doc_device_hints (doc_path, device_hint)
                VALUES (?, ?)
                """,
                device_rows,
            )
            device_rows.clear()

    for rec in iter_jsonl(path):
        summary = rec.get("summary") or {}
        tracks = summary.get("tracks") or {}
        clips = summary.get("clips") or {}
        doc_rows.append(
            (
                rec.get("path"),
                rec.get("ext"),
                rec.get("kind"),
                rec.get("scanned_at"),
                rec.get("error"),
                tracks.get("audio"),
                tracks.get("midi"),
                tracks.get("return"),
                tracks.get("master"),
                tracks.get("total"),
                clips.get("audio"),
                clips.get("midi"),
                clips.get("total"),
            )
        )
        scanned_at = rec.get("scanned_at")
        for sample in summary.get("sample_refs", []) or []:
            sample_rows.append((rec.get("path"), sample, scanned_at))
        for hint in summary.get("device_hints", []) or []:
            device_rows.append((rec.get("path"), hint))

        if len(doc_rows) >= 1000 or len(sample_rows) >= 2000 or len(device_rows) >= 2000:
            flush()

    flush()


def load_refs_graph(conn: sqlite3.Connection, path: Path) -> None:
    if not path.exists():
        return
    insert_many(
        conn,
        """
        INSERT OR REPLACE INTO refs_graph
            (src, src_kind, ref_kind, ref_path, scanned_at, exists)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            (
                rec.get("src"),
                rec.get("src_kind"),
                rec.get("ref_kind"),
                rec.get("ref_path"),
                rec.get("scanned_at"),
                None if rec.get("exists") is None else int(bool(rec.get("exists"))),
            )
            for rec in iter_jsonl(path)
        ),
    )


def load_scan_state(conn: sqlite3.Connection, path: Path) -> None:
    if not path.exists():
        return
    state = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for file_path, meta in state.items():
        rows.append(
            (
                file_path,
                meta.get("size"),
                meta.get("mtime"),
                meta.get("sha1"),
            )
        )
    insert_many(
        conn,
        """
        INSERT OR REPLACE INTO scan_state (path, size, mtime, sha1)
        VALUES (?, ?, ?, ?)
        """,
        rows,
    )


def migrate_catalog(catalog: CatalogPaths, db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        create_schema(conn)
        ensure_column(conn, "refs_graph", "exists", "exists INTEGER")
        with conn:
            load_file_index(conn, catalog.file_index)
            load_ableton_docs(conn, catalog.docs)
            load_refs_graph(conn, catalog.refs)
            load_scan_state(conn, catalog.scan_state)
    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="abletools-catalog-db",
        description="Build a SQLite database from a .abletools_catalog JSONL snapshot.",
    )
    ap.add_argument(
        "catalog",
        nargs="?",
        default=".abletools_catalog",
        help="Path to the .abletools_catalog directory (default: ./.abletools_catalog)",
    )
    ap.add_argument(
        "--db",
        default=None,
        help="Output database path (default: <catalog>/abletools_catalog.sqlite)",
    )
    ap.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite the output database if it already exists.",
    )
    ap.add_argument(
        "--vacuum",
        action="store_true",
        help="Run VACUUM after migration to optimize the database.",
    )
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    catalog_dir = Path(args.catalog).expanduser().resolve()
    if not catalog_dir.exists() or not catalog_dir.is_dir():
        raise SystemExit(f"Catalog directory does not exist: {catalog_dir}")

    db_path = Path(args.db).expanduser().resolve() if args.db else catalog_dir / "abletools_catalog.sqlite"
    if db_path.exists():
        if args.overwrite:
            db_path.unlink()
        else:
            raise SystemExit(f"Database already exists: {db_path} (use --overwrite to replace)")

    catalog = resolve_catalog_paths(catalog_dir)
    migrate_catalog(catalog, db_path)

    if args.vacuum:
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("VACUUM")
        finally:
            conn.close()

    print(f"OK: catalog={catalog_dir} db={db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
