#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_BIN="${TARGET_BIN:-$ROOT_DIR/protocol_manager}"

if [[ ! -x "$TARGET_BIN" ]]; then
  echo "protocol_manager binary not found or not executable: $TARGET_BIN" >&2
  exit 1
fi

exec sudo nsenter -t 1 -n "$TARGET_BIN" "$@"
