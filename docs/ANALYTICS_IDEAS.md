# Analytics Ideas

## High-Value Metrics
- Most used devices across projects.
- Device co-occurrence matrix (which devices appear together).
- Tempo and key distributions across sets.
- Project recency and activity heatmap.
- Unused sample detection (referenced vs. unreferenced).

## Trend Detection
- Rolling 30/90-day changes in device usage.
- Growth in library size by type.
- Changes in average project size over time.

## Tool Ideas
- Auto-color labeling for top N devices.
- "Top 10" dashboard widgets.
- Tag suggestions based on device or sample clusters.
- Suggest FX chain templates from commonly ordered device sequences.

## Potential Analytics Stack
- SQLite + Pandas for local analysis.
- DuckDB for heavy ad-hoc analytics on JSONL.
- Lightweight charts in UI (sparklines, histograms).
