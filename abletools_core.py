from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional


@dataclass
class CatalogStats:
    file_count: int = 0
    doc_count: int = 0
    refs_count: int = 0
    missing_refs: int = 0
    last_scan: str = ""


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def safe_read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def format_mtime(value: object) -> str:
    try:
        ts = int(value)
    except Exception:
        return ""
    if ts <= 0:
        return ""
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def format_bytes(value: object) -> str:
    try:
        size = int(value)
    except Exception:
        return ""
    if size < 0:
        return ""
    units = ["B", "KB", "MB", "GB", "TB"]
    size_float = float(size)
    unit_idx = 0
    while size_float >= 1024.0 and unit_idx < len(units) - 1:
        size_float /= 1024.0
        unit_idx += 1
    if unit_idx == 0:
        return f"{int(size_float)} {units[unit_idx]}"
    return f"{size_float:.1f} {units[unit_idx]}"


class CatalogService:
    def __init__(
        self,
        catalog_dir: Path,
        log: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self.catalog_dir = catalog_dir
        self._log = log

    def _log_event(self, kind: str, message: str) -> None:
        if self._log:
            self._log(kind, message)

    def catalog_db_path(self) -> Path:
        return self.catalog_dir / "abletools_catalog.sqlite"

    def load_catalog_stats(self) -> CatalogStats:
        db_path = self.catalog_db_path()
        stats = CatalogStats(last_scan=now_iso())
        if not db_path.exists():
            return stats
        try:
            with sqlite3.connect(db_path) as conn:
                stats.file_count = conn.execute(
                    "SELECT SUM(cnt) FROM ("
                    "SELECT COUNT(*) AS cnt FROM file_index "
                    "UNION ALL SELECT COUNT(*) FROM file_index_user_library "
                    "UNION ALL SELECT COUNT(*) FROM file_index_preferences)"
                ).fetchone()[0] or 0
                stats.doc_count = conn.execute(
                    "SELECT SUM(cnt) FROM ("
                    "SELECT COUNT(*) AS cnt FROM ableton_docs "
                    "UNION ALL SELECT COUNT(*) FROM ableton_docs_user_library "
                    "UNION ALL SELECT COUNT(*) FROM ableton_docs_preferences)"
                ).fetchone()[0] or 0
                stats.refs_count = conn.execute(
                    "SELECT SUM(cnt) FROM ("
                    "SELECT COUNT(*) AS cnt FROM refs_graph "
                    "UNION ALL SELECT COUNT(*) FROM refs_graph_user_library "
                    "UNION ALL SELECT COUNT(*) FROM refs_graph_preferences)"
                ).fetchone()[0] or 0
                stats.missing_refs = conn.execute(
                    "SELECT SUM(cnt) FROM ("
                    "SELECT COUNT(*) AS cnt FROM refs_graph WHERE ref_exists = 0 "
                    "UNION ALL SELECT COUNT(*) FROM refs_graph_user_library WHERE ref_exists = 0 "
                    "UNION ALL SELECT COUNT(*) FROM refs_graph_preferences WHERE ref_exists = 0)"
                ).fetchone()[0] or 0
        except Exception:
            return stats
        return stats

    def load_top_devices(self, limit: int = 8) -> list[str]:
        db_path = self.catalog_db_path()
        if not db_path.exists():
            return []
        try:
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT device_name, usage_count FROM device_usage "
                    "WHERE scope != 'preferences' "
                    "ORDER BY usage_count DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                if rows:
                    return [f"{name} ({count})" for name, count in rows]
                rows = conn.execute(
                    "SELECT device_name, COUNT(*) FROM doc_device_hints "
                    "WHERE scope != 'preferences' "
                    "GROUP BY device_name "
                    "ORDER BY COUNT(*) DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                return [f"{name} ({count})" for name, count in rows]
        except Exception:
            return []

    def load_top_plugins(self, limit: int = 8) -> list[str]:
        db_path = self.catalog_db_path()
        if not db_path.exists():
            return []
        try:
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT COALESCE(name, path) AS label, COALESCE(vendor, '') AS vendor, COUNT(*) "
                    "FROM plugin_index "
                    "WHERE scope != 'preferences' "
                    "GROUP BY label, vendor "
                    "ORDER BY COUNT(*) DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            results = []
            for label, vendor, count in rows:
                if vendor:
                    results.append(f"{label} ({vendor}, {count})")
                else:
                    results.append(f"{label} ({count})")
            return results
        except Exception:
            return []

    def load_top_chains(self, limit: int = 6) -> list[str]:
        db_path = self.catalog_db_path()
        if not db_path.exists():
            return []
        try:
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT chain, usage_count FROM device_chain_stats "
                    "WHERE scope != 'preferences' "
                    "ORDER BY usage_count DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [f"{chain} ({count})" for chain, count in rows]
        except Exception:
            return []

    def load_missing_refs_paths(self, limit: int = 6) -> list[str]:
        db_path = self.catalog_db_path()
        if not db_path.exists():
            return []
        try:
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT ref_parent, missing_count FROM missing_refs_by_path "
                    "WHERE scope != 'preferences' "
                    "ORDER BY missing_count DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [f"{path} ({count})" for path, count in rows]
        except Exception:
            return []

    def load_missing_hotspots(self, scope: str, limit: int = 8) -> list[str]:
        db_path = self.catalog_db_path()
        if not db_path.exists():
            return []
        try:
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT ref_parent, missing_count FROM missing_refs_by_path "
                    "WHERE scope = ? ORDER BY missing_count DESC LIMIT ?",
                    (scope, limit),
                ).fetchall()
            return [f"{path} ({count})" for path, count in rows]
        except Exception:
            return []

    def load_chain_fingerprints(self, scope: str, limit: int = 8) -> list[str]:
        db_path = self.catalog_db_path()
        if not db_path.exists():
            return []
        try:
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT chain, usage_count FROM device_chain_stats "
                    "WHERE scope = ? ORDER BY usage_count DESC LIMIT ?",
                    (scope, limit),
                ).fetchall()
            return [f"{chain} ({count})" for chain, count in rows]
        except Exception:
            return []

    def load_set_health(self, scope: str, limit: int = 8) -> list[str]:
        db_path = self.catalog_db_path()
        if not db_path.exists():
            return []
        try:
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT path, health_score, missing_refs_count, devices_count, samples_count "
                    "FROM set_health WHERE scope = ? "
                    "ORDER BY health_score ASC LIMIT ?",
                    (scope, limit),
                ).fetchall()
            results = []
            for path, score, missing, devices, samples in rows:
                name = Path(path).stem
                results.append(
                    f"{score:.0f} | {name} (missing {missing}, devices {devices}, samples {samples})"
                )
            return results
        except Exception:
            return []

    def load_audio_footprint(self, scope: str) -> dict[str, int]:
        db_path = self.catalog_db_path()
        if not db_path.exists():
            return {}
        try:
            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT total_media_bytes, referenced_media_bytes, unreferenced_media_bytes "
                    "FROM audio_footprint WHERE scope = ?",
                    (scope,),
                ).fetchone()
            if not row:
                return {}
            return {
                "total_media_bytes": int(row[0]),
                "referenced_media_bytes": int(row[1]),
                "unreferenced_media_bytes": int(row[2]),
            }
        except Exception:
            return {}

    def load_set_storage_summary(self, scope: str) -> dict[str, int]:
        db_path = self.catalog_db_path()
        if not db_path.exists():
            return {}
        try:
            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT total_sets, total_set_bytes, non_backup_sets, non_backup_bytes "
                    "FROM set_storage_summary WHERE scope = ?",
                    (scope,),
                ).fetchone()
            if not row:
                return {}
            return {
                "total_sets": int(row[0]),
                "total_set_bytes": int(row[1]),
                "non_backup_sets": int(row[2]),
                "non_backup_bytes": int(row[3]),
            }
        except Exception:
            return {}

    def load_set_activity(self, scope: str) -> list[str]:
        db_path = self.catalog_db_path()
        if not db_path.exists():
            return []
        try:
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT window_days, set_count, total_bytes "
                    "FROM set_activity_stats WHERE scope = ? "
                    "ORDER BY window_days ASC",
                    (scope,),
                ).fetchall()
            lines = []
            for days, count, total_bytes in rows:
                lines.append(
                    f"Last {days}d: {int(count)} sets ({format_bytes(int(total_bytes))})"
                )
            return lines
        except Exception:
            return []

    def load_largest_sets(self, scope: str, limit: int = 8) -> list[str]:
        db_path = self.catalog_db_path()
        if not db_path.exists():
            return []
        try:
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT path, size_bytes FROM set_size_top "
                    "WHERE scope = ? ORDER BY size_bytes DESC LIMIT ?",
                    (scope, limit),
                ).fetchall()
            return [f"{Path(path).stem} ({format_bytes(size)})" for path, size in rows]
        except Exception:
            return []

    def load_unreferenced_audio(self, scope: str, limit: int = 8) -> list[str]:
        db_path = self.catalog_db_path()
        if not db_path.exists():
            return []
        try:
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT parent_path, file_count, total_bytes "
                    "FROM unreferenced_audio_by_path "
                    "WHERE scope = ? ORDER BY total_bytes DESC LIMIT ?",
                    (scope, limit),
                ).fetchall()
            return [
                f"{path} ({int(count)} files, {format_bytes(int(total))})"
                for path, count, total in rows
            ]
        except Exception:
            return []

    def load_quality_issues(self, scope: str, limit: int = 8) -> list[str]:
        db_path = self.catalog_db_path()
        if not db_path.exists():
            return []
        try:
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT issue, path, issue_value FROM quality_issues "
                    "WHERE scope = ? ORDER BY issue_value DESC LIMIT ?",
                    (scope, limit),
                ).fetchall()
            results = []
            for issue, path, value in rows:
                name = Path(path).stem
                label = issue.replace("_", " ")
                if value:
                    results.append(f"{label}: {name} ({int(value)})")
                else:
                    results.append(f"{label}: {name}")
            return results
        except Exception:
            return []

    def load_recent_device_usage(
        self, scope: str, window_days: int = 30, limit: int = 8
    ) -> list[str]:
        db_path = self.catalog_db_path()
        if not db_path.exists():
            return []
        try:
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT device_name, usage_count FROM device_usage_recent "
                    "WHERE scope = ? AND window_days = ? "
                    "ORDER BY usage_count DESC LIMIT ?",
                    (scope, window_days, limit),
                ).fetchall()
            return [f"{name} ({int(count)})" for name, count in rows]
        except Exception:
            return []

    def load_device_pairs(self, scope: str, limit: int = 8) -> list[str]:
        db_path = self.catalog_db_path()
        if not db_path.exists():
            return []
        try:
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT device_a, device_b, usage_count FROM device_cooccurrence "
                    "WHERE scope = ? ORDER BY usage_count DESC LIMIT ?",
                    (scope, limit),
                ).fetchall()
            return [f"{a} + {b} ({int(count)})" for a, b, count in rows]
        except Exception:
            return []

    def load_dashboard_focus(self, scope: str) -> dict[str, int]:
        db_path = self.catalog_db_path()
        if not db_path.exists():
            return {}
        suffix = "" if scope == "live_recordings" else f"_{scope}"
        backup_clause = (
            "lower(path) NOT LIKE ? AND lower(path) NOT LIKE ? "
            "AND lower(path) NOT LIKE ? AND lower(path) NOT LIKE ? "
            "AND path NOT GLOB ?"
        )
        backup_params = [
            "%/backup/%",
            "%\\backup\\%",
            "backup/%",
            "backup\\%",
            "*[[][0-9]*[]]*",
        ]
        result = {
            "set_count_total": 0,
            "set_count_non_backup": 0,
            "set_bytes": 0,
            "audio_bytes": 0,
            "missing_sets": 0,
        }
        try:
            with sqlite3.connect(db_path) as conn:
                result["set_count_total"] = (
                    conn.execute(
                        f"SELECT COUNT(*) FROM file_index{suffix} "
                        "WHERE ext IN ('.als', '.alc')",
                    ).fetchone()[0]
                    or 0
                )
                result["set_count_non_backup"] = (
                    conn.execute(
                        f"SELECT COUNT(*) FROM file_index{suffix} "
                        "WHERE ext IN ('.als', '.alc') AND " + backup_clause,
                        backup_params,
                    ).fetchone()[0]
                    or 0
                )
                result["set_bytes"] = (
                    conn.execute(
                        f"SELECT SUM(size) FROM file_index{suffix} "
                        "WHERE ext IN ('.als', '.alc') AND " + backup_clause,
                        backup_params,
                    ).fetchone()[0]
                    or 0
                )
                result["audio_bytes"] = (
                    conn.execute(
                        f"SELECT SUM(size) FROM file_index{suffix} "
                        "WHERE kind = 'media' AND " + backup_clause,
                        backup_params,
                    ).fetchone()[0]
                    or 0
                )
                result["missing_sets"] = (
                    conn.execute(
                        "SELECT COUNT(*) FROM catalog_docs "
                        "WHERE scope = ? AND ext IN ('.als', '.alc') "
                        "AND missing_refs = 1 AND " + backup_clause,
                        (scope, *backup_params),
                    ).fetchone()[0]
                    or 0
                )
        except Exception:
            return result
        return result

    def list_backup_paths(self, scope: str, kind: str) -> list[Path]:
        db_path = self.catalog_db_path()
        if not db_path.exists():
            return []
        suffix = "" if scope == "live_recordings" else f"_{scope}"
        backup_clause = (
            "lower(path) NOT LIKE ? AND lower(path) NOT LIKE ? "
            "AND lower(path) NOT LIKE ? AND lower(path) NOT LIKE ? "
            "AND path NOT GLOB ?"
        )
        backup_params = [
            "%/backup/%",
            "%\\backup\\%",
            "backup/%",
            "backup\\%",
            "*[[][0-9]*[]]*",
        ]
        if kind == "audio":
            where = "kind = 'media'"
        else:
            where = "ext IN ('.als', '.alc')"
        try:
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    f"SELECT path FROM file_index{suffix} WHERE {where} AND {backup_clause}",
                    backup_params,
                ).fetchall()
        except Exception as exc:
            self._log_event("ERROR", f"list_backup_paths: {exc}")
            return []
        return [Path(path_str) for (path_str,) in rows]

    def get_known_sets(self, scope: str) -> list[dict[str, str]]:
        db_path = self.catalog_db_path()
        if not db_path.exists():
            return []
        items: list[dict[str, str]] = []
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                scopes = [scope] if scope != "all" else ["live_recordings", "user_library"]
                for scope_name in scopes:
                    if scope_name not in {"live_recordings", "user_library"}:
                        continue
                    suffix = "" if scope_name == "live_recordings" else f"_{scope_name}"
                    query = f"""
                        SELECT d.path, d.tracks_total, d.clips_total, f.mtime
                        FROM ableton_docs{suffix} d
                        JOIN file_index{suffix} f ON f.path = d.path
                        WHERE f.ext IN ('.als', '.alc')
                        ORDER BY f.mtime DESC
                        LIMIT 2000
                    """
                    for row in conn.execute(query).fetchall():
                        path = row["path"]
                        items.append(
                            {
                                "path": path,
                                "name": Path(path).name,
                                "mtime": row["mtime"],
                                "tracks": row["tracks_total"],
                                "clips": row["clips_total"],
                                "scope": scope_name,
                            }
                        )
        except Exception as exc:
            self._log_event("ERROR", f"get_known_sets: {exc}")
        return items

    def audit_zero_tracks(self) -> list[str]:
        db_path = self.catalog_db_path()
        if not db_path.exists():
            return []
        issues: list[str] = []
        log_path = self.catalog_dir / "audit_log.txt"
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                for scope, suffix in (
                    ("live_recordings", ""),
                    ("user_library", "_user_library"),
                ):
                    rows = conn.execute(
                        f"""
                        SELECT d.path, d.tracks_total, d.clips_total, d.error, f.size
                        FROM ableton_docs{suffix} d
                        LEFT JOIN file_index{suffix} f ON f.path = d.path
                        WHERE d.tracks_total = 0
                        LIMIT 50
                        """
                    ).fetchall()
                    for row in rows:
                        reason = "no track tags found"
                        if row["error"]:
                            reason = f"parse error: {row['error']}"
                        entry = (
                            f"{scope}: {row['path']} "
                            f"(tracks={row['tracks_total']}, clips={row['clips_total']}, "
                            f"size={row['size']}, {reason})"
                        )
                        issues.append(entry)
                        self._log_event("AUDIT", entry)
            if issues:
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(f"{datetime.now().isoformat()} audit_zero_tracks\n")
                    for entry in issues:
                        handle.write(f"{entry}\n")
        except Exception as exc:
            self._log_event("ERROR", f"audit_zero_tracks: {exc}")
        return issues

    def get_pref_sources(self) -> list[tuple[str, str, int]]:
        db_path = self.catalog_db_path()
        if not db_path.exists():
            return []
        items: list[tuple[str, str, int]] = []
        try:
            with sqlite3.connect(db_path) as conn:
                for row in conn.execute(
                    "SELECT kind, source, mtime FROM ableton_prefs ORDER BY mtime DESC"
                ):
                    items.append((row[0], row[1], row[2]))
        except Exception as exc:
            self._log_event("ERROR", f"get_pref_sources: {exc}")
        return items

    def get_pref_payload(self, kind: str, source: str) -> Optional[str]:
        db_path = self.catalog_db_path()
        if not db_path.exists():
            return None
        try:
            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT payload_json FROM ableton_prefs WHERE kind = ? AND source = ?",
                    (kind, source),
                ).fetchone()
        except Exception as exc:
            self._log_event("ERROR", f"get_pref_payload: {exc}")
            return None
        if not row:
            return None
        return row[0]

    def query_catalog(
        self,
        scope: str,
        term: str = "",
        filter_missing: bool = False,
        filter_devices: bool = False,
        filter_samples: bool = False,
        show_backups: bool = False,
        limit: int = 500,
    ) -> list[dict[str, str]]:
        db_path = self.catalog_db_path()
        if not db_path.exists():
            return []
        clauses = []
        params: list[object] = []
        if term:
            if scope == "preferences":
                clauses.append("(source LIKE ? OR kind LIKE ?)")
                params.extend([f"%{term}%", f"%{term}%"])
            else:
                clauses.append("path LIKE ?")
                params.append(f"%{term}%")
        if filter_missing:
            clauses.append("missing_refs = 1")
        if filter_devices:
            clauses.append("has_devices = 1")
        if filter_samples:
            clauses.append("has_samples = 1")
        if not show_backups and scope != "preferences":
            clauses.append(
                "lower(path) NOT LIKE ? AND lower(path) NOT LIKE ? AND path NOT GLOB ?"
            )
            params.extend(["%/backup/%", "%\\backup\\%", "*[[][0-9]*[]]*"])
        where_sql = " AND ".join(clauses) if clauses else "1=1"

        rows: list[dict[str, str]] = []
        try:
            with sqlite3.connect(db_path) as conn:
                if scope == "preferences":
                    sql = (
                        "SELECT kind, source, mtime "
                        "FROM ableton_prefs "
                        f"WHERE {where_sql} "
                        "ORDER BY mtime DESC LIMIT ?"
                    )
                    for kind, source, mtime in conn.execute(sql, (*params, limit)):
                        rows.append(
                            {
                                "kind": kind,
                                "source": source,
                                "mtime": format_mtime(mtime),
                                "scope": "preferences",
                            }
                        )
                    return rows

                query_scope = scope if scope != "all" else None
                if query_scope:
                    suffix = "" if query_scope == "live_recordings" else f"_{query_scope}"
                    targeted_expr = (
                        f"EXISTS (SELECT 1 FROM ableton_struct_meta{suffix} sm "
                        "WHERE sm.doc_path = catalog_docs.path)"
                    )
                else:
                    targeted_expr = (
                        "CASE scope "
                        "WHEN 'live_recordings' THEN EXISTS (SELECT 1 FROM ableton_struct_meta sm "
                        "WHERE sm.doc_path = catalog_docs.path) "
                        "WHEN 'user_library' THEN EXISTS (SELECT 1 FROM ableton_struct_meta_user_library sm "
                        "WHERE sm.doc_path = catalog_docs.path) "
                        "ELSE 0 END"
                    )
                sql = (
                    "SELECT path, ext, size, mtime, tracks_total, clips_total, "
                    "has_devices, has_samples, missing_refs, scanned_at, scope, "
                    f"{targeted_expr} AS targeted "
                    "FROM catalog_docs "
                )
                if query_scope:
                    sql += "WHERE scope = ? AND " + where_sql + " "
                    run_params = (query_scope, *params, limit)
                else:
                    sql += "WHERE " + where_sql + " "
                    run_params = (*params, limit)
                sql += "ORDER BY scanned_at DESC LIMIT ?"

                for row in conn.execute(sql, run_params):
                    path = row[0]
                    rows.append(
                        {
                            "name": Path(path).name,
                            "path_full": path,
                            "ext": row[1] or "",
                            "size": format_bytes(row[2] or 0),
                            "mtime": format_mtime(row[3]),
                            "tracks": "" if row[4] is None else str(row[4]),
                            "clips": "" if row[5] is None else str(row[5]),
                            "devices": "yes" if row[6] else "no",
                            "samples": "yes" if row[7] else "no",
                            "missing": "yes" if row[8] else "no",
                            "scanned_at": format_mtime(row[9]),
                            "scope": row[10] or scope,
                            "targeted": "yes" if row[11] else "no",
                        }
                    )
        except Exception as exc:
            self._log_event("ERROR", f"query_catalog: {exc}")
        return rows
