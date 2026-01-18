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
- `abletools_scan.py`
  - incremental decision logic (mtime/size/ctime/hash).
  - scope handling and output file naming.
  - MIME detection fallback.
- `abletools_catalog_db.py`
  - schema creation for all scopes.
  - JSONL row ingestion and `ingest_state` updates.
  - `ref_exists` logic and uniqueness constraints.

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

## CI Ideas
- Basic lint + tests on push.
- Optional integration tests on macOS runners (preferred for preference paths).

