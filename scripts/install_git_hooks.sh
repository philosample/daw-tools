#!/usr/bin/env bash
set -euo pipefail

HOOK_DIR=".git/hooks"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$HOOK_DIR"
ln -sf "$SCRIPT_DIR/post-commit" "$HOOK_DIR/post-commit"

echo "Installed post-commit hook."
