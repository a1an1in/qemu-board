#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
# 兼容入口：实际实现已统一到 tools/devops.py
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
exec "${PYTHON:-python3}" "$ROOT/tools/devops.py" run "$@"
