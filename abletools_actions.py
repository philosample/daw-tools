from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Tuple

from abletools_catalog_ops import cleanup_catalog_dir
from abletools_core import format_bytes

ABLETOOLS_DIR = Path(__file__).resolve().parent


def open_in_finder(path: str) -> None:
    subprocess.run(["open", path])


def build_targeted_scan_cmd(path: str, scope: str, catalog_dir: Path) -> list[str]:
    scan_script = ABLETOOLS_DIR / "abletools_scan.py"
    return [
        sys.executable,
        str(scan_script),
        str(path),
        "--scope",
        scope,
        "--mode",
        "targeted",
        "--details",
        "struct,clips,devices,routing,refs",
        "--out",
        str(catalog_dir),
        "--incremental",
        "--progress",
        "--verbose",
    ]


def run_targeted_scan(path: str, scope: str, catalog_dir: Path) -> subprocess.CompletedProcess:
    cmd = build_targeted_scan_cmd(path, scope, catalog_dir)
    return subprocess.run(cmd, cwd=str(ABLETOOLS_DIR), capture_output=True, text=True)


def run_catalog_cleanup(
    catalog_dir: Path,
    selected: dict[str, bool],
    rebuild_db: bool,
    optimize_db: bool,
) -> Tuple[int, int, str]:
    removed, bytes_freed = cleanup_catalog_dir(catalog_dir, selected)
    maintenance_msg = ""
    if rebuild_db:
        script = ABLETOOLS_DIR / "abletools_catalog_db.py"
        proc = subprocess.run(
            [
                sys.executable,
                str(script),
                str(catalog_dir),
                "--overwrite",
                "--vacuum",
            ],
            cwd=str(ABLETOOLS_DIR),
            capture_output=True,
            text=True,
        )
        maintenance_msg = (
            " Rebuilt DB." if proc.returncode == 0 else f" Rebuild failed: {proc.stderr.strip()}"
        )
    elif optimize_db:
        script = ABLETOOLS_DIR / "abletools_maintenance.py"
        proc = subprocess.run(
            [
                sys.executable,
                str(script),
                str(catalog_dir / "abletools_catalog.sqlite"),
                "--analyze",
                "--optimize",
                "--vacuum",
            ],
            cwd=str(ABLETOOLS_DIR),
            capture_output=True,
            text=True,
        )
        maintenance_msg = (
            " Optimized DB." if proc.returncode == 0 else f" Optimize failed: {proc.stderr.strip()}"
        )
    summary = f"Removed {removed} files, freed {format_bytes(bytes_freed)}.{maintenance_msg}"
    return removed, bytes_freed, summary
