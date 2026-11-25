#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
# 兼容入口：initramfs 由 tools/devops.py 用纯 Python 打包
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
exec "${PYTHON:-python3}" "$ROOT/tools/devops.py" build initramfs "$@"
