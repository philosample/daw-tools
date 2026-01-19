#!/usr/bin/env bash
set -euo pipefail

pytest -q
./scripts/test_full_scan.sh
./scripts/test_targeted_scan.sh
