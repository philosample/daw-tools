#!/usr/bin/env bash
set -euo pipefail

ROOT="$(mktemp -d)"
OUT_DEFAULT="$(mktemp -d)"
OUT_INCLUDE="$(mktemp -d)"

cleanup() {
  rm -rf "$ROOT" "$OUT_DEFAULT" "$OUT_INCLUDE"
}
trap cleanup EXIT

mkdir -p "$ROOT/Backup"

cat >"$ROOT/Set.als" <<'EOF'
<Ableton>
  <AudioTrack Name="Main">
    <AudioClip Name="Clip A" Length="4.0" />
  </AudioTrack>
</Ableton>
EOF

cat >"$ROOT/Backup/Set Backup.als" <<'EOF'
<Ableton>
  <AudioTrack Name="Backup">
    <AudioClip Name="Clip B" Length="8.0" />
  </AudioTrack>
</Ableton>
EOF

cat >"$ROOT/Set [2026-01-19 123456].als" <<'EOF'
<Ableton>
  <AudioTrack Name="Timestamp">
    <AudioClip Name="Clip C" Length="2.0" />
  </AudioTrack>
</Ableton>
EOF

python3 abletools_scan.py "$ROOT" \
  --scope live_recordings \
  --mode full \
  --out "$OUT_DEFAULT" \
  --only-known

python3 abletools_schema_validate.py "$OUT_DEFAULT"

python3 - <<PY
import json
from pathlib import Path

path = Path("$OUT_DEFAULT") / "file_index.jsonl"
assert path.exists(), "file_index.jsonl missing"
rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
paths = [row["path"] for row in rows]
assert any(p.endswith("Set.als") for p in paths), "expected Set.als"
assert not any("/Backup/" in p or "\\\\Backup\\\\" in p for p in paths), "backup dir should be excluded"
assert not any("[2026-01-19" in p for p in paths), "timestamp backup should be excluded"
PY

python3 abletools_scan.py "$ROOT" \
  --scope live_recordings \
  --mode full \
  --out "$OUT_INCLUDE" \
  --only-known \
  --include-backups

python3 abletools_schema_validate.py "$OUT_INCLUDE"

python3 - <<PY
import json
from pathlib import Path

path = Path("$OUT_INCLUDE") / "file_index.jsonl"
assert path.exists(), "file_index.jsonl missing"
rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
paths = [row["path"] for row in rows]
assert any("/Backup/" in p or "\\\\Backup\\\\" in p for p in paths), "backup dir should be included"
assert any("[2026-01-19" in p for p in paths), "timestamp backup should be included"
PY
