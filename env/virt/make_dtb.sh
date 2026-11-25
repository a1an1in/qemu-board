#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
#
# 从 virt_custom.dts 生成 DTB（可选）。
# 默认 run_qemu.sh 不传 -dtb：自研 QEMU 自动生成的 FDT 才带 tmp105/emmc/spi 节点。
# 只有移植到别的 QEMU/板子时才需要这份 DTB。
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
# shellcheck source=../../scripts/common.sh
. "$ROOT/scripts/common.sh"

have dtc || die "需要 dtc（apt install device-tree-compiler）"
OUT=${1:-$BUILD/virt_custom.dtb}
mkdir -p "$(dirname "$OUT")"
dtc -q -I dts -O dtb -o "$OUT" "$ROOT/env/virt/virt_custom.dts"
log "生成：$OUT"
