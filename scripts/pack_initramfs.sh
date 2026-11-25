#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
#
# 从 build/rootfs（busybox install 产物 + overlay）打 initramfs.cpio.gz。
# 用内核自带的 usr/gen_init_cpio 生成 cpio，因此不需要 root/fakeroot 也能
# 写入 /dev/console、/dev/null 这类设备节点。
#
#   ./scripts/pack_initramfs.sh
#   ROOTFS=... INITRD=... ./scripts/pack_initramfs.sh
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=common.sh
. "$ROOT/scripts/common.sh"

[ -x "$ROOTFS/bin/busybox" ] || die "找不到 $ROOTFS/bin/busybox：先 make env-busybox"
[ -f "$KERNEL_SRC/usr/gen_init_cpio.c" ] || die "找不到内核的 usr/gen_init_cpio.c"

log "准备 rootfs 骨架：$ROOTFS"
mkdir -p "$ROOTFS"/dev "$ROOTFS"/proc "$ROOTFS"/sys "$ROOTFS"/tmp \
	"$ROOTFS"/etc/init.d "$ROOTFS"/lib

if [ -d "$LAB_ROOT/env/busybox/rootfs-overlay" ]; then
	log "复制 rootfs overlay"
	cp -a "$LAB_ROOT/env/busybox/rootfs-overlay/." "$ROOTFS/"
fi
chmod 1777 "$ROOTFS/tmp"

# 内核 rdinit=/linuxrc（busybox init）
ln -sfn bin/busybox "$ROOTFS/linuxrc"

log "复制交叉工具链运行库"
for lib in ld-linux-aarch64.so.1 libc.so.6 libm.so.6 libresolv.so.2; do
	src=$("${CROSS_COMPILE}gcc" -print-file-name="$lib")
	[ -f "$src" ] || die "工具链里找不到 $lib（$CROSS_COMPILE）"
	cp -L "$src" "$ROOTFS/lib/$lib"
done

GEN="$BUILD/gen_init_cpio"
if [ ! -x "$GEN" ] || [ "$KERNEL_SRC/usr/gen_init_cpio.c" -nt "$GEN" ]; then
	log "编译 gen_init_cpio"
	gcc -O2 -o "$GEN" "$KERNEL_SRC/usr/gen_init_cpio.c"
fi

LIST="$BUILD/initramfs.list"
log "生成 cpio 清单：$LIST"
python3 - "$ROOTFS" > "$LIST" <<'PY'
import os
import stat
import sys

top = sys.argv[1]


def mode(p):
	return stat.S_IMODE(os.lstat(p).st_mode)


print("dir / 755 0 0")

for root, dirs, files in os.walk(top):
	dirs.sort()
	files.sort()
	rel = os.path.relpath(root, top)
	parts = [] if rel == "." else rel.split(os.sep)
	if rel != ".":
		print("dir /%s %o 0 0" % (rel.replace(os.sep, "/"), mode(root)))

	for name in files:
		path = "/".join(parts + [name]) if parts else name
		host = os.path.join(root, name)
		st = os.lstat(host)
		if stat.S_ISLNK(st.st_mode):
			print("slink /%s %s %o 0 0" %
				(path, os.readlink(host), mode(host)))
		elif stat.S_ISREG(st.st_mode):
			print("file /%s %s %o 0 0" % (path, host, mode(host)))
		# 设备节点/管道由下面显式生成（也兼容已有 rootfs 里没有节点的情况）

print("nod /dev/console 600 0 0 c 5 1")
print("nod /dev/null 666 0 0 c 1 3")
PY

[ -f "$ROOTFS/etc/inittab" ] || die "rootfs 缺 /etc/inittab（overlay 没复制成功？）"

log "打包 $INITRD"
"$GEN" "$LIST" | gzip -9 -n > "$INITRD.tmp"
mv -f "$INITRD.tmp" "$INITRD"

count=$(zcat "$INITRD" | cpio -it 2>/dev/null | wc -l)
log "完成：$INITRD（$count 项，$(du -h "$INITRD" | cut -f1)）"
