# Abletools

Abletools is a local toolkit for indexing, searching, and analyzing Ableton Live projects, preferences, and user libraries. It scans your files, builds a JSONL catalog, and maintains a SQLite database so you can query and build tools on top of your music ecosystem.

## Highlights
- Multi-scope scans: `live_recordings`, `user_library`, and `preferences`.
- Incremental scanning with optional rehashing.
- JSONL catalogs plus a consolidated SQLite database.
- Structured XML extraction for Ableton docs and artifacts.
- Preferences auto-detection and JSON conversion.
- UI for scanning, catalog browsing, and tools like RAMify.

## Requirements
- Python 3.10+ (tested with a local venv)
- macOS (primary target; paths assume Ableton Live preferences locations)

## Quick Start
```bash
python abletools_ui.py
```

If you prefer CLI-only:
```bash
# Live recordings scan
python abletools_scan.py /path/to/Live\ Recordings

# Build or update the SQLite catalog
python abletools_catalog_db.py ./.abletools_catalog --append
```

## Scopes and Outputs
Scans write JSONL files into a central catalog directory (`.abletools_catalog/`).

Scopes:
- `live_recordings`: Ableton Live projects and associated assets.
- `user_library`: User Library content (samples, clips, presets).
- `preferences`: Ableton Preferences and Options (parsed to JSON).

Outputs (per scope):
- `file_index_<scope>.jsonl`
- `ableton_docs_<scope>.jsonl`
- `ableton_struct_<scope>.jsonl`
- `ableton_xml_nodes_<scope>.jsonl`
- `refs_graph_<scope>.jsonl`
- `scan_state_<scope>.json`

A consolidated SQLite DB is written to:
```
.abletools_catalog/abletools_catalog.sqlite
```

## UI Tabs
- **Dash**: Summary stats and recent activity.
- **Scan**: Run scans, pick scope, and manage incremental options.
- **Catalog**: Search and filter indexed documents.
- **Tools**: Utilities (e.g. RAMify).
- **Prefs**: Parsed preferences + summary.
- **Settings**: App configuration and future utilities.

## Core Commands
```bash
# Scan all files (all scopes) with hashing
python abletools_scan.py /path/to/Root --scope live_recordings --hash --rehash-all

# Incremental DB update
python abletools_catalog_db.py ./.abletools_catalog --append

# Preferences-only refresh
python abletools_catalog_db.py ./.abletools_catalog --prefs-only

# Compute analytics (device usage, FX chain templates)
python abletools_analytics.py ./.abletools_catalog/abletools_catalog.sqlite

# Maintenance (ANALYZE + PRAGMA optimize)
python abletools_maintenance.py ./.abletools_catalog/abletools_catalog.sqlite --analyze --optimize

# Validate JSON/JSONL outputs against schemas
python abletools_schema_validate.py ./.abletools_catalog
```

## Project Layout
```
abletools_ui.py            # UI entry point
abletools_scan.py          # Scanning and JSONL catalog writer
abletools_catalog_db.py    # SQLite schema + migration
abletools_prefs.py         # Preferences discovery + parsing
ramify_core.py             # Shared RAMify logic
resources/                 # Images, icons, and media assets
```

## Docs
- `docs/TEST_PLAN.md`
- `docs/OPTIMIZATION.md`
- `docs/DATA_GAPS.md`
- `docs/PRODUCT_TASKS.md`
- `docs/ANALYTICS_IDEAS.md`
- `docs/UI_VIEWS.md`
- `docs/SCHEMAS.md`

## Notes
- Catalogs are stored locally; no telemetry or remote upload.
- Preferences parsing is best-effort. Some fields are binary-encoded.
