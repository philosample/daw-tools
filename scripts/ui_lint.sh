#!/usr/bin/env bash
set -euo pipefail

fail=0

echo "ui_lint: checking for disallowed setFixedHeight..."
bad_fixed=$(rg "setFixedHeight" abletools_qt.py \
  | rg -v "title.setFixedHeight" || true)
if [[ -n "$bad_fixed" ]]; then
  echo "ui_lint: FAIL setFixedHeight outside allowlist:"
  echo "$bad_fixed"
  fail=1
fi

echo "ui_lint: checking for raw QCheckBox usage..."
python - "$fail" <<'PY'
import pathlib, sys, re
fail = int(sys.argv[1])
text = pathlib.Path("abletools_qt.py").read_text().splitlines()
occ = [i for i,l in enumerate(text) if "QCheckBox(" in l]
start = next(i for i,l in enumerate(text) if l.strip().startswith("def _checkbox"))
end = next((i for i in range(start+1, len(text)) if text[i].startswith("def ")), len(text))
bad = [i for i in occ if not (start <= i < end)]
if bad:
    print("ui_lint: FAIL raw QCheckBox constructions (use _checkbox + _checkbox_flow):")
    for i in bad:
        print(f"  {i+1}: {text[i].strip()}")
    sys.exit(1)
sys.exit(fail)
PY

echo "ui_lint: checking that line edits are labeled..."
python - "$fail" <<'PY'
import pathlib, sys, re
fail = int(sys.argv[1])
text = pathlib.Path("abletools_qt.py").read_text().splitlines()
bad = []
for i, line in enumerate(text):
    if "def _line_edit" in line:
        continue
    if "_line_edit(" not in line:
        continue
    stripped = line.strip()
    if stripped.startswith('("'):
        continue  # labeled tuple in _controls_grid
    window = text[max(0, i-3): min(len(text), i+12)]
    window_text = "\n".join(window)
    if "_field_label" not in window_text:
        bad.append((i + 1, stripped))
if bad:
    print("ui_lint: FAIL unlabeled line edits (add _field_label or a labeled _controls_grid tuple):")
    for lineno, snippet in bad:
        print(f"  {lineno}: {snippet}")
    sys.exit(1)
sys.exit(fail)
PY

exit $fail
