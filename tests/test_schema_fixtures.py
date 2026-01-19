from __future__ import annotations

from pathlib import Path

from abletools_schema_validate import _load_schema, validate_json, validate_jsonl

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "schemas"

JSON_SCHEMAS = {"scan_state.schema.json", "scan_summary.schema.json", "prefs_payload.schema.json"}


def _fixture_path(schema_name: str) -> Path:
    base = schema_name.replace(".schema.json", "")
    if schema_name in JSON_SCHEMAS:
        return FIXTURE_DIR / f"{base}.json"
    return FIXTURE_DIR / f"{base}.jsonl"


def test_schema_fixtures_cover_all() -> None:
    schema_files = sorted(SCHEMA_DIR.glob("*.schema.json"))
    assert schema_files, "no schemas found"
    for schema in schema_files:
        fixture = _fixture_path(schema.name)
        assert fixture.exists(), f"missing fixture for {schema.name}"


def test_schema_fixtures_validate() -> None:
    schema_files = sorted(SCHEMA_DIR.glob("*.schema.json"))
    for schema in schema_files:
        fixture = _fixture_path(schema.name)
        schema_obj = _load_schema(schema)
        if fixture.suffix == ".jsonl":
            errors, _ = validate_jsonl(fixture, schema_obj, max_errors=10)
            assert not errors, f"{schema.name} fixture errors: {errors}"
        else:
            errors = validate_json(fixture, schema_obj)
            assert not errors, f"{schema.name} fixture errors: {errors}"
