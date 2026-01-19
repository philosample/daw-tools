# Product Task Plan

## Phase 1: Reliability
- Normalize scan output across all scopes.
- Add fixture-based tests for scan + db migrations.
- Improve prefs parsing and stable root detection.
- Add scan progress indicators (percentage or path-based activity updates). (done)
- Add schema validation step to CI or preflight. (done: incremental validator)
- Add scan checkpoints + resume for long runs. (done)
- Add doc-only hashing + changed-only scans for faster refresh. (done)

## Phase 2: Catalog Depth
- ALS parsing expansion (tracks/devices/clips/routing). (in progress)
- Sample metadata extraction (duration, bpm, key).
- Plugin metadata discovery from AU/VST folders.
- Backup tab to snapshot `.als` files, JSONL, schemas, and DB.

## Phase 3: Analytics
- Usage stats dashboards.
- Duplicate detection and missing reference auditor.
- Smart labels (color tagging) for high-use devices.
- Track/clip/device analytics from structured XML tables.

## Phase 4: Tooling
- Batch relabeling in Ableton browser (if automatable).
- Automatic cleanup suggestions.
- Template library analytics.
- Backup/restore workflows for project archives.
