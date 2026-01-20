#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from abletools_prefs import load_prefs_payloads, load_plugin_payloads

SCOPES = ("live_recordings", "user_library", "preferences")


def scope_suffix(scope: str) -> str:
    return "" if scope == "live_recordings" else f"_{scope}"


def scoped_name(base: str, scope: str) -> str:
    return f"{base}{scope_suffix(scope)}"


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

        CREATE TABLE IF NOT EXISTS ingest_state (
            source TEXT PRIMARY KEY,
            offset INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ableton_prefs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            source TEXT NOT NULL,
            mtime INTEGER NOT NULL,
            scanned_at INTEGER NOT NULL,
            payload_json TEXT NOT NULL
        );

        CREATE UNIQUE INDEX IF NOT EXISTS uq_ableton_prefs_source ON ableton_prefs(kind, source);
        """
    )

    for scope in SCOPES:
        suffix = scope_suffix(scope)
        conn.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS file_index{suffix} (
                path TEXT PRIMARY KEY,
                path_hash TEXT,
                ext TEXT NOT NULL,
                size INTEGER NOT NULL,
                mtime INTEGER NOT NULL,
                ctime INTEGER,
                atime INTEGER,
                inode INTEGER,
                device INTEGER,
                mode INTEGER,
                uid INTEGER,
                gid INTEGER,
                is_symlink INTEGER,
                symlink_target TEXT,
                name TEXT,
                parent TEXT,
                mime TEXT,
                kind TEXT NOT NULL,
                scanned_at INTEGER NOT NULL,
                sha1 TEXT,
                sha1_error TEXT,
                audio_duration REAL,
                audio_sample_rate INTEGER,
                audio_channels INTEGER,
                audio_bit_depth INTEGER,
                audio_codec TEXT
            );

            CREATE TABLE IF NOT EXISTS ableton_docs{suffix} (
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
                clips_total INTEGER,
                tempo REAL
            );

            CREATE TABLE IF NOT EXISTS ableton_struct_meta{suffix} (
                doc_path TEXT PRIMARY KEY,
                parse_method TEXT,
                error TEXT
            );

            CREATE TABLE IF NOT EXISTS ableton_tracks{suffix} (
                doc_path TEXT NOT NULL,
                track_index INTEGER NOT NULL,
                track_type TEXT,
                name TEXT,
                is_group INTEGER,
                is_folded INTEGER,
                meta_json TEXT,
                PRIMARY KEY (doc_path, track_index)
            );

            CREATE TABLE IF NOT EXISTS ableton_clips{suffix} (
                doc_path TEXT NOT NULL,
                clip_index INTEGER NOT NULL,
                track_index INTEGER,
                clip_type TEXT,
                name TEXT,
                length REAL,
                meta_json TEXT,
                PRIMARY KEY (doc_path, clip_index)
            );

            CREATE TABLE IF NOT EXISTS ableton_devices{suffix} (
                doc_path TEXT NOT NULL,
                device_index INTEGER NOT NULL,
                track_index INTEGER,
                device_type TEXT,
                name TEXT,
                meta_json TEXT,
                PRIMARY KEY (doc_path, device_index)
            );

            CREATE TABLE IF NOT EXISTS ableton_routing{suffix} (
                doc_path TEXT NOT NULL,
                track_index INTEGER,
                direction TEXT,
                value TEXT,
                meta_json TEXT
            );

            CREATE TABLE IF NOT EXISTS ableton_clip_details{suffix} (
                doc_path TEXT NOT NULL,
                clip_index INTEGER NOT NULL,
                track_index INTEGER,
                clip_type TEXT,
                name TEXT,
                details_json TEXT,
                PRIMARY KEY (doc_path, clip_index)
            );

            CREATE TABLE IF NOT EXISTS ableton_device_params{suffix} (
                doc_path TEXT NOT NULL,
                device_index INTEGER NOT NULL,
                track_index INTEGER,
                param_type TEXT,
                name TEXT,
                param_json TEXT,
                PRIMARY KEY (doc_path, device_index, name)
            );

            CREATE TABLE IF NOT EXISTS ableton_routing_details{suffix} (
                doc_path TEXT NOT NULL,
                track_index INTEGER,
                direction TEXT,
                value TEXT,
                meta_json TEXT
            );

            CREATE TABLE IF NOT EXISTS ableton_xml_nodes{suffix} (
                doc_path TEXT NOT NULL,
                ord INTEGER NOT NULL,
                depth INTEGER,
                tag TEXT,
                path_tag TEXT,
                attrs_json TEXT,
                text TEXT,
                text_len INTEGER,
                text_truncated INTEGER,
                PRIMARY KEY (doc_path, ord)
            );

            CREATE TABLE IF NOT EXISTS doc_sample_refs{suffix} (
                doc_path TEXT NOT NULL,
                sample_path TEXT NOT NULL,
                scanned_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS doc_device_hints{suffix} (
                doc_path TEXT NOT NULL,
                device_hint TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS doc_device_sequence{suffix} (
                doc_path TEXT NOT NULL,
                ord INTEGER NOT NULL,
                device_name TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS refs_graph{suffix} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                src TEXT NOT NULL,
                src_kind TEXT NOT NULL,
                ref_kind TEXT NOT NULL,
                ref_path TEXT NOT NULL,
                scanned_at INTEGER NOT NULL,
                ref_exists INTEGER
            );

            CREATE TABLE IF NOT EXISTS scan_state{suffix} (
                path TEXT PRIMARY KEY,
                size INTEGER NOT NULL,
                mtime INTEGER NOT NULL,
                ctime INTEGER,
                sha1 TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_file_index_kind{suffix} ON file_index{suffix}(kind);
            CREATE INDEX IF NOT EXISTS idx_file_index_ext{suffix} ON file_index{suffix}(ext);
            CREATE INDEX IF NOT EXISTS idx_file_index_sha1{suffix} ON file_index{suffix}(sha1);
            CREATE INDEX IF NOT EXISTS idx_ableton_docs_scanned_at{suffix} ON ableton_docs{suffix}(scanned_at);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_doc_sample_refs{suffix} ON doc_sample_refs{suffix}(doc_path, sample_path);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_doc_device_hints{suffix} ON doc_device_hints{suffix}(doc_path, device_hint);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_doc_device_sequence{suffix} ON doc_device_sequence{suffix}(doc_path, ord, device_name);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_refs_graph{suffix} ON refs_graph{suffix}(src, ref_kind, ref_path);
            CREATE INDEX IF NOT EXISTS idx_doc_sample_refs_doc_path{suffix} ON doc_sample_refs{suffix}(doc_path);
            CREATE INDEX IF NOT EXISTS idx_doc_sample_refs_sample_path{suffix} ON doc_sample_refs{suffix}(sample_path);
            CREATE INDEX IF NOT EXISTS idx_doc_device_hints_device{suffix} ON doc_device_hints{suffix}(device_hint);
            CREATE INDEX IF NOT EXISTS idx_doc_device_sequence_doc{suffix} ON doc_device_sequence{suffix}(doc_path);
            CREATE INDEX IF NOT EXISTS idx_doc_device_sequence_name{suffix} ON doc_device_sequence{suffix}(device_name);
            CREATE INDEX IF NOT EXISTS idx_refs_graph_src{suffix} ON refs_graph{suffix}(src);
            CREATE INDEX IF NOT EXISTS idx_refs_graph_ref_path{suffix} ON refs_graph{suffix}(ref_path);
            CREATE INDEX IF NOT EXISTS idx_refs_graph_ref_kind{suffix} ON refs_graph{suffix}(ref_kind);
            CREATE INDEX IF NOT EXISTS idx_ableton_tracks_name{suffix} ON ableton_tracks{suffix}(name);
            CREATE INDEX IF NOT EXISTS idx_ableton_clips_name{suffix} ON ableton_clips{suffix}(name);
            CREATE INDEX IF NOT EXISTS idx_ableton_devices_name{suffix} ON ableton_devices{suffix}(name);
            CREATE INDEX IF NOT EXISTS idx_ableton_tracks_doc{suffix} ON ableton_tracks{suffix}(doc_path);
            CREATE INDEX IF NOT EXISTS idx_ableton_clips_doc{suffix} ON ableton_clips{suffix}(doc_path);
            CREATE INDEX IF NOT EXISTS idx_ableton_devices_doc{suffix} ON ableton_devices{suffix}(doc_path);
            CREATE INDEX IF NOT EXISTS idx_ableton_routing_doc{suffix} ON ableton_routing{suffix}(doc_path);
            CREATE INDEX IF NOT EXISTS idx_ableton_clip_details_doc{suffix} ON ableton_clip_details{suffix}(doc_path);
            CREATE INDEX IF NOT EXISTS idx_ableton_device_params_doc{suffix} ON ableton_device_params{suffix}(doc_path);
            CREATE INDEX IF NOT EXISTS idx_ableton_routing_details_doc{suffix} ON ableton_routing_details{suffix}(doc_path);
            CREATE INDEX IF NOT EXISTS idx_ableton_xml_nodes_doc{suffix} ON ableton_xml_nodes{suffix}(doc_path);
            CREATE INDEX IF NOT EXISTS idx_ableton_xml_nodes_tag{suffix} ON ableton_xml_nodes{suffix}(tag);
            """
        )

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS audio_analysis (
            scope TEXT NOT NULL,
            path TEXT NOT NULL,
            duration_sec REAL,
            sample_rate INTEGER,
            channels INTEGER,
            bit_depth INTEGER,
            codec TEXT,
            scanned_at INTEGER NOT NULL,
            PRIMARY KEY (scope, path)
        );

        CREATE TABLE IF NOT EXISTS plugin_index (
            scope TEXT NOT NULL,
            path TEXT NOT NULL,
            name TEXT,
            vendor TEXT,
            version TEXT,
            format TEXT,
            bundle_id TEXT,
            scanned_at INTEGER NOT NULL,
            PRIMARY KEY (scope, path)
        );

        CREATE TABLE IF NOT EXISTS catalog_docs (
            scope TEXT NOT NULL,
            path TEXT NOT NULL,
            ext TEXT,
            size INTEGER,
            mtime INTEGER,
            tracks_total INTEGER,
            clips_total INTEGER,
            has_devices INTEGER,
            has_samples INTEGER,
            missing_refs INTEGER,
            scanned_at INTEGER NOT NULL,
            PRIMARY KEY (scope, path)
        );

        CREATE TABLE IF NOT EXISTS device_usage (
            scope TEXT NOT NULL,
            device_name TEXT NOT NULL,
            usage_count INTEGER NOT NULL,
            computed_at INTEGER NOT NULL,
            PRIMARY KEY (scope, device_name)
        );

        CREATE TABLE IF NOT EXISTS device_chain_stats (
            scope TEXT NOT NULL,
            chain TEXT NOT NULL,
            chain_len INTEGER NOT NULL,
            usage_count INTEGER NOT NULL,
            computed_at INTEGER NOT NULL,
            PRIMARY KEY (scope, chain)
        );

        CREATE TABLE IF NOT EXISTS device_cooccurrence (
            scope TEXT NOT NULL,
            device_a TEXT NOT NULL,
            device_b TEXT NOT NULL,
            usage_count INTEGER NOT NULL,
            computed_at INTEGER NOT NULL,
            PRIMARY KEY (scope, device_a, device_b)
        );

        CREATE TABLE IF NOT EXISTS doc_complexity (
            scope TEXT NOT NULL,
            path TEXT NOT NULL,
            tracks_total INTEGER,
            clips_total INTEGER,
            devices_count INTEGER,
            samples_count INTEGER,
            missing_refs_count INTEGER,
            computed_at INTEGER NOT NULL,
            PRIMARY KEY (scope, path)
        );

        CREATE TABLE IF NOT EXISTS library_growth (
            scope TEXT NOT NULL,
            snapshot_at INTEGER NOT NULL,
            file_count INTEGER NOT NULL,
            total_bytes INTEGER NOT NULL,
            media_bytes INTEGER NOT NULL,
            doc_count INTEGER NOT NULL,
            PRIMARY KEY (scope, snapshot_at)
        );

        CREATE TABLE IF NOT EXISTS missing_refs_by_path (
            scope TEXT NOT NULL,
            ref_parent TEXT NOT NULL,
            missing_count INTEGER NOT NULL,
            computed_at INTEGER NOT NULL,
            PRIMARY KEY (scope, ref_parent)
        );

        CREATE TABLE IF NOT EXISTS set_health (
            scope TEXT NOT NULL,
            path TEXT NOT NULL,
            tracks_total INTEGER,
            clips_total INTEGER,
            devices_count INTEGER,
            samples_count INTEGER,
            missing_refs_count INTEGER,
            health_score REAL NOT NULL,
            computed_at INTEGER NOT NULL,
            PRIMARY KEY (scope, path)
        );

        CREATE TABLE IF NOT EXISTS audio_footprint (
            scope TEXT NOT NULL,
            total_media_bytes INTEGER NOT NULL,
            referenced_media_bytes INTEGER NOT NULL,
            unreferenced_media_bytes INTEGER NOT NULL,
            computed_at INTEGER NOT NULL,
            PRIMARY KEY (scope)
        );

        CREATE TABLE IF NOT EXISTS set_storage_summary (
            scope TEXT NOT NULL,
            total_sets INTEGER NOT NULL,
            total_set_bytes INTEGER NOT NULL,
            non_backup_sets INTEGER NOT NULL,
            non_backup_bytes INTEGER NOT NULL,
            computed_at INTEGER NOT NULL,
            PRIMARY KEY (scope)
        );

        CREATE TABLE IF NOT EXISTS set_activity_stats (
            scope TEXT NOT NULL,
            window_days INTEGER NOT NULL,
            set_count INTEGER NOT NULL,
            total_bytes INTEGER NOT NULL,
            computed_at INTEGER NOT NULL,
            PRIMARY KEY (scope, window_days)
        );

        CREATE TABLE IF NOT EXISTS set_size_top (
            scope TEXT NOT NULL,
            path TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            mtime INTEGER NOT NULL,
            computed_at INTEGER NOT NULL,
            PRIMARY KEY (scope, path)
        );

        CREATE TABLE IF NOT EXISTS unreferenced_audio_by_path (
            scope TEXT NOT NULL,
            parent_path TEXT NOT NULL,
            file_count INTEGER NOT NULL,
            total_bytes INTEGER NOT NULL,
            computed_at INTEGER NOT NULL,
            PRIMARY KEY (scope, parent_path)
        );

        CREATE TABLE IF NOT EXISTS quality_issues (
            scope TEXT NOT NULL,
            path TEXT NOT NULL,
            issue TEXT NOT NULL,
            issue_value INTEGER NOT NULL,
            computed_at INTEGER NOT NULL,
            PRIMARY KEY (scope, path, issue)
        );

        CREATE TABLE IF NOT EXISTS device_usage_recent (
            scope TEXT NOT NULL,
            window_days INTEGER NOT NULL,
            device_name TEXT NOT NULL,
            usage_count INTEGER NOT NULL,
            computed_at INTEGER NOT NULL,
            PRIMARY KEY (scope, window_days, device_name)
        );

        CREATE INDEX IF NOT EXISTS idx_catalog_docs_scope ON catalog_docs(scope);
        CREATE INDEX IF NOT EXISTS idx_catalog_docs_missing ON catalog_docs(missing_refs);
        CREATE INDEX IF NOT EXISTS idx_catalog_docs_devices ON catalog_docs(has_devices);
        CREATE INDEX IF NOT EXISTS idx_catalog_docs_samples ON catalog_docs(has_samples);
        CREATE INDEX IF NOT EXISTS idx_device_cooccurrence_count ON device_cooccurrence(usage_count);
        CREATE INDEX IF NOT EXISTS idx_library_growth_scope ON library_growth(scope);
        CREATE INDEX IF NOT EXISTS idx_missing_refs_scope ON missing_refs_by_path(scope);
        CREATE INDEX IF NOT EXISTS idx_set_health_scope ON set_health(scope);
        CREATE INDEX IF NOT EXISTS idx_audio_footprint_scope ON audio_footprint(scope);
        CREATE INDEX IF NOT EXISTS idx_set_storage_summary_scope ON set_storage_summary(scope);
        CREATE INDEX IF NOT EXISTS idx_set_activity_stats_scope ON set_activity_stats(scope);
        CREATE INDEX IF NOT EXISTS idx_set_size_top_scope ON set_size_top(scope);
        CREATE INDEX IF NOT EXISTS idx_unreferenced_audio_by_path_scope ON unreferenced_audio_by_path(scope);
        CREATE INDEX IF NOT EXISTS idx_quality_issues_scope ON quality_issues(scope);
        CREATE INDEX IF NOT EXISTS idx_device_usage_recent_scope ON device_usage_recent(scope);
        """
    )


def get_ingest_offset(conn: sqlite3.Connection, source: str) -> int:
    row = conn.execute(
        "SELECT offset FROM ingest_state WHERE source = ?", (source,)
    ).fetchone()
    return int(row[0]) if row else 0


def set_ingest_offset(conn: sqlite3.Connection, source: str, offset: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO ingest_state (source, offset) VALUES (?, ?)",
        (source, int(offset)),
    )


def read_jsonl_incremental(
    path: Path, start_offset: int, on_record: Callable[[dict], None]
) -> int:
    size = path.stat().st_size
    if start_offset > size:
        print(f"WARN: {path} offset beyond EOF; resetting to 0.")
        start_offset = 0
    with path.open("rb") as handle:
        if start_offset > 0:
            handle.seek(start_offset)
            handle.readline()
        while True:
            line = handle.readline()
            if not line:
                break
            start_offset = handle.tell()
            line = line.strip()
            if not line:
                continue
            on_record(json.loads(line.decode("utf-8")))
    return start_offset


def ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def ensure_file_index_columns(conn: sqlite3.Connection, table: str) -> None:
    columns = {
        "path_hash": "path_hash TEXT",
        "ctime": "ctime INTEGER",
        "atime": "atime INTEGER",
        "inode": "inode INTEGER",
        "device": "device INTEGER",
        "mode": "mode INTEGER",
        "uid": "uid INTEGER",
        "gid": "gid INTEGER",
        "is_symlink": "is_symlink INTEGER",
        "symlink_target": "symlink_target TEXT",
        "name": "name TEXT",
        "parent": "parent TEXT",
        "mime": "mime TEXT",
        "audio_duration": "audio_duration REAL",
        "audio_sample_rate": "audio_sample_rate INTEGER",
        "audio_channels": "audio_channels INTEGER",
        "audio_bit_depth": "audio_bit_depth INTEGER",
        "audio_codec": "audio_codec TEXT",
    }
    for col, ddl in columns.items():
        ensure_column(conn, table, col, ddl)
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_path_hash ON {table}(path_hash)")


def ensure_ableton_docs_columns(conn: sqlite3.Connection, table: str) -> None:
    ensure_column(conn, table, "tempo", "tempo REAL")


def ensure_ableton_struct_columns(conn: sqlite3.Connection, scope: str) -> None:
    suffix = scope_suffix(scope)
    ensure_column(conn, f"ableton_tracks{suffix}", "meta_json", "meta_json TEXT")
    ensure_column(conn, f"ableton_clips{suffix}", "meta_json", "meta_json TEXT")
    ensure_column(conn, f"ableton_devices{suffix}", "meta_json", "meta_json TEXT")
    ensure_column(conn, f"ableton_routing{suffix}", "meta_json", "meta_json TEXT")


def load_file_index(
    conn: sqlite3.Connection, path: Path, incremental: bool, table: str
) -> None:
    if not path.exists():
        return
    start_offset = get_ingest_offset(conn, table) if incremental else 0
    rows: list[tuple] = []

    def on_record(rec: dict) -> None:
        rows.append(
            (
                rec.get("path"),
                rec.get("path_hash"),
                rec.get("ext"),
                rec.get("size"),
                rec.get("mtime"),
                rec.get("ctime"),
                rec.get("atime"),
                rec.get("inode"),
                rec.get("device"),
                rec.get("mode"),
                rec.get("uid"),
                rec.get("gid"),
                None if rec.get("is_symlink") is None else int(bool(rec.get("is_symlink"))),
                rec.get("symlink_target"),
                rec.get("name"),
                rec.get("parent"),
                rec.get("mime"),
                rec.get("kind"),
                rec.get("scanned_at"),
                rec.get("sha1"),
                rec.get("sha1_error"),
                rec.get("audio_duration"),
                rec.get("audio_sample_rate"),
                rec.get("audio_channels"),
                rec.get("audio_bit_depth"),
                rec.get("audio_codec"),
            )
        )
        if len(rows) >= 1000:
            insert_many(
                conn,
                f"""
                INSERT OR REPLACE INTO {table}
                    (
                        path, path_hash, ext, size, mtime,
                        ctime, atime, inode, device, mode, uid, gid, is_symlink, symlink_target,
                        name, parent, mime,
                        kind, scanned_at, sha1, sha1_error,
                        audio_duration, audio_sample_rate, audio_channels, audio_bit_depth, audio_codec
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            rows.clear()

    end_offset = (
        read_jsonl_incremental(path, start_offset, on_record)
        if incremental
        else read_jsonl_incremental(path, 0, on_record)
    )
    if rows:
        insert_many(
            conn,
            f"""
            INSERT OR REPLACE INTO {table}
                (
                    path, path_hash, ext, size, mtime,
                    ctime, atime, inode, device, mode, uid, gid, is_symlink, symlink_target,
                    name, parent, mime,
                    kind, scanned_at, sha1, sha1_error,
                    audio_duration, audio_sample_rate, audio_channels, audio_bit_depth, audio_codec
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    set_ingest_offset(conn, table, end_offset)


def load_ableton_docs(
    conn: sqlite3.Connection, path: Path, incremental: bool, table: str
) -> None:
    if not path.exists():
        return
    start_offset = get_ingest_offset(conn, table) if incremental else 0
    doc_rows: list[tuple] = []
    sample_rows: list[tuple] = []
    device_rows: list[tuple] = []
    sequence_rows: list[tuple] = []

    def flush() -> None:
        if doc_rows:
            insert_many(
                conn,
                f"""
                INSERT OR REPLACE INTO {table}
                    (
                        path, ext, kind, scanned_at, error,
                        tracks_audio, tracks_midi, tracks_return, tracks_master, tracks_total,
                        clips_audio, clips_midi, clips_total,
                        tempo
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                doc_rows,
            )
            doc_rows.clear()
        if sample_rows:
            insert_many(
                conn,
                f"""
                INSERT OR REPLACE INTO {table.replace('ableton_docs', 'doc_sample_refs')}
                    (doc_path, sample_path, scanned_at)
                VALUES (?, ?, ?)
                """,
                sample_rows,
            )
            sample_rows.clear()
        if device_rows:
            insert_many(
                conn,
                f"""
                INSERT OR REPLACE INTO {table.replace('ableton_docs', 'doc_device_hints')}
                    (doc_path, device_hint)
                VALUES (?, ?)
                """,
                device_rows,
            )
            device_rows.clear()
        if sequence_rows:
            insert_many(
                conn,
                f"""
                INSERT OR REPLACE INTO {table.replace('ableton_docs', 'doc_device_sequence')}
                    (doc_path, ord, device_name)
                VALUES (?, ?, ?)
                """,
                sequence_rows,
            )
            sequence_rows.clear()

    def on_record(rec: dict) -> None:
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
                summary.get("tempo"),
            )
        )
        scanned_at = rec.get("scanned_at")
        for sample in summary.get("sample_refs", []) or []:
            sample_rows.append((rec.get("path"), sample, scanned_at))
        for hint in summary.get("device_hints", []) or []:
            device_rows.append((rec.get("path"), hint))
        for idx, name in enumerate(summary.get("device_sequence", []) or []):
            sequence_rows.append((rec.get("path"), idx, name))

        if (
            len(doc_rows) >= 1000
            or len(sample_rows) >= 2000
            or len(device_rows) >= 2000
            or len(sequence_rows) >= 2000
        ):
            flush()

    end_offset = (
        read_jsonl_incremental(path, start_offset, on_record)
        if incremental
        else read_jsonl_incremental(path, 0, on_record)
    )
    flush()
    set_ingest_offset(conn, table, end_offset)


def load_ableton_struct(
    conn: sqlite3.Connection, path: Path, incremental: bool, scope: str
) -> None:
    if not path.exists():
        return
    suffix = scope_suffix(scope)
    source = f"ableton_struct{suffix}"
    start_offset = get_ingest_offset(conn, source) if incremental else 0

    def on_record(rec: dict) -> None:
        doc_path = rec.get("path")
        if not doc_path:
            return
        conn.execute(
            f"INSERT OR REPLACE INTO ableton_struct_meta{suffix} (doc_path, parse_method, error) "
            f"VALUES (?, ?, ?)",
            (doc_path, rec.get("parse_method"), rec.get("error")),
        )
        conn.execute(f"DELETE FROM ableton_tracks{suffix} WHERE doc_path = ?", (doc_path,))
        conn.execute(f"DELETE FROM ableton_clips{suffix} WHERE doc_path = ?", (doc_path,))
        conn.execute(f"DELETE FROM ableton_devices{suffix} WHERE doc_path = ?", (doc_path,))
        conn.execute(f"DELETE FROM ableton_routing{suffix} WHERE doc_path = ?", (doc_path,))

        track_rows = []
        for track in rec.get("tracks", []) or []:
            track_rows.append(
                (
                    doc_path,
                    track.get("index"),
                    track.get("type"),
                    track.get("name"),
                    1 if track.get("is_group") else 0,
                    1 if track.get("is_folded") else 0,
                    json.dumps(track.get("meta") or {}),
                )
            )
        if track_rows:
            insert_many(
                conn,
                f"""
                INSERT OR REPLACE INTO ableton_tracks{suffix}
                    (doc_path, track_index, track_type, name, is_group, is_folded, meta_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                track_rows,
            )

        clip_rows = []
        for clip in rec.get("clips", []) or []:
            clip_rows.append(
                (
                    doc_path,
                    clip.get("index"),
                    clip.get("track_index"),
                    clip.get("type"),
                    clip.get("name"),
                    clip.get("length"),
                    json.dumps(clip.get("meta") or {}),
                )
            )
        if clip_rows:
            insert_many(
                conn,
                f"""
                INSERT OR REPLACE INTO ableton_clips{suffix}
                    (doc_path, clip_index, track_index, clip_type, name, length, meta_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                clip_rows,
            )

        device_rows = []
        for device in rec.get("devices", []) or []:
            device_rows.append(
                (
                    doc_path,
                    device.get("index"),
                    device.get("track_index"),
                    device.get("type"),
                    device.get("name"),
                    json.dumps(device.get("meta") or {}),
                )
            )
        if device_rows:
            insert_many(
                conn,
                f"""
                INSERT OR REPLACE INTO ableton_devices{suffix}
                    (doc_path, device_index, track_index, device_type, name, meta_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                device_rows,
            )

        routing_rows = []
        for routing in rec.get("routings", []) or []:
            routing_rows.append(
                (
                    doc_path,
                    routing.get("track_index"),
                    routing.get("direction"),
                    routing.get("value"),
                    json.dumps(routing.get("meta") or {}),
                )
            )
        if routing_rows:
            insert_many(
                conn,
                f"""
                INSERT INTO ableton_routing{suffix}
                    (doc_path, track_index, direction, value, meta_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                routing_rows,
            )

    end_offset = (
        read_jsonl_incremental(path, start_offset, on_record)
        if incremental
        else read_jsonl_incremental(path, 0, on_record)
    )
    set_ingest_offset(conn, source, end_offset)


def load_ableton_xml_nodes(
    conn: sqlite3.Connection, path: Path, incremental: bool, scope: str
) -> None:
    if not path.exists():
        return
    suffix = scope_suffix(scope)
    source = f"ableton_xml_nodes{suffix}"
    start_offset = get_ingest_offset(conn, source) if incremental else 0
    rows: list[tuple] = []

    def flush() -> None:
        if not rows:
            return
        insert_many(
            conn,
            f"""
            INSERT OR REPLACE INTO ableton_xml_nodes{suffix}
                (doc_path, ord, depth, tag, path_tag, attrs_json, text, text_len, text_truncated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        rows.clear()

    def on_record(rec: dict) -> None:
        rows.append(
            (
                rec.get("path"),
                rec.get("ord"),
                rec.get("depth"),
                rec.get("tag"),
                rec.get("path_tag"),
                json.dumps(rec.get("attrs") or {}),
                rec.get("text"),
                rec.get("text_len"),
                1 if rec.get("text_truncated") else 0,
            )
        )
        if len(rows) >= 1000:
            flush()

    end_offset = (
        read_jsonl_incremental(path, start_offset, on_record)
        if incremental
        else read_jsonl_incremental(path, 0, on_record)
    )
    flush()
    set_ingest_offset(conn, source, end_offset)


def load_ableton_clip_details(
    conn: sqlite3.Connection, path: Path, incremental: bool, scope: str
) -> None:
    if not path.exists():
        return
    suffix = scope_suffix(scope)
    source = f"ableton_clip_details{suffix}"
    start_offset = get_ingest_offset(conn, source) if incremental else 0
    rows: list[tuple] = []

    def flush() -> None:
        if not rows:
            return
        insert_many(
            conn,
            f"""
            INSERT OR REPLACE INTO ableton_clip_details{suffix}
                (doc_path, clip_index, track_index, clip_type, name, details_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        rows.clear()

    def on_record(rec: dict) -> None:
        rows.append(
            (
                rec.get("path"),
                rec.get("clip_index"),
                rec.get("track_index"),
                rec.get("clip_type"),
                rec.get("name"),
                json.dumps(rec.get("details") or {}),
            )
        )
        if len(rows) >= 1000:
            flush()

    end_offset = (
        read_jsonl_incremental(path, start_offset, on_record)
        if incremental
        else read_jsonl_incremental(path, 0, on_record)
    )
    flush()
    set_ingest_offset(conn, source, end_offset)


def load_ableton_device_params(
    conn: sqlite3.Connection, path: Path, incremental: bool, scope: str
) -> None:
    if not path.exists():
        return
    suffix = scope_suffix(scope)
    source = f"ableton_device_params{suffix}"
    start_offset = get_ingest_offset(conn, source) if incremental else 0
    rows: list[tuple] = []

    def flush() -> None:
        if not rows:
            return
        insert_many(
            conn,
            f"""
            INSERT OR REPLACE INTO ableton_device_params{suffix}
                (doc_path, device_index, track_index, param_type, name, param_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        rows.clear()

    def on_record(rec: dict) -> None:
        rows.append(
            (
                rec.get("path"),
                rec.get("device_index"),
                rec.get("track_index"),
                rec.get("param_type"),
                rec.get("name"),
                json.dumps(rec.get("param") or {}),
            )
        )
        if len(rows) >= 1000:
            flush()

    end_offset = (
        read_jsonl_incremental(path, start_offset, on_record)
        if incremental
        else read_jsonl_incremental(path, 0, on_record)
    )
    flush()
    set_ingest_offset(conn, source, end_offset)


def load_ableton_routing_details(
    conn: sqlite3.Connection, path: Path, incremental: bool, scope: str
) -> None:
    if not path.exists():
        return
    suffix = scope_suffix(scope)
    source = f"ableton_routing_details{suffix}"
    start_offset = get_ingest_offset(conn, source) if incremental else 0
    rows: list[tuple] = []

    def flush() -> None:
        if not rows:
            return
        insert_many(
            conn,
            f"""
            INSERT OR REPLACE INTO ableton_routing_details{suffix}
                (doc_path, track_index, direction, value, meta_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )
        rows.clear()

    def on_record(rec: dict) -> None:
        rows.append(
            (
                rec.get("path"),
                rec.get("track_index"),
                rec.get("direction"),
                rec.get("value"),
                json.dumps(rec.get("meta") or {}),
            )
        )
        if len(rows) >= 1000:
            flush()

    end_offset = (
        read_jsonl_incremental(path, start_offset, on_record)
        if incremental
        else read_jsonl_incremental(path, 0, on_record)
    )
    flush()
    set_ingest_offset(conn, source, end_offset)


def load_refs_graph(
    conn: sqlite3.Connection, path: Path, incremental: bool, table: str
) -> None:
    if not path.exists():
        return
    start_offset = get_ingest_offset(conn, table) if incremental else 0
    rows: list[tuple] = []

    def on_record(rec: dict) -> None:
        rows.append(
            (
                rec.get("src"),
                rec.get("src_kind"),
                rec.get("ref_kind"),
                rec.get("ref_path"),
                rec.get("scanned_at"),
                None if rec.get("exists") is None else int(bool(rec.get("exists"))),
            )
        )
        if len(rows) >= 1000:
            insert_many(
                conn,
                f"""
                INSERT OR REPLACE INTO {table}
                    (src, src_kind, ref_kind, ref_path, scanned_at, ref_exists)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            rows.clear()

    end_offset = (
        read_jsonl_incremental(path, start_offset, on_record)
        if incremental
        else read_jsonl_incremental(path, 0, on_record)
    )
    if rows:
        insert_many(
            conn,
            f"""
            INSERT OR REPLACE INTO {table}
                (src, src_kind, ref_kind, ref_path, scanned_at, ref_exists)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    set_ingest_offset(conn, table, end_offset)


def load_scan_state(conn: sqlite3.Connection, path: Path, table: str) -> None:
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
                meta.get("ctime"),
                meta.get("sha1"),
            )
        )
    insert_many(
        conn,
        f"""
        INSERT OR REPLACE INTO {table} (path, size, mtime, ctime, sha1)
        VALUES (?, ?, ?, ?, ?)
        """,
        rows,
    )


def load_audio_analysis(
    conn: sqlite3.Connection, file_index_table: str, scope: str
) -> None:
    conn.execute(
        f"""
        INSERT OR REPLACE INTO audio_analysis
            (scope, path, duration_sec, sample_rate, channels, bit_depth, codec, scanned_at)
        SELECT
            ?,
            path,
            audio_duration,
            audio_sample_rate,
            audio_channels,
            audio_bit_depth,
            audio_codec,
            scanned_at
        FROM {file_index_table}
        WHERE audio_duration IS NOT NULL
           OR audio_sample_rate IS NOT NULL
           OR audio_channels IS NOT NULL
           OR audio_bit_depth IS NOT NULL
        """,
        (scope,),
    )


def refresh_catalog_docs(conn: sqlite3.Connection, scope: str) -> None:
    suffix = scope_suffix(scope)
    conn.execute("DELETE FROM catalog_docs WHERE scope = ?", (scope,))
    conn.execute(
        f"""
        INSERT OR REPLACE INTO catalog_docs
            (scope, path, ext, size, mtime, tracks_total, clips_total,
             has_devices, has_samples, missing_refs, scanned_at)
        SELECT
            ?,
            d.path,
            f.ext,
            f.size,
            f.mtime,
            d.tracks_total,
            d.clips_total,
            EXISTS(SELECT 1 FROM doc_device_hints{suffix} dh WHERE dh.doc_path = d.path),
            EXISTS(SELECT 1 FROM doc_sample_refs{suffix} ds WHERE ds.doc_path = d.path),
            EXISTS(SELECT 1 FROM refs_graph{suffix} rg WHERE rg.src = d.path AND rg.ref_exists = 0),
            d.scanned_at
        FROM ableton_docs{suffix} d
        LEFT JOIN file_index{suffix} f ON f.path = d.path
        """,
        (scope,),
    )


def load_ableton_prefs(conn: sqlite3.Connection, cache_dir: Path) -> None:
    payloads = load_prefs_payloads(cache_dir)
    for entry in payloads:
        row = conn.execute(
            "SELECT mtime FROM ableton_prefs WHERE kind = ? AND source = ?",
            (entry["kind"], entry["source"]),
        ).fetchone()
        if row and int(row[0]) == int(entry["mtime"]):
            continue
        conn.execute(
            """
            INSERT OR REPLACE INTO ableton_prefs
                (kind, source, mtime, scanned_at, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                entry["kind"],
                entry["source"],
                int(entry["mtime"]),
                int(entry["scanned_at"]),
                json.dumps(entry["payload"]),
            ),
        )


def load_plugin_index(conn: sqlite3.Connection, cache_dir: Path) -> None:
    payloads = load_plugin_payloads(cache_dir)
    for entry in payloads:
        scope = entry.get("scope", "preferences")
        for plugin in entry.get("plugins", []):
            conn.execute(
                """
                INSERT OR REPLACE INTO plugin_index
                    (scope, path, name, vendor, version, format, bundle_id, scanned_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scope,
                    plugin.get("path"),
                    plugin.get("name"),
                    plugin.get("vendor"),
                    plugin.get("version"),
                    plugin.get("format"),
                    plugin.get("bundle_id"),
                    entry.get("scanned_at"),
                ),
            )


def migrate_catalog(catalog: CatalogPaths, db_path: Path, incremental: bool) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-200000")
        create_schema(conn)
        for scope in SCOPES:
            suffix = scope_suffix(scope)
            file_index_table = scoped_name("file_index", scope)
            docs_table = scoped_name("ableton_docs", scope)
            refs_table = scoped_name("refs_graph", scope)
            scan_state_table = scoped_name("scan_state", scope)

            ensure_file_index_columns(conn, file_index_table)
            ensure_ableton_docs_columns(conn, docs_table)
            ensure_ableton_struct_columns(conn, scope)
            ensure_column(conn, refs_table, "ref_exists", "ref_exists INTEGER")
            ensure_column(conn, scan_state_table, "ctime", "ctime INTEGER")

            file_index_path = catalog.root / f"file_index{suffix}.jsonl"
            docs_path = catalog.root / f"ableton_docs{suffix}.jsonl"
            struct_path = catalog.root / f"ableton_struct{suffix}.jsonl"
            xml_nodes_path = catalog.root / f"ableton_xml_nodes{suffix}.jsonl"
            clip_details_path = catalog.root / f"ableton_clip_details{suffix}.jsonl"
            device_params_path = catalog.root / f"ableton_device_params{suffix}.jsonl"
            routing_details_path = catalog.root / f"ableton_routing_details{suffix}.jsonl"
            refs_path = catalog.root / f"refs_graph{suffix}.jsonl"
            scan_state_path = catalog.root / f"scan_state{suffix}.json"

            conn.execute("BEGIN")
            try:
                load_file_index(conn, file_index_path, incremental, file_index_table)
                load_ableton_docs(conn, docs_path, incremental, docs_table)
                load_ableton_struct(conn, struct_path, incremental, scope)
                load_ableton_clip_details(conn, clip_details_path, incremental, scope)
                load_ableton_device_params(conn, device_params_path, incremental, scope)
                load_ableton_routing_details(conn, routing_details_path, incremental, scope)
                load_ableton_xml_nodes(conn, xml_nodes_path, incremental, scope)
                load_refs_graph(conn, refs_path, incremental, refs_table)
                load_scan_state(conn, scan_state_path, scan_state_table)
                load_audio_analysis(conn, file_index_table, scope)
                refresh_catalog_docs(conn, scope)
            except Exception:
                conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")
        with conn:
            load_ableton_prefs(conn, catalog.root)
            load_plugin_index(conn, catalog.root)
            conn.execute("PRAGMA optimize")
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
        "--append",
        action="store_true",
        help="Append into an existing database instead of failing.",
    )
    ap.add_argument(
        "--prefs-only",
        action="store_true",
        help="Only update Ableton preferences/options metadata in the database.",
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
    if args.append and args.overwrite:
        raise SystemExit("Use only one of --append or --overwrite.")

    db_path = Path(args.db).expanduser().resolve() if args.db else catalog_dir / "abletools_catalog.sqlite"
    if db_path.exists():
        if args.overwrite:
            db_path.unlink()
        elif not args.append:
            raise SystemExit(
                f"Database already exists: {db_path} (use --overwrite to replace or --append to update)"
            )
        else:
            pass

    catalog = resolve_catalog_paths(catalog_dir)
    if args.prefs_only:
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            create_schema(conn)
            ensure_column(conn, "refs_graph", "ref_exists", "ref_exists INTEGER")
            with conn:
                load_ableton_prefs(conn, catalog.root)
        finally:
            conn.close()
    else:
        migrate_catalog(catalog, db_path, incremental=args.append)

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
