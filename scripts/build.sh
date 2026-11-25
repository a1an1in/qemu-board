#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
# 兼容入口：模块/检查命令已统一到 tools/devops.py
#
#   ./scripts/build.sh                 # 编译所有模块
#   ./scripts/build.sh clean           # 清理产物
#   ./scripts/build.sh checkpatch      # checkpatch
#   ./scripts/build.sh sparse          # sparse（C=2）
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PY=${PYTHON:-python3}
MODE=${1:-modules}
shift || true

case "$MODE" in
modules)
	exec "$PY" "$ROOT/tools/devops.py" modules "$@"
	;;
clean)
	exec "$PY" "$ROOT/tools/devops.py" clean modules --yes "$@"
	;;
checkpatch)
	exec "$PY" "$ROOT/tools/devops.py" checkpatch "$@"
	;;
sparse)
	exec "$PY" "$ROOT/tools/devops.py" modules --sparse "$@"
	;;
*)
	sed -n '2,10p' "$0"
	exit 1
	;;
esac
