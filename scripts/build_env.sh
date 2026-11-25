#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
# 兼容入口：实际实现已统一到 tools/devops.py
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PY=${PYTHON:-python3}

target=${1:-all}
shift || true
if [ "${1:-}" = "--jobs" ]; then
	[ $# -ge 2 ] || { echo "--jobs 需要参数" >&2; exit 1; }
	jobs=$2
	shift 2
	exec "$PY" "$ROOT/tools/devops.py" build "$target" --jobs "$jobs" "$@"
fi
exec "$PY" "$ROOT/tools/devops.py" build "$target" "$@"
