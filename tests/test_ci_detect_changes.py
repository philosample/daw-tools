from __future__ import annotations

from pathlib import Path

import scripts.ci_detect_changes as detect


def test_load_coverage_map(tmp_path: Path) -> None:
    content = """items:
  - kind: function
    name: foo
    file: abletools_scan.py
    line: 10
    tests:
      - pytest -q tests/test_scan.py
"""
    path = tmp_path / "coverage_map.yaml"
    path.write_text(content, encoding="utf-8")
    items = detect.load_coverage_map(path)
    assert items
    assert items[0].kind == "function"
    assert items[0].name == "foo"
    assert items[0].tests == ["pytest -q tests/test_scan.py"]


def test_parse_changed_lines() -> None:
    diff_text = (
        "diff --git a/abletools_scan.py b/abletools_scan.py\n"
        "+++ b/abletools_scan.py\n"
        "@@ -10,0 +11,2 @@\n"
        "+def foo():\n"
        "+    return 1\n"
    )
    lines = detect.parse_changed_lines(diff_text)
    assert lines["abletools_scan.py"] == {11, 12}


def test_extract_sql_strings_variants() -> None:
    text = (
        "q = \"SELECT * FROM table\"\n"
        "q2 = f\"SELECT {1} FROM table\"\n"
        "q3 = \"SELECT \" + \"name FROM table\"\n"
    )
    queries = detect.extract_sql_strings(text)
    assert any("SELECT * FROM table" in q[0] for q in queries)
    assert any("SELECT {} FROM table" in q[0] for q in queries)
    assert any("SELECT name FROM table" in q[0] for q in queries)


def test_detect_cli_changes(tmp_path: Path) -> None:
    original_root = detect.ROOT
    try:
        detect.ROOT = tmp_path
        path = tmp_path / "abletools_scan.py"
        path.write_text("ap.add_argument('--foo')\n", encoding="utf-8")
        changed_lines = {"abletools_scan.py": {1}}
        tests = detect.detect_cli_changes(["abletools_scan.py"], changed_lines)
        assert "./scripts/test_full_scan.sh" in tests
    finally:
        detect.ROOT = original_root
