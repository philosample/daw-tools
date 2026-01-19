#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_schema(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _type_matches(expected: str, value: Any) -> bool:
    mapping = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "object": dict,
        "array": list,
        "boolean": bool,
        "null": type(None),
    }
    py_type = mapping.get(expected)
    if py_type is None:
        return True
    return isinstance(value, py_type)


def _validate_value(schema: dict, value: Any, errors: list[str], ctx: str) -> None:
    if "type" in schema:
        expected = schema["type"]
        if isinstance(expected, list):
            if not any(_type_matches(t, value) for t in expected):
                errors.append(f"{ctx}: type mismatch (expected {expected}, got {type(value).__name__})")
                return
        else:
            if not _type_matches(expected, value):
                errors.append(f"{ctx}: type mismatch (expected {expected}, got {type(value).__name__})")
                return
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{ctx}: value {value} not in enum {schema['enum']}")


def validate_record(schema: dict, record: dict, ignore_required: set[str] | None = None) -> list[str]:
    errors: list[str] = []
    required = schema.get("required", [])
    for key in required:
        if ignore_required and key in ignore_required:
            continue
        if key not in record:
            errors.append(f"missing required key: {key}")
    properties = schema.get("properties", {})
    for key, prop in properties.items():
        if key not in record:
            continue
        _validate_value(prop, record[key], errors, key)
    return errors


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            yield line_no, json.loads(line)


def validate_jsonl(path: Path, schema: dict, max_errors: int, ignore_required: set[str] | None = None) -> list[str]:
    errors: list[str] = []
    for line_no, record in iter_jsonl(path):
        for err in validate_record(schema, record, ignore_required=ignore_required):
            errors.append(f"{path.name}:{line_no}: {err}")
            if len(errors) >= max_errors:
                return errors
    return errors


def validate_json(path: Path, schema: dict) -> list[str]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"{path.name}: failed to read JSON: {exc}"]
    errors = validate_record(schema, record)
    return [f"{path.name}: {err}" for err in errors]


def build_targets(catalog_dir: Path) -> list[tuple[Path, Path, str, set[str] | None]]:
    schema_dir = Path(__file__).resolve().parent / "schemas"
    targets = []
    for suffix in ("", "_user_library", "_preferences"):
        ignore_scope = {"scope"} if suffix == "" else None
        targets.append((catalog_dir / f"file_index{suffix}.jsonl", schema_dir / "file_index.schema.json", "jsonl", ignore_scope))
        targets.append((catalog_dir / f"ableton_docs{suffix}.jsonl", schema_dir / "ableton_docs.schema.json", "jsonl", ignore_scope))
        targets.append((catalog_dir / f"ableton_struct{suffix}.jsonl", schema_dir / "ableton_struct.schema.json", "jsonl", ignore_scope))
        targets.append((catalog_dir / f"ableton_xml_nodes{suffix}.jsonl", schema_dir / "ableton_xml_nodes.schema.json", "jsonl", ignore_scope))
        targets.append((catalog_dir / f"refs_graph{suffix}.jsonl", schema_dir / "refs_graph.schema.json", "jsonl", ignore_scope))
        targets.append((catalog_dir / f"scan_state{suffix}.json", schema_dir / "scan_state.schema.json", "json", None))
        targets.append((catalog_dir / f"scan_summary{suffix}.json", schema_dir / "scan_summary.schema.json", "json", None))
    return targets


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate Abletools JSON/JSONL outputs against schemas.")
    ap.add_argument("catalog", nargs="?", default=".abletools_catalog", help="Catalog directory")
    ap.add_argument("--max-errors", type=int, default=50, help="Stop after this many errors")
    args = ap.parse_args()

    catalog_dir = Path(args.catalog)
    if not catalog_dir.exists():
        print(f"Catalog directory not found: {catalog_dir}")
        return 2

    total_errors: list[str] = []
    for data_path, schema_path, kind, ignore_required in build_targets(catalog_dir):
        if not data_path.exists():
            continue
        if not schema_path.exists():
            total_errors.append(f"Missing schema: {schema_path}")
            continue
        schema = _load_schema(schema_path)
        if kind == "jsonl":
            errors = validate_jsonl(
                data_path,
                schema,
                args.max_errors - len(total_errors),
                ignore_required=ignore_required,
            )
        else:
            errors = validate_json(data_path, schema)
        total_errors.extend(errors)
        if len(total_errors) >= args.max_errors:
            break

    if total_errors:
        print("Schema validation failed:")
        for err in total_errors:
            print(f"- {err}")
        return 1

    print("Schema validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
