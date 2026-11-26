# SPDX-License-Identifier: GPL-2.0
#
# linux-kmods 顶层 Makefile —— 薄封装，实际实现统一在 tools/devops.py
#
# 推荐直接使用 Python 入口（跨平台，Windows 下会自动转交 WSL）：
#   python3 tools/devops.py doctor
#   python3 tools/devops.py init
#   python3 tools/devops.py build
#   python3 tools/devops.py build drivers
#   python3 tools/devops.py verify
#   python3 tools/devops.py qemu status|diff|patch|reset|rebase
#
# 本文件保留 make 兼容入口，所有 target 都转调 tools/devops.py。

PYTHON		?= python3
DEVOPS		:= $(PYTHON) $(CURDIR)/tools/devops.py

KDIR		?= $(CURDIR)/build/kernel
ARCH		?= arm64
CROSS_COMPILE	?= aarch64-linux-gnu-
JOBS		?= $(shell nproc 2>/dev/null || echo 4)

MODULE_DIRS	:= $(shell find drivers -name Kbuild -printf '%h\n' 2>/dev/null | sort)

.PHONY: all modules clean list help \
	env env-fetch env-build env-qemu env-kernel env-busybox env-initramfs \
	verify doctor \
	env-qemu-hack env-qemu-export env-qemu-reset env-qemu-rebase env-qemu-status \
	env-qemu-patch \
	env-distclean

all: modules

modules:
	@$(DEVOPS) build drivers --kdir "$(KDIR)" --arch "$(ARCH)" \
		--cross-prefix "$(CROSS_COMPILE)" --jobs $(JOBS)

clean:
	@$(DEVOPS) clean drivers --yes --kdir "$(KDIR)"

list:
	@$(DEVOPS) list

# ---- 实验环境 recipe ----

env: env-build

env-fetch:
	@$(DEVOPS) init

env-build: env-fetch
	@$(DEVOPS) build all --jobs $(JOBS)

env-qemu:
	@$(DEVOPS) build qemu --jobs $(JOBS)

env-kernel:
	@$(DEVOPS) build kernel --jobs $(JOBS)

env-busybox:
	@$(DEVOPS) build busybox --jobs $(JOBS)

env-initramfs:
	@$(DEVOPS) build initramfs

verify:
	@$(DEVOPS) verify

doctor:
	@$(DEVOPS) doctor

env-qemu-patch:
	@$(DEVOPS) qemu patch

# 源码树统一在 master 上开发；这里只确保 external/qemu == base + patches
env-qemu-hack:
	@$(DEVOPS) init --skip-kernel --skip-busybox

env-qemu-export: env-qemu-patch

env-qemu-reset:
	@$(DEVOPS) qemu reset

env-qemu-rebase:
	@$(DEVOPS) qemu rebase $(BASE)

env-qemu-status:
	@$(DEVOPS) qemu status

env-distclean:
	@$(DEVOPS) clean all --yes

help:
	@echo "推荐：python3 tools/devops.py <命令>（Windows 用 python tools/devops.py）"
	@echo "  doctor / init / build [all|qemu|kernel|busybox|initramfs|drivers] [驱动路径]"
	@echo "  verify / qemu status|diff|patch|reset|rebase / clean / status / list"
	@echo
	@echo "make 兼容 target：env / env-build / verify / doctor / modules / clean"
	@echo "发现到的模块目录:"; $(DEVOPS) list
