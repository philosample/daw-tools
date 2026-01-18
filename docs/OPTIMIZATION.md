# Optimization Ideas

## Implemented (Baseline)
- Scandir-based traversal to reduce stat overhead.
- Directory mtime cache to skip unchanged subtrees during incremental scans.
- MIME lookup cache by extension.
- Batch inserts via `executemany` and WAL mode during ingestion.
- Per-scope transactions with memory temp store and larger SQLite cache size.
- Materialized `catalog_docs` for faster UI queries.

## Scanning Performance
- Use `os.scandir` everywhere for faster stat calls.
- Batch hashing in a worker pool; skip hash unless needed.
- Cache MIME lookups per extension.
- Consider a lightweight file type allowlist for docs vs. media.
- Add a fast path for unchanged directories (mtime on directory tree).

## Database Performance
- Enable WAL mode and `synchronous=NORMAL` during ingestion.
- Use `executemany` batches for inserts.
- Add partial indexes for heavy queries (e.g. `missing_refs`).
- Store path hashes for faster lookups.

## UI Responsiveness
- Virtualize large tables in Catalog (lazy list).
- Async scan progress updates only every N rows.
- Keep GIF animation off main thread if possible.

## Storage & Data Layout
- Compact JSONL outputs (optional compression).
- Normalize path references to reduce duplication.
- Separate large blobs (raw prefs) into a sidecar file.
