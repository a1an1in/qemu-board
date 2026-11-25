# SPDX-License-Identifier: GPL-2.0
#
# 所有脚本共用：仓库根、lab.conf 版本、路径、日志/断言、QEMU patch 队列操作。
# 用法：. "$(dirname "$0")/common.sh"

LAB_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

# lab.conf 里的键允许被环境变量覆盖（例：QEMU_SERIES=spi make env-qemu）。
# 先保存当前环境里的值，source 完再恢复。
_lab_keys="KERNEL_VERSION KERNEL_URL KERNEL_SHA256 \
 BUSYBOX_VERSION BUSYBOX_URL BUSYBOX_SHA256 \
 QEMU_URL QEMU_TAG QEMU_BASE QEMU_SERIES QEMU_CLONE_FILTER QEMU_FALLBACK_DEPTH"
_lab_restore=()
for _v in $_lab_keys; do
	if [[ -v $_v ]]; then
		printf -v "_saved_$_v" '%s' "${!_v}"
		_lab_restore+=("$_v")
	fi
done

set -a
# shellcheck disable=SC1091
. "$LAB_ROOT/lab.conf"
set +a

for _v in "${_lab_restore[@]}"; do
	_sname="_saved_$_v"
	printf -v "$_v" '%s' "${!_sname}"
done
unset _sname
unset _v _lab_keys _lab_restore

# ---- 可覆盖的默认值 ----
: "${ARCH:=arm64}"
: "${CROSS_COMPILE:=aarch64-linux-gnu-}"
: "${JOBS:=$(nproc 2>/dev/null || echo 4)}"
: "${EXTERNAL:=$LAB_ROOT/external}"
: "${BUILD:=$LAB_ROOT/build}"
: "${QEMU_SRC:=$EXTERNAL/qemu}"
: "${QEMU_BUILD:=$BUILD/qemu}"
: "${KERNEL_SRC:=$EXTERNAL/linux-$KERNEL_VERSION}"
: "${BUSYBOX_SRC:=$EXTERNAL/busybox-$BUSYBOX_VERSION}"
: "${KERNEL_BUILD:=$BUILD/kernel}"
: "${BUSYBOX_BUILD:=$BUILD/busybox}"
: "${ROOTFS:=$BUILD/rootfs}"
: "${INITRD:=$BUILD/initramfs.cpio.gz}"
: "${QEMU_BIN:=$QEMU_BUILD/qemu-system-aarch64}"
: "${KDIR:=$KERNEL_BUILD}"

export ARCH CROSS_COMPILE JOBS EXTERNAL BUILD

log()  { printf '  %s\n' "$*"; }
die()  { printf '错误：%s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# ---- QEMU patch 队列 ----
qemu_series_path() {
	printf '%s\n' "$LAB_ROOT/env/qemu/series/$QEMU_SERIES"
}

qemu_expected_patches() {
	local series
	series=$(qemu_series_path)
	[ -f "$series" ] || { echo 0; return; }
	awk '!/^[[:space:]]*(#|$)/ { n++ } END { print n + 0 }' "$series"
}

qemu_apply_series() {
	local series line patch n=0
	series=$(qemu_series_path)
	[ -f "$series" ] || die "找不到 patch 队列：$series"

	while IFS= read -r line || [ -n "$line" ]; do
		line=${line%%#*}
		line=$(printf '%s' "$line" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')
		[ -z "$line" ] && continue
		patch="$LAB_ROOT/env/qemu/patches/$QEMU_SERIES/$line"
		[ -f "$patch" ] || die "patch 不存在：$patch"
		log "应用 $line"
		git -C "$QEMU_SRC" -c user.name=lab -c user.email=lab@localhost \
			am -q --3way "$patch" ||
			die "应用 $line 失败；在 $QEMU_SRC 解决后 make env-qemu-export"
		n=$((n + 1))
	done < "$series"

	[ "$n" -gt 0 ] || die "patch 队列为空：$series"
}
