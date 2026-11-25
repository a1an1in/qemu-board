# env/kernel —— 内核 recipe

- 版本由 `lab.conf` 的 `KERNEL_VERSION` 固定，源码从 `KERNEL_URL` 下载并按 `KERNEL_SHA256` 校验。
- `arm64-virt.config` 是完整 `.config`，`init` 会复制到 `build/kernel/.config`，编译前跑 `olddefconfig`。
- `env/kernel/patches/*.patch` 是内核代码补丁，按文件名 0001、0002... 顺序应用（默认没有）。
- `external/linux-*` 在 `init` 时建立本地 git 基线（`lab-base` 标签），方便看 diff 和生成 patch。

## 改内核代码 → 生成 patch

```sh
python3 tools/devops.py init           # 首次：建立 lab-base 基线
python3 tools/devops.py kernel checkout
vim external/linux-4.9.263/drivers/...
git -C external/linux-4.9.263 commit -am "my change"
python3 tools/devops.py kernel patch   # → env/kernel/patches/*.patch
git add env/kernel/patches
git commit -m "kernel: my change"
```

查看改动：

```sh
python3 tools/devops.py kernel status
python3 tools/devops.py kernel diff          # stat + 文件列表
python3 tools/devops.py kernel diff --full   # 完整 diff
```

验证 recipe 可重建：

```sh
python3 tools/devops.py kernel reset
python3 tools/devops.py build kernel
```

> 首次 `init` 会为内核源码建立一个本地 git 基线（提交整个源码树，约 1~2 分钟）。
> 不想用可以 `KERNEL_GIT=0 python3 tools/devops.py init` 跳过，但 `kernel` 子命令将不可用；
> `build kernel` 仍然可用。

内核构建产物在 `build/kernel/`，`modules` 默认 `KDIR=build/kernel`。
