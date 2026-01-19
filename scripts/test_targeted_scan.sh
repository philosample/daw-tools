#!/usr/bin/env bash
set -euo pipefail

ROOT="$(mktemp -d)"
OUT_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "$ROOT" "$OUT_DIR"
}
trap cleanup EXIT

cat >"$ROOT/Set.als" <<'EOF'
<Ableton>
  <AudioTrack Name="Main">
    <AudioClip Name="Clip A" Length="4.0" />
  </AudioTrack>
</Ableton>
EOF

python3 abletools_scan.py "$ROOT/Set.als" \
  --scope live_recordings \
  --mode targeted \
  --details struct,clips,devices,routing,refs \
  --out "$OUT_DIR"

python3 abletools_schema_validate.py "$OUT_DIR"

python3 - <<PY
from pathlib import Path

out_dir = Path("$OUT_DIR")
docs = out_dir / "ableton_docs.jsonl"
struct = out_dir / "ableton_struct.jsonl"
refs = out_dir / "refs_graph.jsonl"
per_doc_dir = out_dir / "sets" / "live_recordings"

assert docs.exists(), "ableton_docs.jsonl missing"
assert struct.exists(), "ableton_struct.jsonl missing"
if not refs.exists():
    print("WARN: refs_graph.jsonl missing (no refs emitted)")
assert per_doc_dir.exists(), "per-doc output dir missing"
per_docs = list(per_doc_dir.glob("*.json"))
assert per_docs, "per-doc json missing"
PY
