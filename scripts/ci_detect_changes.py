#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL_RE = re.compile(r"\\b(SELECT|INSERT|UPDATE|DELETE|WITH)\\b", re.IGNORECASE)
SQL_STRIP_RE = re.compile(r"\\s+")
TEST_ITEM_PREFIXES = (
    "abletools_",
    "ramify_core.py",
    "ableton_ramify.py",
)


def is_test_item_file(path: str) -> bool:
    if path.startswith("schemas/") and path.endswith(".schema.json"):
        return True
    name = Path(path).name
    if name.startswith(TEST_ITEM_PREFIXES):
        return True
    return False


@dataclass
class CoverageItem:
    kind: str
    name: str
    file: str
    line: int
    tests: list[str]


def _to_int(value: str) -> int:
    try:
        return int(value)
    except Exception:
        return 1


def load_coverage_map(path: Path) -> list[CoverageItem]:
    items: list[CoverageItem] = []
    if not path.exists():
        return items
    current = None
    in_tests = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("- kind:"):
            if current:
                items.append(
                    CoverageItem(
                        kind=current.get("kind", ""),
                        name=current.get("name", ""),
                        file=current.get("file", ""),
                        line=_to_int(current.get("line", "1")),
                        tests=current.get("tests", []),
                    )
                )
            current = {"kind": stripped.split(":", 1)[1].strip()}
            in_tests = False
            continue
        if current is None:
            continue
        if stripped.startswith("tests:"):
            current.setdefault("tests", [])
            in_tests = True
            continue
        if in_tests and stripped.startswith("- "):
            current.setdefault("tests", []).append(stripped[2:].strip())
            continue
        in_tests = False
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            current[key.strip()] = value.strip()
    if current:
        items.append(
            CoverageItem(
                kind=current.get("kind", ""),
                name=current.get("name", ""),
                file=current.get("file", ""),
                line=_to_int(current.get("line", "1")),
                tests=current.get("tests", []),
            )
        )
    return items


def git_diff(base: str | None, head: str | None) -> str:
    if base and head:
        cmd = ["git", "diff", "--unified=0", f"{base}...{head}"]
    else:
        cmd = ["git", "diff", "--unified=0", "HEAD~1...HEAD"]
    return subprocess.check_output(cmd, cwd=str(ROOT), text=True)


def git_changed_files(base: str | None, head: str | None) -> list[str]:
    if base and head:
        cmd = ["git", "diff", "--name-only", f"{base}...{head}"]
    else:
        cmd = ["git", "diff", "--name-only", "HEAD~1...HEAD"]
    output = subprocess.check_output(cmd, cwd=str(ROOT), text=True)
    return [line.strip() for line in output.splitlines() if line.strip()]


def extract_added_defs(diff_text: str) -> set[str]:
    defs = set()
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            stripped = line[1:].strip()
            if stripped.startswith("def "):
                name = stripped.split()[1].split("(")[0]
                defs.add(name)
            elif stripped.startswith("class "):
                name = stripped.split()[1].split("(")[0].strip(":")
                defs.add(name)
    return defs


def extract_sql_strings(text: str) -> list[tuple[str, int]]:
    results: list[tuple[str, int]] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return results
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value.strip()
            if SQL_RE.search(value):
                line = getattr(node, "lineno", 1)
                cleaned = SQL_STRIP_RE.sub(" ", value)
                results.append((cleaned[:80], line))
        elif isinstance(node, ast.JoinedStr):
            parts = []
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    parts.append(part.value)
                else:
                    parts.append("{}")
            value = "".join(parts).strip()
            if SQL_RE.search(value):
                line = getattr(node, "lineno", 1)
                cleaned = SQL_STRIP_RE.sub(" ", value)
                results.append((cleaned[:80], line))
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = node.left
            right = node.right
            if isinstance(left, ast.Constant) and isinstance(left.value, str) and isinstance(right, ast.Constant) and isinstance(right.value, str):
                value = (left.value + right.value).strip()
                if SQL_RE.search(value):
                    line = getattr(node, "lineno", 1)
                    cleaned = SQL_STRIP_RE.sub(" ", value)
                    results.append((cleaned[:80], line))
    return results


def parse_changed_lines(diff_text: str) -> dict[str, set[int]]:
    file_lines: dict[str, set[int]] = {}
    current_file = None
    new_line = None
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            current_file = line.split("+++ b/")[1].strip()
            file_lines.setdefault(current_file, set())
            new_line = None
            continue
        if line.startswith("@@"):
            parts = line.split()
            for part in parts:
                if part.startswith("+"):
                    # format +start,count or +start
                    span = part[1:].split(",")
                    new_line = int(span[0])
                    break
            continue
        if current_file is None or new_line is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            file_lines[current_file].add(new_line)
            new_line += 1
            continue
        if line.startswith("-") and not line.startswith("---"):
            continue
        if line.startswith("\\"):
            continue
        new_line += 1
    return file_lines


def build_defs_for_file(path: Path) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    items = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            end = getattr(node, "end_lineno", node.lineno)
            items.append(
                {
                    "name": node.name,
                    "line": node.lineno,
                    "end_line": end,
                    "kind": "function" if isinstance(node, ast.FunctionDef) else "class",
                }
            )
    return items


def build_queries_for_file(path: Path) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return []
    queries = []
    for snippet, line in extract_sql_strings(text):
        queries.append({"name": snippet, "line": line, "kind": "query"})
    return queries


def detect_changed_items(
    map_items: list[CoverageItem],
    changed_files: list[str],
    changed_defs: set[str],
    changed_lines: dict[str, set[int]],
) -> dict:
    by_file: dict[str, list[CoverageItem]] = {}
    for item in map_items:
        if item.file:
            by_file.setdefault(item.file, []).append(item)

    matched: list[CoverageItem] = []
    missing = []

    for file in changed_files:
        if file not in by_file:
            if is_test_item_file(file):
                missing.append({"file": file, "reason": "file missing from coverage_map"})
            continue
        matched.extend(by_file[file])

    # refine matches using changed line coverage for functions/classes/queries
    for file, lines in changed_lines.items():
        for item in by_file.get(file, []):
            if item.kind in {"function", "class", "query"} and item.line in lines:
                matched.append(item)

    # detect changed functions/classes missing in the map
    for file in changed_files:
        if not is_test_item_file(file):
            continue
        path = ROOT / file
        if not path.exists() or path.suffix != ".py":
            continue
        defs = build_defs_for_file(path)
        queries = build_queries_for_file(path)
        lines = changed_lines.get(file, set())
        for d in defs:
            if not any(line in lines for line in range(d["line"], d["end_line"] + 1)):
                continue
            if not any(
                item.kind == d["kind"] and item.name == d["name"] and item.file == file
                for item in map_items
            ):
                missing.append(
                    {"file": file, "reason": f"{d['kind']} '{d['name']}' missing from coverage_map"}
                )
        for q in queries:
            if q["line"] not in lines:
                continue
            if not any(
                item.kind == "query" and item.name == q["name"] and item.file == file
                for item in map_items
            ):
                missing.append({"file": file, "reason": f"query '{q['name']}' missing from coverage_map"})

    tests = []
    for item in matched:
        for test in item.tests:
            if test not in tests:
                tests.append(test)

    return {"tests": tests, "missing": missing}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--map", default="tests/coverage_map.yaml")
    parser.add_argument("--base")
    parser.add_argument("--head")
    args = parser.parse_args()

    diff_text = git_diff(args.base, args.head)
    changed_files = git_changed_files(args.base, args.head)
    changed_defs = extract_added_defs(diff_text)
    changed_lines = parse_changed_lines(diff_text)
    coverage = load_coverage_map(ROOT / args.map)
    result = detect_changed_items(coverage, changed_files, changed_defs, changed_lines)

    missing = result["missing"]
    if missing:
        print("Missing coverage map entries:")
        for item in missing:
            print(f"- {item['file']}: {item['reason']}")
        return 2

    if result["tests"]:
        print("tests=" + ",".join(result["tests"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
