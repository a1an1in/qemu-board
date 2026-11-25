#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
#
# 按 recipe 还原实验环境：下载/解包内核与 busybox，浅拉 QEMU 基线并打 patch。
# 只准备源码和配置，不编译（编译见 scripts/build_env.sh / make env-build）。
#
#   ./scripts/bootstrap.sh              # 首次准备（可重复执行）
#   ./scripts/bootstrap.sh --check      # 只检查宿主依赖（make doctor）
#   ./scripts/bootstrap.sh --reset      # 丢弃 external/qemu 的本地改动后重建
#   ./scripts/bootstrap.sh --skip-qemu  # 只准备内核/busybox
#
# 环境变量：EXTERNAL / BUILD / QEMU_SRC / QEMU_SERIES / KERNEL_SRC / BUSYBOX_SRC
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=common.sh
. "$ROOT/scripts/common.sh"

CHECK=0
RESET=0
SKIP_QEMU=0
SKIP_KERNEL=0
SKIP_BUSYBOX=0

usage() {
	sed -n '2,14p' "$0"
}

while [ $# -gt 0 ]; do
	case "$1" in
	--check)	CHECK=1 ;;
	--reset)	RESET=1 ;;
	--skip-qemu)	SKIP_QEMU=1 ;;
	--skip-kernel)	SKIP_KERNEL=1 ;;
	--skip-busybox)	SKIP_BUSYBOX=1 ;;
	--jobs)		JOBS=$2; shift ;;
	-h|--help)	usage; exit 0 ;;
	*)		die "未知参数：$1（--help 查看用法）" ;;
	esac
	shift
done

doctor() {
	local missing=0

	check() {
		if have "$1"; then
			printf '  [OK]   %s\n' "$1"
		else
			printf '  [MISS] %s\n' "$1"
			missing=1
		fi
	}

	printf '== 必需工具 ==\n'
	for c in git make gcc curl tar xz bzip2 gzip sha256sum cpio python3 ninja bc; do
		check "$c"
	done
	check "$CROSS_COMPILE"gcc

	printf '== QEMU 构建依赖 ==\n'
	if have pkg-config && pkg-config --exists glib-2.0 pixman-1 2>/dev/null; then
		printf '  [OK]   glib-2.0 / pixman-1（pkg-config）\n'
	else
		printf '  [MISS] glib-2.0 / pixman-1 开发包（libglib2.0-dev libpixman-1-dev）\n'
		missing=1
	fi
	if python3 -c 'import venv' >/dev/null 2>&1; then
		printf '  [OK]   python3 venv（QEMU 用内置 wheel 建 meson 环境）\n'
	else
		printf '  [MISS] python3-venv\n'
		missing=1
	fi

	printf '== 可选工具 ==\n'
	for c in dtc mksquashfs meson flex bison; do
		if have "$c"; then
			printf '  [OK]   %s\n' "$c"
		else
			printf '  [--]   %s（仅部分场景需要）\n' "$c"
		fi
	done

	if [ "$missing" -ne 0 ]; then
		cat <<'EOF'

Ubuntu/Debian 可一次装齐：
  sudo apt install build-essential git curl bc cpio xz-utils bzip2 gzip \
      python3 python3-venv ninja-build pkg-config libglib2.0-dev \
      libpixman-1-dev gcc-aarch64-linux-gnu
EOF
		return 1
	fi
	return 0
}

if [ "$CHECK" -eq 1 ]; then
	doctor
	exit $?
fi

log "检查宿主依赖"
doctor || die "依赖不全，按上面的提示安装后重试"

mkdir -p "$EXTERNAL" "$BUILD"

# fetch_tarball <url> <sha256>：解包到 $EXTERNAL/<name>，已存在则复用
fetch_tarball() {
	local url=$1 sha=$2 base name src tarball

	base=$(basename "$url")
	name=${base%.tar.*}
	src="$EXTERNAL/$name"

	if [ -f "$src/Makefile" ]; then
		log "复用已有源码：$src"
		return 0
	fi
	[ -e "$src" ] && die "$src 已存在但不像完整源码树（缺 Makefile），请先删除"

	mkdir -p "$EXTERNAL/.cache"
	tarball="$EXTERNAL/.cache/$base"
	if [ ! -f "$tarball" ]; then
		log "下载 $base"
		curl -fL --retry 3 --connect-timeout 20 --silent --show-error \
			-o "$tarball.part" "$url"
		mv "$tarball.part" "$tarball"
	fi
	log "校验 $base"
	printf '%s  %s\n' "$sha" "$tarball" | sha256sum -c - >/dev/null ||
		die "$base 的 sha256 不匹配（删除 $tarball 后重试）"

	log "解包 $base"
	tar -xf "$tarball" -C "$EXTERNAL"
	[ -f "$src/Makefile" ] || die "解包后找不到 $src/Makefile"
}

prepare_kernel() {
	[ -f "$KERNEL_SRC/Makefile" ] || die "内核源码不完整：$KERNEL_SRC"
	[ -f "$KERNEL_SRC/.config" ] &&
		die "$KERNEL_SRC 里有 in-tree 构建产物（.config）；recipe 用 O= 外部构建，要求干净源码。请删除该目录后重试"
	mkdir -p "$KERNEL_BUILD"
	if [ ! -f "$KERNEL_BUILD/.config" ] || [ "$RESET" -eq 1 ]; then
		cp -f "$LAB_ROOT/env/kernel/arm64-virt.config" "$KERNEL_BUILD/.config"
		log "写入内核配置：$KERNEL_BUILD/.config"
	fi
	log "内核源码：$KERNEL_SRC（编译目录 $KERNEL_BUILD）"
}

prepare_busybox() {
	[ -f "$BUSYBOX_SRC/Makefile" ] || die "busybox 源码不完整：$BUSYBOX_SRC"
	[ -f "$BUSYBOX_SRC/.config" ] &&
		die "$BUSYBOX_SRC 里有 in-tree 构建产物（.config）；recipe 用 O= 外部构建，要求干净源码。请删除该目录后重试"
	log "busybox 源码：$BUSYBOX_SRC（编译目录 $BUSYBOX_BUILD）"
}

prepare_qemu() {
	local actual expected filter_args=()

	if [ ! -d "$QEMU_SRC/.git" ]; then
		if [ -e "$QEMU_SRC" ] && [ -n "$(ls -A "$QEMU_SRC" 2>/dev/null)" ]; then
			die "$QEMU_SRC 已存在但不是 git 仓库；移走或删除后重试"
		fi
		log "初始化 QEMU 仓库（只取基线 $QEMU_BASE 所需对象）"
		mkdir -p "$QEMU_SRC"
		git -C "$QEMU_SRC" init -q
		git -C "$QEMU_SRC" remote add origin "$QEMU_URL"
	fi

	if [ "$RESET" -eq 0 ]; then
		[ -n "$(git -C "$QEMU_SRC" status --porcelain)" ] &&
			die "$QEMU_SRC 有未提交改动：先 make env-qemu-export 或 git stash，再重试（--reset 会丢弃）"

		if git -C "$QEMU_SRC" rev-parse --verify -q lab/work >/dev/null 2>&1; then
			actual=$(git -C "$QEMU_SRC" rev-list --count lab/work --not "$QEMU_BASE" 2>/dev/null || echo 0)
			expected=$(qemu_expected_patches)
			[ "$actual" -gt "$expected" ] &&
				die "lab/work 比 recipe 多 $((actual - expected)) 个提交：先 make env-qemu-export，或 --reset 丢弃"
		fi
	fi

	if ! git -C "$QEMU_SRC" cat-file -e "$QEMU_BASE^{commit}" 2>/dev/null; then
		[ -n "$QEMU_CLONE_FILTER" ] && filter_args=(--filter="$QEMU_CLONE_FILTER")
		log "拉取 QEMU 基线 ${QEMU_BASE:0:12}（${QEMU_CLONE_FILTER:-full}）"
		if ! git -C "$QEMU_SRC" fetch --depth 1 "${filter_args[@]}" origin "$QEMU_BASE"; then
			log "按 SHA 拉取失败，回退到 master 最近 $QEMU_FALLBACK_DEPTH 个提交"
			git -C "$QEMU_SRC" fetch --depth "$QEMU_FALLBACK_DEPTH" \
				"${filter_args[@]}" origin master ||
				die "无法拉取 QEMU，请检查网络或 QEMU_URL"
		fi
		git -C "$QEMU_SRC" cat-file -e "$QEMU_BASE^{commit}" 2>/dev/null ||
			die "基线 $QEMU_BASE 不在拉取结果里；调整 QEMU_BASE 或 QEMU_FALLBACK_DEPTH"
	fi

	git -C "$QEMU_SRC" checkout -q -f -B lab/work "$QEMU_BASE"
	git -C "$QEMU_SRC" reset -q --hard "$QEMU_BASE"
	if [ "$RESET" -eq 1 ]; then
		git -C "$QEMU_SRC" clean -q -fdx
	fi

	log "QEMU 源码：$QEMU_SRC（series=$QEMU_SERIES）"
	qemu_apply_series
}

[ "$SKIP_KERNEL" -eq 0 ] && {
	fetch_tarball "$KERNEL_URL" "$KERNEL_SHA256"
	prepare_kernel
}
[ "$SKIP_BUSYBOX" -eq 0 ] && {
	fetch_tarball "$BUSYBOX_URL" "$BUSYBOX_SHA256"
	prepare_busybox
}
[ "$SKIP_QEMU" -eq 0 ] && prepare_qemu

cat <<EOF

recipe 准备完成：
  内核      $KERNEL_SRC
  busybox   $BUSYBOX_SRC
  QEMU      $QEMU_SRC  (base ${QEMU_BASE:0:12}, series $QEMU_SERIES)
  构建目录  $BUILD

下一步：
  make env-build        # QEMU + 内核 + busybox + initramfs（首次 20~40 分钟）
  make env-qemu         # 只编 QEMU
  make env-kernel       # 只编内核（arm64 Image + Module.symvers）
  make env-initramfs    # 只重打 initramfs
  make run              # 起 QEMU
EOF
