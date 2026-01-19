#!/usr/bin/env bash
set -euo pipefail

BASE_SHA="${BASE_SHA:-}"
HEAD_SHA="${HEAD_SHA:-}"

OUTPUT="$(python3 scripts/ci_detect_changes.py --base "$BASE_SHA" --head "$HEAD_SHA")"
if [[ -z "$OUTPUT" ]]; then
  echo "No matching tests in coverage map."
  exit 0
fi

TESTS_LINE="$(echo "$OUTPUT" | rg '^tests=' || true)"
if [[ -z "$TESTS_LINE" ]]; then
  echo "$OUTPUT"
  exit 0
fi

TESTS="${TESTS_LINE#tests=}"
IFS=',' read -r -a TEST_ARRAY <<< "$TESTS"

for test_cmd in "${TEST_ARRAY[@]}"; do
  if [[ -n "$test_cmd" ]]; then
    echo "Running: $test_cmd"
    eval "$test_cmd"
  fi
done
