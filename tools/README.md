# tools/devops.py —— 统一入口

`tools/devops.py` 是本工程唯一的构建/运维入口（纯 Python 3，跨平台）：

```sh
python3 tools/devops.py <命令> [选项]
```

- **Linux / WSL / macOS**：直接执行。
- **Windows**：用 `python tools/devops.py ...`（或 `py`），脚本会自动把命令转交给
  仓库所在的 WSL 发行版执行；仓库放在 `\\wsl.localhost\<distro>\...` 或普通 Windows
  路径都可以（后者用 `wslpath` 映射）。
- `--no-wsl` 可禁止 Windows 自动转交（调试用）。

## 命令

| 命令 | 作用 |
|---|---|
| `doctor` | 检查宿主依赖（git/make/gcc/aarch64-gcc/ninja/glib/pixman/bc/perl…） |
| `init` | 按 `lab.conf` + `env/` 还原 recipe：下载/校验/解包内核与 busybox，浅拉 QEMU 基线并打 patch。`--reset` 丢弃 `external/qemu` 本地改动；`--skip-qemu/--skip-kernel/--skip-busybox` 跳过部分 |
| `build [all\|qemu\|kernel\|busybox\|initramfs\|drivers] [驱动路径]` | 编译。默认 `all`（环境四件套）；`build drivers` 编全部 `drivers/**`，也可 `build drivers/chardev`、`build drivers/chardev/i2c-tmp105` 只编某一个。`--jobs/--kdir/--arch/--cross-prefix/--sparse` |
| `verify [子串]` | 依次运行 `tests/*/*/verify_qemu.sh`，可按名字过滤（如 `hwmon`） |
| `qemu status\|diff\|checkout\|patch\|reset\|rebase <base>` | QEMU 定制工作流；patch 目录是 `env/qemu/patches/`（按文件名排序） |
| `clean [drivers\|env\|all]` | 清驱动产物 / `build/` / `build/+external/`；非交互环境需 `--yes` |
| `status` | 查看版本、路径、产物和 QEMU 分支状态 |
| `list` | 列出会被构建的模块目录 |
| `help` | 帮助 |

> 内核代码不用 `devops.py` 管，直接 `git -C external/linux-* ...`。

## 环境变量

与 recipe 一致，均可覆盖默认路径：

| 变量 | 默认 | 说明 |
|---|---|---|
| `EXTERNAL` | `external/` | 源码树缓存 |
| `BUILD` | `build/` | 构建产物 |
| `QEMU_SRC` / `QEMU_BUILD` | `external/qemu` / `build/qemu` | QEMU 源码/构建目录 |
| `KERNEL_SRC` / `KERNEL_BUILD` | `external/linux-<ver>` / `build/kernel` | 内核源码/构建目录 |
| `BUSYBOX_SRC` / `BUSYBOX_BUILD` | `external/busybox-<ver>` / `build/busybox` | busybox |
| `KDIR` | `build/kernel` | 编外部模块用的内核树 |
| `QEMU_PATCH_DIR` | `env/qemu/patches` | 换一套 QEMU patch 目录（可选） |
| `KERNEL_PATCH_DIR` | `env/kernel/patches` | 换一套内核 patch 目录（可选） |
| `KERNEL_GIT` | `1` | 设为 `0` 跳过 `init` 建立内核 git 基线（之后需自己 `git init`） |
| `JOBS` / `ARCH` / `CROSS_COMPILE` | `nproc` / `arm64` / `aarch64-linux-gnu-` | 编译参数 |
| `QEMU` / `KDIR` / `INITRD` / `KMODS_ROOT` | 由 recipe 推导 | `verify` 脚本可直接用这些覆盖 |

## 修改代码与生成补丁

先分清三种“代码”：

| 改什么 | 改哪里 | 怎么保存 | 需要生成 patch 吗 |
|---|---|---|---|
| 驱动 / 测试 / 文档 | `drivers/ test/ doc/`（本仓库） | `git add` + `git commit` | 不需要；正常 git 提交即可 |
| QEMU 设备模型 / virt 板级 | `external/qemu`（临时工作区） | `qemu patch` → `env/qemu/patches/` | **需要**，patch 才是长期真相 |
| 内核代码 | `external/linux-*`（本地 git 基线） | 手动 `git format-patch` → `env/kernel/patches/` | **需要**，用 git 自己管 |
| busybox 代码 | `external/busybox-*` | 目前只支持配置/overlay；代码补丁需自己加队列 | 需要时再加 |

### 看改动了什么

```sh
python3 tools/devops.py qemu status        # base/patches/分支/最近提交/是否脏
python3 tools/devops.py qemu diff          # 相对基线的 stat + 文件列表
python3 tools/devops.py qemu diff --full   # 完整 diff
```

内核直接看 git：

```sh
git -C external/linux-4.9.263 status
git -C external/linux-4.9.263 diff
git -C external/linux-4.9.263 log --oneline lab-base..dev
```

也可以直接用 git（`external/qemu` 是完整仓库，`external/linux-*` 在 `init` 后也有
`lab-base`/`dev`）：

```sh
git -C external/qemu log --oneline dev
git -C external/qemu diff b428fe036233..dev -- hw/arm/virt.c

git -C external/linux-4.9.263 status
git -C external/linux-4.9.263 diff lab-base..dev
git -C external/linux-4.9.263 log --oneline lab-base..dev
```

### QEMU：改代码 → 导出补丁

```sh
python3 tools/devops.py init          # 首次
python3 tools/devops.py qemu checkout     # 切到 external/qemu 的 dev
vim external/qemu/hw/arm/virt.c       # 改代码
ninja -C build/qemu qemu-system-aarch64
python3 tools/devops.py build qemu           # 只编 QEMU（增量）

git -C external/qemu add -A
git -C external/qemu commit -m "virt: add foo sensor at 0x4d"
python3 tools/devops.py qemu patch   # 重写 env/qemu/patches/*.patch
git add env/qemu/patches
git commit -m "qemu: add foo sensor at 0x4d"
```

- `qemu checkout` 只做一件事：确保 `external/qemu` 在 `dev` 分支（不存在则从
  `QEMU_BASE` 创建并重放当前 patches）。它**不编译、不导出、不动内核**；
  已经在 `dev` 时基本是 no-op。
- `qemu patch` 要求 `external/qemu` 工作区干净（先 commit），并按 `QEMU_BASE..dev`
  生成 patch；文件名是 `0001-...` 这种，**文件名排序就是应用顺序**。
- `qemu patch` 用 `git format-patch --zero-commit`，所以 patch 内容可复现。
- 只想临时分享未提交改动：`git -C external/qemu diff > /tmp/foo.patch`；但它**不会**
  进入 recipe，`init`/`qemu reset` 后就会消失。
- 验证 recipe 可重建：

```sh
python3 tools/devops.py qemu reset    # 回到 base + 当前 patches
ninja -C build/qemu qemu-system-aarch64
python3 tools/devops.py verify
```

- 需要另一套补丁组合：把 patches 复制到另一个目录，用
  `QEMU_PATCH_DIR=env/qemu/patches-spi python3 tools/devops.py qemu reset` 切换。
- 升级 QEMU 基线：先改 `lab.conf` 的 `QEMU_BASE`，再
  `python3 tools/devops.py qemu rebase <新commit>`；冲突解决后
  `git -C external/qemu am --continue`，最后 `qemu patch`。

### 驱动：直接改，正常 git 提交

```sh
vim drivers/chardev/i2c-tmp105/chardev_i2c_tmp105.c
python3 tools/devops.py build drivers
python3 tools/devops.py verify chardev
git add drivers/chardev/i2c-tmp105 doc tests
git commit -m "chardev_i2c_tmp105: ..."
```

驱动源码本来就在总仓里，不需要 `env/` patch；如果要给内核上游发补丁，再用标准
`git format-patch -1 HEAD` 生成邮件补丁。

### 内核：直接用 git

```sh
python3 tools/devops.py init           # 首次：建立 lab-base 基线 + dev 分支

cd external/linux-4.9.263
git checkout dev                       # init 已建；不存在时 git checkout -b dev lab-base
vim drivers/...
git commit -am "my change"
rm -f ../../env/kernel/patches/*.patch
git format-patch --zero-commit --no-signature --no-numbered --full-index \
    -o ../../env/kernel/patches lab-base..dev
cd ../..
git add env/kernel/patches
git commit -m "kernel: my change"
```

重放/回退也直接用 git：

```sh
cd external/linux-4.9.263
git checkout -f -B dev lab-base
git clean -fdx
git am --3way ../../env/kernel/patches/*.patch
```

> 第一次 `init` 才会在 `external/linux-*` 里创建 `.git`。在此之前，`git -C
> external/linux-* status` 会向上找到总仓的 `.git`，看起来像 linux-kmods 的仓库，
> 这是正常的。`KERNEL_GIT=0` 可跳过基线，但之后要自己 `git init`。
> `init` 仍会把 `env/kernel/patches/*.patch` 应用到 `external/linux-*`。

### busybox 代码

- 只改配置/overlay：改 `env/busybox/busybox.config` 或 `rootfs-overlay/`，
  然后 `build busybox` + `build initramfs`。
- 改源码：目前 recipe 只内置了配置/overlay，没有 busybox patch 队列；需要时按
  `env/kernel/` 的模式补 `patches/` 并在 `build_busybox()` 里应用。

## 示例

```sh
python3 tools/devops.py doctor
python3 tools/devops.py init
python3 tools/devops.py build --jobs 8
python3 tools/devops.py build drivers
python3 tools/devops.py build drivers/chardev
python3 tools/devops.py build drivers/chardev/i2c-tmp105
python3 tools/devops.py build drivers/hwmon/i2c-tmp105
python3 tools/devops.py verify hwmon
python3 tools/devops.py qemu status
python3 tools/devops.py clean all --yes
```

> recipe 的边界不变：`env/` 进 git（版本/配置/patch/overlay），`external/` 和
> `build/` 不进 git，可随时由 `init`/`build` 重建。
