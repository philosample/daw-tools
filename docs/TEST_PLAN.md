# Automated Test Plan

## Goals
- Verify scans are deterministic and incremental.
- Ensure DB migration and indexes remain consistent across scopes.
- Validate preferences parsing and caching.
- Smoke-test UI paths without manual clicking.

## Test Levels

### Unit Tests
- `abletools_prefs.py`
  - parse/normalize preferences from sample fixtures.
  - detect latest preferences and options path.
  - caching behavior for `prefs_cache.json`.
- `abletools_catalog_ops.py`
  - cleanup + backup operations with temp fixtures.
- `abletools_analytics.py`
  - set health + audio footprint metrics.
  - missing ref hotspots and device chain fingerprints.
- `abletools_scan.py`
  - incremental decision logic (mtime/size/ctime/hash).
  - scope handling and output file naming.
  - MIME detection fallback.
  - skip directories named `Backup` and timestamped backup filenames (optionally includable).
- `abletools_catalog_db.py`
  - schema creation for all scopes.
  - JSONL row ingestion and `ingest_state` updates.
  - `ref_exists` logic and uniqueness constraints.
- `abletools_ui.py`
  - formatting helpers (`format_mtime`, `truncate_path`, `set_detail_fields`).

### Integration Tests
- Scan a controlled fixture directory and compare JSONL snapshots.
- Run migration on JSONL and validate counts per table.
- Preferences-only refresh updates DB without scanning.

### UI Smoke Tests
- Start app, switch tabs, load preferences, run a scan, open catalog.
- Verify UI error log not created for normal flows.

## Automation Suggestions
- Use `pytest` with temp directories and fixture JSONL.
- Add a small `fixtures/` set with:
  - One ALS test file.
  - A fake Preferences.cfg and Options.txt.
  - Mixed file types and symlinks.
  - Schema fixtures under `tests/fixtures/schemas` for every JSON/JSONL schema.
- Harness scripts:
  - `scripts/test_full_scan.sh`
  - `scripts/test_targeted_scan.sh`
  - `scripts/test_all.sh`
- Targeted test runner:
  - `scripts/ci_detect_changes.py` + `scripts/ci_run_targeted.sh`
  - Optional git hook installer: `scripts/install_git_hooks.sh`

## Catalog
- See `docs/TEST_CATALOG.md` for the query/function/file coverage map starter.

## Detector Coverage + Gaps
- Current coverage:
  - Python functions/classes via AST + diff line ranges.
  - SQL strings from literals, simple concatenation, and f-strings in Python.
  - External `.sql` file changes trigger catalog coverage checks.
  - CLI `add_argument` changes trigger entrypoint checks (`--help` or harness runs).
  - Schema files in `schemas/*.schema.json`.
  - Non-test-item files are ignored by the detector to avoid false positives.
- Known gaps (add when they become common):
  - Queries or schemas stored outside Python (e.g., external `.sql` files).
  - Config/CLI changes that alter runtime behavior without touching core modules.
  - Resource/layout changes that affect UI queries or scan outputs.
  - Schema or JSON fixture updates that need domain-specific validators.
  - New entrypoints or scripts added outside the default catalog paths.

## CI Ideas
- Basic lint + tests on push.
- Optional integration tests on macOS runners (preferred for preference paths).
