# Worklog & Backlog

## Worklog
- 2026-01-19: Added remaining analytics (activity deltas, growth folders, duplicates, cold samples, routing anomalies, rare pairs) with tests + UI wiring.
- 2026-01-19: Expanded Insights analytics (storage/activity, largest sets, unreferenced audio, quality flags, recent devices) and added tests/UI updates.
- 2026-01-19: Added Insights analytics (set health, missing hotspots, audio footprint, chain fingerprints) with tests and docs updates.
- 2026-01-19: Updated agent policy: auto-commit allowed when configured, but pushes require explicit approval; run syntax checks/tests before proposing commits.
- 2026-01-19: Added comprehensive XML node capture (opt-in), schema validation, and scan performance safeguards (hash-docs-only, changed-only, checkpoints).
- 2026-01-19: Added structured XML extraction and normalized tables (tracks/clips/devices/routing) plus schema docs.
- 2026-01-19: Split scan modes (full vs targeted) and added per-set JSON cache for targeted scans.

## Backlog (Prioritized)
### P0: Targeted Scan UX
- Persist targeted scan detail group defaults.
- Add targeted scan run history (per-set cache age + last refresh).

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
1) Polish targeted scan UX and visibility (history + defaults).
2) Add per-set cache inspection in UI details pane.
