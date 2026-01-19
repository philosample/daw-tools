# Abletools Schemas

This document locks down the schemas for XML extraction, JSONL outputs, and SQLite tables.

## Extension Coverage

Extensions are grouped into families and mapped to their JSONL/DB storage:

- Ableton docs: `.als`, `.alc`
  - Format: gzipped XML
  - JSONL: `ableton_docs.jsonl`, `ableton_struct.jsonl`, `refs_graph.jsonl`
  - DB: `ableton_docs*`, `ableton_tracks*`, `ableton_clips*`, `ableton_devices*`, `ableton_routing*`, `doc_sample_refs*`, `doc_device_hints*`, `doc_device_sequence*`, `refs_graph*`
- Ableton artifacts: `.adg`, `.adv`, `.agr`, `.alp`
  - Format: gzipped XML (parsed with same extractor)
  - JSONL: `ableton_docs.jsonl`, `ableton_struct.jsonl`, `refs_graph.jsonl`
  - DB: same tables as Ableton docs (with `kind=ableton_artifact`)
- Media: `.wav`, `.aif`, `.aiff`, `.flac`, `.mp3`, `.m4a`, `.ogg`
  - JSONL: `file_index.jsonl`
  - DB: `file_index*`, `audio_analysis`
- Plugins: `.component`, `.vst`, `.vst3`
  - JSONL: (none)
  - DB: `plugin_index`
- Other files: all remaining extensions
  - JSONL: `file_index.jsonl`
  - DB: `file_index*`
- Preferences and options
  - Inputs: `Preferences.cfg`, `Options.txt`
  - DB: `ableton_prefs` with `payload_json`

## XML Extraction (Ableton docs/artifacts)

The extractor is schema-agnostic and parses gzipped XML. It uses tag/attribute heuristics:

- Track tags: `AudioTrack`, `MidiTrack`, `ReturnTrack`, `MasterTrack`, `GroupTrack`, `FoldedGroupTrack`
- Clip tags: `AudioClip`, `MidiClip`
- Device hints: `PluginName`, `DeviceName`, `DisplayName`, `ShortName`, etc.
- Sample references: file paths matching audio extensions
- Tempo: `Tempo Value="..."`

The parsed output is stored in `ableton_docs.jsonl` under `summary`.

## JSONL Schemas

Schema files live in `schemas/`:

- `schemas/file_index.schema.json`
- `schemas/ableton_docs.schema.json`
- `schemas/refs_graph.schema.json`
- `schemas/ableton_struct.schema.json`
- `schemas/scan_summary.schema.json`
- `schemas/scan_state.schema.json`
- `schemas/prefs_payload.schema.json`

Each JSONL file is one record per line and maps directly to database tables below.

## SQLite Schema (Overview)

Per-scope tables (suffix is `_user_library` or `_preferences`):

- `file_index*` (generic file metadata)
- `ableton_docs*` (parsed Ableton doc/artifact summaries)
- `ableton_tracks*` (track inventory with `meta_json`)
- `ableton_clips*` (clip inventory with `meta_json`)
- `ableton_devices*` (device inventory with `meta_json`)
- `ableton_routing*` (input/output routing with `meta_json`)
- `doc_sample_refs*` (sample references)
- `doc_device_hints*` (device hints)
- `doc_device_sequence*` (ordered device sequences)
- `refs_graph*` (source -> reference edges)
- `scan_state*` (incremental scan state)

Shared tables:

- `ableton_prefs` (preferences payloads as JSON)
- `plugin_index` (VST/AU bundle metadata)
- `audio_analysis` (duration/sample rate/bit depth)
- `catalog_docs` (materialized summary used by the UI)

Analytics tables:

- `device_usage`
- `device_chain_stats`
- `device_cooccurrence`
- `doc_complexity`
- `library_growth`
- `missing_refs_by_path`

## Notes

- JSONL fields are append-only and ingested incrementally into SQLite.
- Any new extractor outputs must update the JSON schema files and DB tables.
- For new extension families, the minimal requirement is to populate `file_index.jsonl` and extend the schema docs.
- Validate outputs with `python abletools_schema_validate.py <catalog_dir>`.
