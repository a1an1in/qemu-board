#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
#
# QEMU 定制工作流：在 external/qemu 的 lab/work 分支上改，改完导出为 patch。
# patch 队列（env/qemu/patches/<series>/ + env/qemu/series/<series>）才是长期真相。
#
#   ./scripts/qemu_hack.sh hack             # 切到 lab/work（不存在则从基线重放 patch）
#   ./scripts/qemu_hack.sh export           # 把 lab/work 的提交导出成当前 series 的 patch
#   ./scripts/qemu_hack.sh reset            # 丢弃本地改动，回到 base + 当前 series
#   ./scripts/qemu_hack.sh rebase <新base>  # 换基线并重放当前 series（冲突时停住）
#   ./scripts/qemu_hack.sh status           # 看当前版本/补丁/脏文件
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=common.sh
. "$ROOT/scripts/common.sh"

MODE=${1:-status}
[ $# -gt 0 ] && shift

need_repo() {
	[ -d "$QEMU_SRC/.git" ] || die "先运行 ./scripts/bootstrap.sh"
}

case "$MODE" in
hack)
	need_repo
	if git -C "$QEMU_SRC" show-ref --verify --quiet refs/heads/lab/work; then
		git -C "$QEMU_SRC" checkout -q lab/work
	else
		log "创建 lab/work 并重放当前 series"
		git -C "$QEMU_SRC" checkout -q -B lab/work "$QEMU_BASE"
		qemu_apply_series
	fi
	cat <<EOF
已切到 $QEMU_SRC 的 lab/work。
修改并 commit 后执行：make env-qemu-export
增量编译：ninja -C $QEMU_BUILD qemu-system-aarch64
EOF
	;;
export)
	need_repo
	[ -z "$(git -C "$QEMU_SRC" status --porcelain)" ] ||
		die "有未提交改动，先 git -C $QEMU_SRC commit（否则不会被导出）"
	git -C "$QEMU_SRC" rev-parse --verify -q lab/work >/dev/null ||
		die "没有 lab/work 分支；先 make env-qemu-hack"
	git -C "$QEMU_SRC" merge-base --is-ancestor "$QEMU_BASE" lab/work ||
		die "lab/work 不是基于 QEMU_BASE=$QEMU_BASE；先更新 lab.conf 或 rebase"

	pdir="$LAB_ROOT/env/qemu/patches/$QEMU_SERIES"
	mkdir -p "$pdir"
	rm -f "$pdir"/*.patch

	count=$(git -C "$QEMU_SRC" rev-list --count "$QEMU_BASE..lab/work")
	[ "$count" -gt 0 ] || die "lab/work 相对基线没有提交，无可导出内容"

	log "导出 $count 个 commit 到 $pdir"
	git -C "$QEMU_SRC" format-patch --zero-commit --no-signature -o "$pdir" \
		"$QEMU_BASE..lab/work" >/dev/null
	(
		cd "$pdir"
		ls -1 ./*.patch | sed 's#^\./##'
	) > "$(qemu_series_path)"

	printf '\n已更新 series %s：\n' "$QEMU_SERIES"
	sed 's/^/  /' "$(qemu_series_path)"
	echo
	echo "记得把 env/qemu/patches 和 series 一起提交到总仓。"
	;;
reset)
	need_repo
	log "重置 lab/work 到 $QEMU_BASE 并重放 series $QEMU_SERIES"
	git -C "$QEMU_SRC" checkout -q -f -B lab/work "$QEMU_BASE"
	git -C "$QEMU_SRC" reset -q --hard "$QEMU_BASE"
	git -C "$QEMU_SRC" clean -q -fdx
	qemu_apply_series
	;;
rebase)
	NEW=${1:-}
	[ -n "$NEW" ] || die "用法：$0 rebase <新 base commit>"
	need_repo
	git -C "$QEMU_SRC" cat-file -e "$NEW^{commit}" 2>/dev/null ||
		die "找不到 commit：$NEW（先 git -C $QEMU_SRC fetch）"
	log "切到新基线 $NEW 并重放 series $QEMU_SERIES"
	git -C "$QEMU_SRC" checkout -q -f -B lab/work "$NEW"
	git -C "$QEMU_SRC" reset -q --hard "$NEW"
	qemu_apply_series
	cat <<EOF

重放成功。请手动更新 lab.conf：
  QEMU_BASE=$NEW
然后执行：
  make env-qemu-export
  make verify
EOF
	;;
status)
	need_repo
	printf '仓库      %s\n' "$QEMU_SRC"
	printf 'recipe    base=%s series=%s (%s 个 patch)\n' \
		"$QEMU_BASE" "$QEMU_SERIES" "$(qemu_expected_patches)"
	git -C "$QEMU_SRC" rev-parse --abbrev-ref HEAD 2>/dev/null |
		sed 's/^/分支      /'
	git -C "$QEMU_SRC" log --oneline -"$(qemu_expected_patches)" 2>/dev/null | sed 's/^/  /'
	printf '工作区    '
	if [ -n "$(git -C "$QEMU_SRC" status --porcelain)" ]; then
		echo "有未提交改动"
	else
		echo "干净"
	fi
	;;
*)
	sed -n '2,12p' "$0"
	exit 1
	;;
esac
