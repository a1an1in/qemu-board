# SPDX-License-Identifier: GPL-2.0
#
# linux-kmods 顶层 Makefile
#   1) 递归发现 drivers/**/Kbuild 做外部模块构建
#   2) 管理实验环境 recipe：QEMU / 内核 / busybox / initramfs
#
# 环境（首次）：
#   make env              # 下载/解包源码 + 打 QEMU patch
#   make env-build        # 编译 QEMU + 内核 + busybox + initramfs
#
# 日常：
#   make                  # 默认 KDIR=build/kernel，arm64 交叉编译
#   make KDIR=/lib/modules/$(uname -r)/build ARCH=x86_64 CROSS_COMPILE=   # 编本机
#   make run QMP_SOCK=/tmp/tmp105.sock
#   make verify
#   make clean            # 清理模块产物
#   make env-distclean    # 删除 build/ 和 external/（可重建）
#
# 目录/命名规则见 doc/开发规范.md：
#   drivers/<子系统>/<总线>-<器件>/{Kbuild,<子系统>_<总线>_<器件>.c}
# 新增驱动只要按规则建目录（含 Kbuild），本文件无需修改（递归发现，任意嵌套深度）。

KDIR		?= $(CURDIR)/build/kernel
ARCH		?= arm64
CROSS_COMPILE	?= aarch64-linux-gnu-
JOBS		?= $(shell nproc 2>/dev/null || echo 4)

PWD		:= $(shell pwd)
KBUILD_FLAGS	:= -C $(KDIR) ARCH=$(ARCH) CROSS_COMPILE=$(CROSS_COMPILE)

# 递归发现所有模块目录：任何包含 Kbuild 的目录都当作一个模块单元
MODULE_DIRS	:= $(shell find drivers -name Kbuild -printf '%h\n' 2>/dev/null | sort)

.PHONY: all modules clean list help \
	env env-fetch env-build env-qemu env-kernel env-busybox env-initramfs \
	run verify doctor \
	env-qemu-hack env-qemu-export env-qemu-reset env-qemu-rebase env-qemu-status \
	env-distclean

all: modules

modules:
	@if [ -z "$(MODULE_DIRS)" ]; then \
		echo "找不到任何模块目录（drivers/**/Kbuild）"; exit 1; \
	fi
	@for d in $(MODULE_DIRS); do \
		echo "=== 构建 $$d ==="; \
		$(MAKE) $(KBUILD_FLAGS) M=$(PWD)/$$d modules || exit 1; \
	done

clean:
	@for d in $(MODULE_DIRS); do \
		$(MAKE) $(KBUILD_FLAGS) M=$(PWD)/$$d clean; \
	done

list:
	@echo "$(MODULE_DIRS)" | tr ' ' '\n'

# ---- 实验环境 recipe ----

env: env-build

env-fetch:
	@$(CURDIR)/scripts/bootstrap.sh

env-build: env-fetch
	@$(CURDIR)/scripts/build_env.sh --jobs $(JOBS) all

env-qemu:
	@$(CURDIR)/scripts/build_env.sh --jobs $(JOBS) qemu

env-kernel:
	@$(CURDIR)/scripts/build_env.sh --jobs $(JOBS) kernel

env-busybox:
	@$(CURDIR)/scripts/build_env.sh busybox

env-initramfs:
	@$(CURDIR)/scripts/build_env.sh initramfs

run:
	@$(CURDIR)/scripts/run_qemu.sh

verify:
	@set -e; for t in $(CURDIR)/tests/*/*/verify_qemu.sh; do \
		echo; echo "=== $$t ==="; "$$t"; \
	done

doctor:
	@$(CURDIR)/scripts/bootstrap.sh --check

env-qemu-hack:
	@$(CURDIR)/scripts/qemu_hack.sh hack

env-qemu-export:
	@$(CURDIR)/scripts/qemu_hack.sh export

env-qemu-reset:
	@$(CURDIR)/scripts/qemu_hack.sh reset

env-qemu-rebase:
	@$(CURDIR)/scripts/qemu_hack.sh rebase $(BASE)

env-qemu-status:
	@$(CURDIR)/scripts/qemu_hack.sh status

env-distclean:
	@echo "删除 build/ 与 external/（可由 make env 重建）"
	rm -rf "$(CURDIR)/build" "$(CURDIR)/external"

help:
	@echo "模块构建："
	@echo "  make [KDIR=<内核树>] [ARCH=<arch>] [CROSS_COMPILE=<前缀>]"
	@echo "发现到的模块目录:"; $(MAKE) -s list
	@echo
	@echo "实验环境："
	@echo "  make env / env-build / env-qemu / env-kernel / env-busybox / env-initramfs"
	@echo "  make run [QMP_SOCK=/tmp/x.sock] / verify / doctor"
	@echo "  make env-qemu-hack|export|reset|status / env-distclean"
