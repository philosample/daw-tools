from __future__ import annotations

import shutil
from datetime import datetime
import json
import sqlite3
from pathlib import Path
from typing import Iterable

from abletools_catalog_db import SCOPES, scope_suffix
from abletools_scan import ABLETON_DOC_EXTS, MEDIA_EXTS


def cleanup_catalog_dir(catalog_dir: Path, options: dict[str, bool]) -> tuple[int, int]:
    if not catalog_dir.exists():
        return 0, 0
    removed = 0
    bytes_freed = 0

    def _remove(path: Path) -> None:
        nonlocal removed, bytes_freed
        try:
            bytes_freed += path.stat().st_size
        except OSError:
            pass
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass

    if options.get("logs"):
        for path in catalog_dir.glob("scan_log_*.txt"):
            _remove(path)
        for path in catalog_dir.glob("scan_log_targeted_*.txt"):
            _remove(path)
        for path in catalog_dir.glob("missing_refs_audit_*.txt"):
            _remove(path)

    if options.get("xml_nodes"):
        for path in catalog_dir.glob("ableton_xml_nodes*.jsonl"):
            _remove(path)

    if options.get("device_params"):
        for path in catalog_dir.glob("ableton_device_params*.jsonl"):
            _remove(path)

    if options.get("refs_graph"):
        for path in catalog_dir.glob("refs_graph*.jsonl"):
            _remove(path)

    if options.get("struct"):
        for pattern in (
            "ableton_struct*.jsonl",
            "ableton_clip_details*.jsonl",
            "ableton_routing_details*.jsonl",
        ):
            for path in catalog_dir.glob(pattern):
                _remove(path)

    if options.get("scan_state"):
        for pattern in ("scan_state*.json", "dir_state*.json", "scan_checkpoint*.json"):
            for path in catalog_dir.glob(pattern):
                _remove(path)

    return removed, bytes_freed


def prune_file_index_jsonl(catalog_dir: Path) -> tuple[int, int]:
    removed = 0
    bytes_freed = 0
    allowed_exts = ABLETON_DOC_EXTS | MEDIA_EXTS
    for path in catalog_dir.glob("file_index*.jsonl"):
        if not path.exists():
            continue
        before_size = path.stat().st_size
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        kept_lines = 0
        removed_lines = 0
        with path.open("r", encoding="utf-8") as src, tmp_path.open(
            "w", encoding="utf-8"
        ) as dst:
            for line in src:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    rec = json.loads(stripped)
                except json.JSONDecodeError:
                    dst.write(line)
                    kept_lines += 1
                    continue
                ext = str(rec.get("ext") or "").lower()
                if ext in allowed_exts:
                    dst.write(line)
                    kept_lines += 1
                else:
                    removed_lines += 1
        tmp_path.replace(path)
        removed += removed_lines
        after_size = path.stat().st_size
        bytes_freed += max(0, before_size - after_size)
    return removed, bytes_freed


def prune_db_file_index(db_path: Path) -> tuple[int, int]:
    removed = 0
    bytes_freed = 0
    allowed_exts = sorted(ABLETON_DOC_EXTS | MEDIA_EXTS)
    if not db_path.exists():
        return removed, bytes_freed
    conn = sqlite3.connect(db_path)
    try:
        for scope in SCOPES:
            suffix = scope_suffix(scope)
            table = f"file_index{suffix}"
            placeholders = ",".join("?" for _ in allowed_exts)
            cur = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE ext NOT IN ({placeholders})",
                allowed_exts,
            )
            row = cur.fetchone()
            to_remove = int(row[0]) if row else 0
            if to_remove:
                conn.execute(
                    f"DELETE FROM {table} WHERE ext NOT IN ({placeholders})",
                    allowed_exts,
                )
            removed += to_remove
        conn.commit()
    finally:
        conn.close()
    return removed, bytes_freed


def backup_files(
    paths: Iterable[Path],
    dest_dir: Path,
    active_root: Path | None,
    kind: str,
    timestamp: str | None = None,
    cleanup_unzipped: bool = True,
) -> tuple[int, int, Path | None]:
    copied = 0
    skipped = 0
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    base_dir = dest_dir / "Abletools Backup" / f"{kind}_{stamp}"
    base_dir.mkdir(parents=True, exist_ok=True)

    for path in paths:
        if not path.exists():
            skipped += 1
            continue
        if active_root:
            try:
                rel = path.relative_to(active_root)
            except ValueError:
                rel = Path(path.name)
        else:
            rel = Path(path.name)
        target = base_dir / rel
        if target.exists():
            skipped += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(path, target)
            copied += 1
        except Exception:
            skipped += 1

    archive_path: Path | None = None
    if copied > 0:
        try:
            archive_path = Path(
                shutil.make_archive(str(base_dir), "zip", root_dir=base_dir)
            )
            if cleanup_unzipped:
                shutil.rmtree(base_dir, ignore_errors=True)
        except Exception:
            archive_path = None
    return copied, skipped, archive_path
