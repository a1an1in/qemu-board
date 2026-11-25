# env/qemu —— QEMU 定制 recipe

```
# 基线 commit 由 lab.conf 的 QEMU_BASE 指定（不要在这里再写一份）
configure.args        # configure 参数，一行一个
patches/<series>/     # 每个 series 一套 patch
series/<series>       # patch 顺序（一行一个文件名）
```

- `lab.conf` 的 `QEMU_BASE` / `QEMU_SERIES` 决定用哪个基线、哪套 series。
- 日常不要把 `external/qemu` 当成长期仓库；改动必须回流成 patch：
  ```sh
  python3 tools/devops.py qemu hack
  # 改代码、ninja -C build/qemu、python3 tools/devops.py run 验证
  git -C external/qemu commit -am "..."
  python3 tools/devops.py qemu export
  git add env/qemu && git commit -m "qemu: ..."
  ```
- 新增一套可选组合（例如只保留 I2C）：
  1. `cp env/qemu/series/base env/qemu/series/minimal`，删掉不需要的行；
  2. 在 `env/qemu/patches/minimal/` 放对应 patch（可以和 base 共享同一批文件内容）；
  3. `QEMU_SERIES=minimal python3 tools/devops.py qemu reset`。
- 升级上游：改 `lab.conf` 的 `QEMU_BASE`，然后
  `python3 tools/devops.py qemu rebase <新commit>`，解决冲突后
  `python3 tools/devops.py qemu export`。
