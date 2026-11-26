# env/qemu —— QEMU 定制 recipe

```
# 基线 commit 由 lab.conf 的 QEMU_BASE 指定（不要在这里再写一份）
configure.args        # configure 参数，一行一个
patches/*.patch       # 自研 virt 补丁，按文件名 0001、0002... 顺序应用
```

- `lab.conf` 的 `QEMU_BASE` 决定基线；`env/qemu/patches/` 里的 patch 按文件名排序应用。
- `external/qemu` 的工作分支固定是 `master`（由 `init` 还原成 `base + patches`），
  日常直接在上面改；改动必须回流成 patch：
  ```sh
  python3 tools/devops.py init
  # 改代码、python3 tools/devops.py build qemu、手动启动 QEMU 验证
  git -C external/qemu commit -am "..."
  python3 tools/devops.py qemu patch
  git add env/qemu/patches && git commit -m "qemu: ..."
  ```
- 需要另一套补丁组合时，用 `QEMU_PATCH_DIR` 指向另一个目录：
  ```sh
  QEMU_PATCH_DIR=env/qemu/patches-spi python3 tools/devops.py qemu reset
  ```
- 升级上游：改 `lab.conf` 的 `QEMU_BASE`，然后
  `python3 tools/devops.py qemu rebase <新commit>`，解决冲突后
  `python3 tools/devops.py qemu patch`。
