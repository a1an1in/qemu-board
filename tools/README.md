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
