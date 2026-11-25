#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
#
# 按 recipe 编译实验环境。产物全部落在 build/，源码树保持干净。
#
#   ./scripts/build_env.sh              # 全部（qemu + kernel + busybox + initramfs）
#   ./scripts/build_env.sh qemu         # 只编 QEMU（增量）
#   ./scripts/build_env.sh kernel       # 只编内核 Image + modules + modules_prepare
#   ./scripts/build_env.sh busybox      # 只编 busybox 并安装到 build/rootfs
#   ./scripts/build_env.sh initramfs    # 只重打 initramfs
#   ./scripts/build_env.sh --jobs 8 all
#
# 注意：改了 env/qemu/configure.args 后需要删掉 build/qemu 再配置。
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=common.sh
. "$ROOT/scripts/common.sh"

WHAT=all
case "${1:-all}" in
--jobs)	JOBS=$2; shift 2 ;;
esac
WHAT=${1:-all}

build_qemu() {
	local cargs=()

	[ -d "$QEMU_SRC/.git" ] || die "先运行 ./scripts/bootstrap.sh"
	[ -n "$(git -C "$QEMU_SRC" status --porcelain)" ] &&
		log "警告：QEMU 工作区有未提交改动，按当前工作区编译"

	mkdir -p "$QEMU_BUILD"
	if [ ! -f "$QEMU_BUILD/build.ninja" ]; then
		mapfile -t cargs < <(sed -e 's/#.*//' -e '/^[[:space:]]*$/d' \
			"$LAB_ROOT/env/qemu/configure.args")
		log "配置 QEMU（${cargs[*]}）"
		(
			cd "$QEMU_BUILD"
			"$QEMU_SRC/configure" "${cargs[@]}"
		)
	fi
	log "编译 QEMU（-j$JOBS）"
	ninja -C "$QEMU_BUILD" -j "$JOBS" qemu-system-aarch64
	log "产物：$QEMU_BIN"
}

build_kernel() {
	[ -f "$KERNEL_SRC/Makefile" ] || die "先运行 ./scripts/bootstrap.sh"
	[ -f "$KERNEL_SRC/.config" ] &&
		die "$KERNEL_SRC 不是干净源码（有 .config）；recipe 要求 O= 外部构建，删除该目录后重试"

	mkdir -p "$KERNEL_BUILD"
	if [ ! -f "$KERNEL_BUILD/.config" ]; then
		cp -f "$LAB_ROOT/env/kernel/arm64-virt.config" "$KERNEL_BUILD/.config"
		log "写入内核配置：$KERNEL_BUILD/.config"
	fi

	log "内核 olddefconfig"
	make -C "$KERNEL_SRC" O="$KERNEL_BUILD" ARCH="$ARCH" \
		CROSS_COMPILE="$CROSS_COMPILE" olddefconfig
	log "编译内核 Image + modules（-j$JOBS）"
	make -C "$KERNEL_SRC" O="$KERNEL_BUILD" ARCH="$ARCH" \
		CROSS_COMPILE="$CROSS_COMPILE" -j "$JOBS" Image modules
	# 外部模块构建需要的 scripts/ 与头文件
	make -C "$KERNEL_SRC" O="$KERNEL_BUILD" ARCH="$ARCH" \
		CROSS_COMPILE="$CROSS_COMPILE" modules_prepare >/dev/null
	log "产物：$KERNEL_BUILD/arch/arm64/boot/Image"
	log "KDIR：$KERNEL_BUILD（可直接给 make/module 用）"
}

build_busybox() {
	local blog

	[ -f "$BUSYBOX_SRC/Makefile" ] || die "先运行 ./scripts/bootstrap.sh"
	[ -f "$BUSYBOX_SRC/.config" ] &&
		die "$BUSYBOX_SRC 不是干净源码（有 .config）；recipe 要求 O= 外部构建，删除该目录后重试"

	mkdir -p "$BUSYBOX_BUILD"
	cp -f "$LAB_ROOT/env/busybox/busybox.config" "$BUSYBOX_BUILD/.config"
	blog="$BUSYBOX_BUILD/build.log"

	log "busybox oldconfig"
	if ! make -C "$BUSYBOX_SRC" O="$BUSYBOX_BUILD" \
		ARCH="$ARCH" CROSS_COMPILE="$CROSS_COMPILE" \
		oldconfig </dev/null >"$blog" 2>&1; then
		tail -30 "$blog"
		die "busybox oldconfig 失败（日志 $blog）"
	fi
	log "编译并安装 busybox 到 $ROOTFS（-j$JOBS）"
	if ! make -C "$BUSYBOX_SRC" O="$BUSYBOX_BUILD" \
		ARCH="$ARCH" CROSS_COMPILE="$CROSS_COMPILE" \
		-j "$JOBS" >>"$blog" 2>&1; then
		tail -50 "$blog"
		die "busybox 编译失败（日志 $blog）"
	fi
	rm -rf "$ROOTFS"
	mkdir -p "$ROOTFS"
	if ! make -C "$BUSYBOX_SRC" O="$BUSYBOX_BUILD" \
		CONFIG_PREFIX="$ROOTFS" install >>"$blog" 2>&1; then
		tail -30 "$blog"
		die "busybox install 失败（日志 $blog）"
	fi
	log "产物：$ROOTFS/bin/busybox"
}

build_initramfs() {
	[ -x "$ROOTFS/bin/busybox" ] || die "还没有 busybox：先 make env-busybox"
	"$LAB_ROOT/scripts/pack_initramfs.sh"
}

case "$WHAT" in
all)
	build_qemu
	build_kernel
	build_busybox
	build_initramfs
	;;
qemu)		build_qemu ;;
kernel)		build_kernel ;;
busybox)	build_busybox ;;
initramfs)	build_initramfs ;;
*)		die "未知目标：$WHAT（all|qemu|kernel|busybox|initramfs）" ;;
esac
