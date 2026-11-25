# env/kernel —— 内核 recipe

- 版本由 `lab.conf` 的 `KERNEL_VERSION` 固定，源码从 `KERNEL_URL` 下载并按 `KERNEL_SHA256` 校验。
- `arm64-virt.config` 是完整 `.config`，`init` 会复制到 `build/kernel/.config`，编译前跑 `olddefconfig`。
- `env/kernel/patches/*.patch` 是内核代码补丁，按文件名 0001、0002... 顺序应用（默认没有）。
- `external/linux-*` 在 `init` 时建立本地 git 基线（`lab-base` 标签 + `dev` 分支）。

## 改内核代码 → 生成 patch（直接用 git）

```sh
python3 tools/devops.py init           # 首次：建立 lab-base 和 dev

cd external/linux-4.9.263
git checkout dev
vim drivers/...
git commit -am "my change"
rm -f ../../env/kernel/patches/*.patch
git format-patch --zero-commit --no-signature --no-numbered --full-index \
    -o ../../env/kernel/patches lab-base..dev
cd ../..
git add env/kernel/patches
git commit -m "kernel: my change"
```

看改动：

```sh
git -C external/linux-4.9.263 status
git -C external/linux-4.9.263 diff
git -C external/linux-4.9.263 diff lab-base..dev
```

重放/回退：

```sh
cd external/linux-4.9.263
git checkout -f -B dev lab-base
git clean -fdx
git am --3way ../../env/kernel/patches/*.patch
```

> 首次 `init` 会为内核源码建立本地 git 基线（提交整个源码树，约 1~2 分钟）。
> 不想用可以 `KERNEL_GIT=0 python3 tools/devops.py init` 跳过，之后自己 `git init`。
> `init` 仍会自动应用 `env/kernel/patches/*.patch`。

内核构建：
`python3 tools/devops.py build kernel`，产物在 `build/kernel/`，驱动默认
`KDIR=build/kernel`。
