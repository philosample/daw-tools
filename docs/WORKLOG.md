# Worklog & Backlog

## Worklog
- 2026-01-19: Added comprehensive XML node capture (opt-in), schema validation, and scan performance safeguards (hash-docs-only, changed-only, checkpoints).
- 2026-01-19: Added structured XML extraction and normalized tables (tracks/clips/devices/routing) plus schema docs.

## Backlog (Prioritized)
### P0: Targeted XML Extraction (No automation/arrangement)
- Device parameters (minimal): extract param id/name/value and device association.
- Routing details (minimal): input/output targets + sends/returns flags.
- Clip details (minimal): warp mode, loop on/off, loop range, transpose/pitch.

### P1: Schema + DB Enrichment
- JSONL schemas for new outputs.
- SQLite tables + ingestion for new outputs.
- Incremental validation for new JSONL types.

### P2: Analytics Hooks
- Device parameter usage distributions.
- Routing anomaly detection.
- Clip warp/loop usage stats.

### P3: UX / Tooling
- Add UI panel for clip/device details.
- Add routing diagnostics view.
- Backup tab (snapshot .als + db + JSON + schemas).

## Current Plan
1) Implement P0 targeted extraction (device params, routing details, clip details).
2) Add JSONL schemas + DB tables + migration for new outputs.
3) Update validator and docs; run tests.
