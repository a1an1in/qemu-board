#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
#
# 启动 QEMU（arm64 virt + busybox initramfs）做驱动上机验证。
#
# 默认路径全部来自 recipe / build/，也可以用环境变量覆盖：
#   QEMU=/path/qemu-system-aarch64  KDIR=/path/kernel-build
#   INITRD=/path/initramfs.cpio.gz  KMODS_ROOT=/path/linux-kmods
#
# 前置结论（见 doc/hwmon/i2c-tmp105/设计文档.md §7、§11.1）：
#   自研 QEMU 的 virt 机器已内置 i2c@9060000/tmp105@48 等设备，并自动生成 FDT。
#   所以默认**不传 -dtb**；只有需要自备 DTB 时才设置 DTB=...
#
# 进入客户机后：
#   mount -t 9p -o trans=virtio,version=9p2000.L kmods /mnt
#   insmod /mnt/drivers/hwmon/i2c-tmp105/hwmon_i2c_tmp105.ko
#   sh /mnt/tests/hwmon/i2c-tmp105/read_hwmon.sh
#
# 动态改温度（两种方式）：
#   A) 带 QMP socket 启动，在另一个宿主终端：
#        QMP_SOCK=/tmp/tmp105.sock ./scripts/run_qemu.sh
#        python3 scripts/qmp_dev.py /tmp/tmp105.sock set --match tmp105 --value -6000
#        python3 scripts/qmp_dev.py /tmp/tmp105.sock get --match tmp105
#   B) 串口里 Ctrl-A c 切 monitor：
#        (qemu) qom-set /machine/unattached/device[10] temperature -6000
#      再 Ctrl-A c 切回。
#
# 完整手动步骤见 doc/<子系统>/<器件>/手动测试指南.md。
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=common.sh
. "$ROOT/scripts/common.sh"

QEMU=${QEMU:-$QEMU_BIN}
KDIR=${KDIR:-$KERNEL_BUILD}
KMODS_ROOT=${KMODS_ROOT:-$LAB_ROOT}
DTB=${DTB:-}
FLASH=${FLASH:-}
QMP_SOCK=${QMP_SOCK:-}

[ -x "$QEMU" ] || die "找不到 QEMU：$QEMU（先 make env-qemu 或设置 QEMU=）"
[ -f "$KDIR/arch/arm64/boot/Image" ] || die "找不到内核 Image：$KDIR/arch/arm64/boot/Image（先 make env-kernel）"
[ -f "$INITRD" ] || die "找不到 initramfs：$INITRD（先 make env-initramfs）"

args=(
	-M virt
	-cpu cortex-a57
	-m 2G
	-kernel "$KDIR/arch/arm64/boot/Image"
	-initrd "$INITRD"
	-nographic
	# 9p：把本工程源码树挂进客户机（改一次编一次，最方便）
	-virtfs "local,path=$KMODS_ROOT,mount_tag=kmods,security_model=none,id=kmods"
)

[ -n "$DTB" ] && args+=(-dtb "$DTB")
[ -n "$FLASH" ] && args+=(-drive "file=$FLASH,if=pflash,index=1,format=raw")
if [ -n "$QMP_SOCK" ]; then
	rm -f "$QMP_SOCK"
	args+=(-qmp "unix:$QMP_SOCK,server,nowait")
fi

args+=(-append "console=ttyAMA0 rdinit=/linuxrc")

echo "启动：$QEMU ${args[*]}"
[ -n "$QMP_SOCK" ] && echo "QMP：$QMP_SOCK（宿主侧：scripts/qmp_dev.py find/get/set --match <设备> --prop <属性>）"
echo "提示：串口里 Ctrl-A c 可切到 QEMU monitor（再按一次切回）"
exec "$QEMU" "${args[@]}" "$@"
