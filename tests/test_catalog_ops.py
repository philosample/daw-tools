from __future__ import annotations

from pathlib import Path

from abletools_catalog_ops import backup_files, cleanup_catalog_dir


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
