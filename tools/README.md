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
| `build [all\|qemu\|kernel\|busybox\|initramfs]` | 编译。默认 `all`；全部 out-of-tree 到 `build/`。`--jobs N` |
| `modules` | 编译 `drivers/**` 外部模块。`--kdir`、`--arch`、`--cross-prefix`、`--sparse` |
| `run` | 启动 QEMU（9p 挂载仓库）。`--qmp`、`--dtb`、`--flash`、`--qemu`、`--kdir`、`--initrd`；`--` 之后可传额外 QEMU 参数 |
| `verify [子串]` | 依次运行 `tests/*/*/verify_qemu.sh`，可按名字过滤（如 `hwmon`） |
| `qemu status\|hack\|export\|reset\|rebase <base>` | QEMU 定制工作流；patch 队列是 `env/qemu/patches/<series>/` |
| `clean [modules\|env\|all]` | 清模块产物 / `build/` / `build/+external/`；非交互环境需 `--yes` |
| `status` | 查看版本、路径、产物和 QEMU 分支状态 |
| `list` | 列出会被构建的模块目录 |
| `help` | 帮助 |

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
| `QEMU_SERIES` | `base` | `env/qemu/series/<name>` |
| `JOBS` / `ARCH` / `CROSS_COMPILE` | `nproc` / `arm64` / `aarch64-linux-gnu-` | 编译参数 |
| `QEMU` / `INITRD` / `KMODS_ROOT` / `QMP_SOCK` | 由 recipe 推导 | `run` 覆盖 |

## 修改代码与生成补丁

先分清三种“代码”：

| 改什么 | 改哪里 | 怎么保存 | 需要生成 patch 吗 |
|---|---|---|---|
| 驱动 / 测试 / 文档 | `drivers/ test/ doc/`（本仓库） | `git add` + `git commit` | 不需要；正常 git 提交即可 |
| QEMU 设备模型 / virt 板级 | `external/qemu`（临时工作区） | `qemu export` → `env/qemu/patches/<series>/` | **需要**，patch 才是长期真相 |
| 内核代码 / busybox 代码 | `external/linux-*` / `external/busybox-*` | 目前只支持配置；代码补丁需在 `env/*/patches/` 加队列并在 `devops.py` 里应用 | 需要（当前未内置） |

### QEMU：改代码 → 导出补丁

```sh
python3 tools/devops.py init          # 首次
python3 tools/devops.py qemu hack     # 切到 external/qemu 的 lab/work
vim external/qemu/hw/arm/virt.c       # 改代码
ninja -C build/qemu qemu-system-aarch64
python3 tools/devops.py run           # 上机验证

git -C external/qemu add -A
git -C external/qemu commit -m "virt: add foo sensor at 0x4d"
python3 tools/devops.py qemu export   # 重写 env/qemu/patches/<series> 和 series
git add env/qemu/patches env/qemu/series
git commit -m "qemu: add foo sensor at 0x4d"
```

- `qemu export` 要求 `external/qemu` 工作区干净（先 commit），并按 `QEMU_BASE..lab/work`
  生成 patch；文件名来自 commit subject，顺序写入 `env/qemu/series/<series>`。
- `qemu export` 用 `git format-patch --zero-commit`，所以 patch 内容可复现。
- 只想临时分享未提交改动：`git -C external/qemu diff > /tmp/foo.patch`；但它**不会**
  进入 recipe，`init`/`qemu reset` 后就会消失。
- 验证 recipe 可重建：

```sh
python3 tools/devops.py qemu reset    # 回到 base + 当前 series
ninja -C build/qemu qemu-system-aarch64
python3 tools/devops.py verify
```

- 新增一套可选组合：复制 `series/base` 为 `series/<name>`，在
  `patches/<name>/` 放对应 patch，然后 `QEMU_SERIES=<name> python3 tools/devops.py qemu reset`。
- 升级 QEMU 基线：先改 `lab.conf` 的 `QEMU_BASE`，再
  `python3 tools/devops.py qemu rebase <新commit>`；冲突解决后
  `git -C external/qemu am --continue`，最后 `qemu export`。

### 驱动：直接改，正常 git 提交

```sh
vim drivers/chardev/i2c-tmp105/chardev_i2c_tmp105.c
python3 tools/devops.py modules
python3 tools/devops.py verify chardev
git add drivers/chardev/i2c-tmp105 doc tests
git commit -m "chardev_i2c_tmp105: ..."
```

驱动源码本来就在总仓里，不需要 `env/` patch；如果要给内核上游发补丁，再用标准
`git format-patch -1 HEAD` 生成邮件补丁。

### 内核 / busybox 代码

- 只改配置：改 `env/kernel/arm64-virt.config` 或 `env/busybox/busybox.config`，
  删掉 `build/*/.config` 后重新 `build kernel|busybox`。
- 改源码：`external/` 是可重建的，不能作为长期保存位置。建议在
  `env/kernel/patches/`（或 `env/busybox/patches/`）建 patch 队列，并在
  `tools/devops.py` 的 `prepare_kernel()` / `build_busybox()` 里用
  `git apply`/`patch -p1` 应用；当前 recipe 还没有内置这一步，需要时再加。

## 示例

```sh
python3 tools/devops.py doctor
python3 tools/devops.py init
python3 tools/devops.py build --jobs 8
python3 tools/devops.py modules
python3 tools/devops.py run --qmp /tmp/tmp105.sock
python3 tools/devops.py verify hwmon
python3 tools/devops.py qemu status
python3 tools/devops.py clean all --yes
```

> recipe 的边界不变：`env/` 进 git（版本/配置/patch/overlay），`external/` 和
> `build/` 不进 git，可随时由 `init`/`build` 重建。
