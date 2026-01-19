from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Iterable


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
