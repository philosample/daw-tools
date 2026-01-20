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
- Set storage summary (total + non-backup bytes).
- Set activity windows (30/90-day counts + bytes).
- Set activity deltas vs prior window.
- Fastest-growing folders by recent bytes.
- Largest sets (by file size).
- Unreferenced audio hotspots (by folder).
- Quality flags (zero clips/tracks, missing refs, large counts).
- Recent device usage (30d/90d).
- Rare device pairs (low co-occurrence).
- Sample duplication groups (sha1 + size).
- Cold samples (not referenced by recent sets).
- Routing anomalies (missing routing values).

## Next Focus (Based on Catalog Coverage)
1. Deeper routing/track checks
   - Silent track detection (no clips + no routing).
   - Input/output mismatch heuristics per track type.
2. Sample intelligence
   - BPM/key detection for audio samples.
   - Similarity clustering (beyond hash duplicates).
3. Device + clip analytics
   - Device parameter usage distributions.
   - Clip warp/loop usage and clip density outliers.

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
