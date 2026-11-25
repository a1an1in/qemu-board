# env/kernel —— 内核 recipe

- 版本由 `lab.conf` 的 `KERNEL_VERSION` 固定，源码从 `KERNEL_URL` 下载并按 `KERNEL_SHA256` 校验。
- `arm64-virt.config` 是完整 `.config`，`init` 会复制到 `build/kernel/.config`，编译前跑 `olddefconfig`。
- 目前没有内核代码补丁；如果以后要改内核：
  1. 建 `env/kernel/patches/`，按 `series` 顺序放置；
  2. 在 `tools/devops.py` 的 `prepare_kernel()` / `build_kernel()` 里增加
     `git apply`/`patch -p1` 步骤；
  3. 仍然保持 `external/linux-*` 干净，方便整体升级。

内核构建产物在 `build/kernel/`，`modules` 默认 `KDIR=build/kernel`。
构建：`python3 tools/devops.py build kernel`。
