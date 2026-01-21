# UI/Core Boundary and PyQt Migration Plan

## Core boundary (current)
- Core module: `abletools_core.py`
  - Data models: `CatalogStats`
  - Utilities: `now_iso`, `safe_read_json`, `format_bytes`
  - Catalog data access: `CatalogService` (SQLite reads and light formatting)
- UI module: `abletools_ui.py`
  - Tk widgets, layout, event wiring, threading/queue
  - Delegates catalog queries + set selection data to `CatalogService`

The goal is that `abletools_core.py` stays free of UI frameworks. It should be safe
to import in Tk, PyQt, or CLI tools without side effects.

## Migration path (PyQt)
1) **Stabilize the core layer**
   - Keep all catalog queries, formatting, and scan command assembly in the core.
   - Add unit tests for core functions (SQLite query outputs, formatting).

2) **Define a UI adapter interface**
   - Minimal interface for logging, progress updates, and user prompts.
   - This keeps threading/async handling isolated in the UI layer.

3) **Build a PyQt shell in parallel**
   - Implement the same view flow (Dashboard, Scan, Catalog, Insights).
   - Use the core for data and scan orchestration.
   - Keep Tk UI as the reference until parity is reached.

4) **Swap default entry point**
   - Add a new `abletools_qt.py` entrypoint.
   - Once parity is good, update CLI/launchers to default to PyQt.

## What still lives in Tk (next extraction candidates)
- Scan command construction and execution orchestration.
- Background task / log streaming utilities.
- Any SQLite writes or file system operations in UI methods.

## Notes
- The `CatalogService` API is intended to stay stable as the UI changes.
- When adding new views, place data access/formatting in `abletools_core.py`.
