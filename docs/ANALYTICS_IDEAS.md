# Analytics Ideas

## Data Available Now
- `file_index*`: file size, kind, timestamps, extensions.
- `ableton_docs*`: tracks/clips totals, metadata per set.
- `doc_sample_refs*`: sample paths referenced by each set.
- `doc_device_hints*` + `doc_device_sequence*`: devices and order.
- `refs_graph*`: missing reference paths and existence.
- Analytics tables: `device_usage`, `device_chain_stats`, `device_cooccurrence`,
  `doc_complexity`, `library_growth`, `missing_refs_by_path`, `set_health`, `audio_footprint`.

## Insights Already Implemented
- Set health scoring (missing refs + devices + samples).
- Audio footprint (total/referenced/unreferenced media).
- Missing reference hotspots by folder.
- Device chain fingerprints (top sequences).

## Near-Term Plan (Based on Catalog Coverage)
1. Surface recency + size trends
   - Rolling 30/90-day set activity, storage growth.
   - "Largest sets" and "fastest growing" folders.
2. Device usage profiles
   - Top devices per scope and per time window.
   - Co-occurrence clusters and anomalies (rare combos).
3. Sample hygiene
   - Unreferenced audio by folder and size bucket.
   - Sample duplication detection (hash + path).
4. Project quality checks
   - Sets with zero clips, empty tracks, or missing routings.
   - Outlier complexity (very high device/sample counts).

## Tooling Ideas
- Batch "archive" suggestions for cold sets and dead samples.
- Auto-tag sets based on dominant devices or genre signals.
- "Cleanup pack" generator: bundles stale sets, unused samples, and notes.
- FX chain preset suggestions from common sequences.
- Health regression alerts after scans (score drops).

## Visualization Ideas
- Small sparklines in Insights (storage growth, missing refs trend).
- Stacked bars for device families (Ableton vs. third-party).
- Tree-map view for sample storage hotspots.

## Implementation Notes
- Use SQLite aggregation for default UI panels.
- Optional Pandas/DuckDB for ad-hoc deep dives.
- Keep all analytics local and stored in the catalog DB.
