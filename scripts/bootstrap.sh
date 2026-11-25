#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
# 兼容入口：实际实现已统一到 tools/devops.py
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PY=${PYTHON:-python3}

if [ "${1:-}" = "--check" ]; then
	shift
	exec "$PY" "$ROOT/tools/devops.py" doctor "$@"
fi
exec "$PY" "$ROOT/tools/devops.py" init "$@"
