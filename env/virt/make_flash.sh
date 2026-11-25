#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
#
# 重新生成 64M pflash 镜像（可选，不跑 run 的 --flash 就不需要）。
# 产物在 build/flash.img；用时：python3 tools/devops.py run --flash build/flash.img
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
# shellcheck source=../../scripts/common.sh
. "$ROOT/scripts/common.sh"

OUT=${1:-$BUILD/flash.img}
SIZE=${SIZE:-64M}

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/root"
cat > "$TMP/root/README" <<'EOF'
linux-kmods pflash test image
EOF

rm -f "$OUT"
mkdir -p "$(dirname "$OUT")"
if have mksquashfs; then
	log "生成 squashfs：$OUT"
	mksquashfs "$TMP/root" "$OUT" -noappend -no-progress -quiet
	truncate -s "$SIZE" "$OUT"
else
	log "没有 mksquashfs，生成空白 ${SIZE} 镜像：$OUT"
	truncate -s "$SIZE" "$OUT"
fi
ls -lh "$OUT"
