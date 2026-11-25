#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""linux-kmods 实验台统一入口（跨平台）。

在 Linux / WSL / macOS 里直接运行；在 Windows 下会自动把命令转交给 WSL
（仓库位于 \\\\wsl.localhost\\<distro>\\... 或普通 Windows 路径都可以）。

常用：
    python3 tools/devops.py doctor                 # 检查依赖
    python3 tools/devops.py init                   # 还原 recipe（下载/解包/patch）
    python3 tools/devops.py build                  # 编 QEMU + 内核 + busybox + initramfs
    python3 tools/devops.py build kernel           # 只编内核
    python3 tools/devops.py build drivers                # 编 drivers/** 外部模块
    python3 tools/devops.py build drivers/chardev        # 只编某个子系统
    python3 tools/devops.py build drivers/chardev/i2c-tmp105
    python3 tools/devops.py verify                 # 跑全部端到端测试
    python3 tools/devops.py qemu status|diff|checkout|patch|reset|rebase
    python3 tools/devops.py clean env|all          # 删构建产物/源码
    python3 tools/devops.py status                 # 看版本、路径、产物

recipe 的唯一真相仍然是 lab.conf + env/；源码在 external/，产物在 build/。
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
CONF: dict[str, str] = {}
VERBOSE = False


class DevopsError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------

def say(msg: str) -> None:
    print(f"\n[devops] {msg}", flush=True)


def info(msg: str) -> None:
    print(f"[devops] {msg}", flush=True)


def die(msg: str) -> None:
    raise DevopsError(msg)


def load_conf() -> None:
    path = ROOT / "lab.conf"
    if not path.exists():
        die(f"找不到 {path}")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        CONF[key.strip()] = value


def conf(key: str, default: str = "") -> str:
    return os.environ.get(key) or CONF.get(key, default)


def run(cmd, cwd=None, check=True, env=None, stdin=None, stdout=None,
        stderr=None):
    cmd = [str(c) for c in cmd]
    if VERBOSE:
        info("$ " + " ".join(shlex.quote(c) for c in cmd))
    try:
        return subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            check=check,
            env=env,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            text=False,
        )
    except FileNotFoundError:
        die(f"找不到命令：{cmd[0]}（先运行 python3 tools/devops.py doctor）")


def capture(cmd, cwd=None, check=True) -> str:
    cmd = [str(c) for c in cmd]
    if VERBOSE:
        info("$ " + " ".join(shlex.quote(c) for c in cmd))
    try:
        proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None,
                              capture_output=True, text=True)
    except FileNotFoundError:
        die(f"找不到命令：{cmd[0]}（先运行 python3 tools/devops.py doctor）")
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        die(f"命令失败：{' '.join(cmd)}\n{detail}")
    return proc.stdout.strip()


def which(name: str) -> str | None:
    return shutil.which(name)


def tail_file(path: Path, lines: int = 40) -> None:
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    for line in content[-lines:]:
        print("    " + line, flush=True)


# --------------------------------------------------------------------------
# 路径
# --------------------------------------------------------------------------

@dataclass
class Paths:
    external: Path
    build: Path
    qemu_src: Path
    qemu_build: Path
    kernel_src: Path
    kernel_build: Path
    busybox_src: Path
    busybox_build: Path
    rootfs: Path
    initrd: Path
    qemu_bin: Path


def env_path(key: str, default: Path) -> Path:
    value = os.environ.get(key)
    return Path(value).expanduser() if value else default


def load_paths() -> Paths:
    external = env_path("EXTERNAL", ROOT / "external")
    build = env_path("BUILD", ROOT / "build")
    kernel_ver = conf("KERNEL_VERSION")
    bb_ver = conf("BUSYBOX_VERSION")
    qemu_src = env_path("QEMU_SRC", external / "qemu")
    qemu_build = env_path("QEMU_BUILD", build / "qemu")
    kernel_src = env_path("KERNEL_SRC", external / f"linux-{kernel_ver}")
    kernel_build = env_path("KERNEL_BUILD", build / "kernel")
    busybox_src = env_path("BUSYBOX_SRC", external / f"busybox-{bb_ver}")
    busybox_build = env_path("BUSYBOX_BUILD", build / "busybox")
    rootfs = env_path("ROOTFS", build / "rootfs")
    initrd = env_path("INITRD", build / "initramfs.cpio.gz")
    qemu_bin = env_path("QEMU_BIN", qemu_build / "qemu-system-aarch64")
    return Paths(external, build, qemu_src, qemu_build, kernel_src,
                 kernel_build, busybox_src, busybox_build, rootfs, initrd,
                 qemu_bin)


def arch() -> str:
    return conf("ARCH", "arm64")


def cross() -> str:
    return conf("CROSS_COMPILE", "aarch64-linux-gnu-")


def jobs(default: int = 0) -> int:
    if default:
        return default
    value = conf("JOBS")
    if value.isdigit() and int(value) > 0:
        return int(value)
    return max(1, os.cpu_count() or 4)


# --------------------------------------------------------------------------
# 依赖检查
# --------------------------------------------------------------------------

APT_HINT = """\
Ubuntu/Debian 可一次装齐：
  sudo apt install build-essential git perl curl bc \\
      python3 python3-venv ninja-build pkg-config libglib2.0-dev \\
      libpixman-1-dev gcc-aarch64-linux-gnu
"""


def doctor() -> bool:
    say("检查宿主依赖")
    missing = 0

    def check(cmd: str, label: str | None = None) -> None:
        nonlocal missing
        label = label or cmd
        if which(cmd):
            print(f"  [OK]   {label}")
        else:
            print(f"  [MISS] {label}")
            missing += 1

    for cmd in ("git", "make", "gcc", "python3", "ninja", "bc"):
        check(cmd)
    check(f"{cross()}gcc")

    if which("pkg-config") and subprocess.run(
            ["pkg-config", "--exists", "glib-2.0", "pixman-1"]).returncode == 0:
        print("  [OK]   glib-2.0 / pixman-1（pkg-config）")
    else:
        print("  [MISS] glib-2.0 / pixman-1 开发包")
        missing += 1

    if subprocess.run([sys.executable, "-c", "import venv"],
                      capture_output=True).returncode == 0:
        print("  [OK]   python3 venv（QEMU 内置 wheel 建 meson 环境）")
    else:
        print("  [MISS] python3-venv")
        missing += 1

    for cmd, label in (("perl", "perl（checkpatch）"), ("dtc", "dtc（可选）"),
                       ("mksquashfs", "mksquashfs（可选）"),
                       ("flex", "flex（可选）"), ("bison", "bison（可选）")):
        if which(cmd):
            print(f"  [OK]   {label}")
        else:
            print(f"  [--]   {label}")

    if missing:
        print()
        print(APT_HINT)
        return False
    return True


# --------------------------------------------------------------------------
# 下载 / 解包
# --------------------------------------------------------------------------

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    info(f"下载 {dest.name}")
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(url, timeout=60) as response, \
                    tmp.open("wb") as handle:
                total = int(response.headers.get("Content-Length") or 0)
                done = 0
                last = 0
                while True:
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    if total and done - last >= (5 << 20):
                        last = done
                        info(f"  {done * 100 // total}%")
            tmp.replace(dest)
            return
        except (urllib.error.URLError, OSError) as exc:
            if attempt == 3:
                tmp.unlink(missing_ok=True)
                die(f"下载失败：{url}\n{exc}")
            info(f"下载失败（{exc}），重试 {attempt}/3 ...")
            time.sleep(2)


def safe_extract(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts:
                die(f"压缩包里有不安全路径：{member.name}")
            if member.isdev() or member.isfifo():
                continue
            tar.extract(member, dest)


def ensure_clean_source(source: Path, label: str) -> None:
    if (source / ".config").exists() or (source / "vmlinux").exists():
        die(f"{source} 有 in-tree 构建产物（.config/vmlinux）。\n"
            f"recipe 使用 O= 外部构建，要求干净源码；删除该目录后重试。")


def ensure_tarball(paths: Paths, name: str, url: str, sha: str,
                   reset: bool = False) -> Path:
    source = paths.external / name
    if (source / "Makefile").is_file() and not reset:
        ensure_clean_source(source, name)
        info(f"复用源码：{source}")
        return source
    if source.exists():
        if reset:
            shutil.rmtree(source)
        else:
            die(f"{source} 已存在但不像完整源码树（缺 Makefile）；"
                f"删除后重试，或加 --reset")

    cache = paths.external / ".cache" / Path(urllib.parse.urlparse(url).path).name
    if not cache.is_file():
        download(url, cache)
    info(f"校验 {cache.name}")
    actual = sha256(cache)
    if actual != sha:
        die(f"{cache.name} 的 sha256 不匹配\n  期望 {sha}\n  实际 {actual}")
    info(f"解包 {cache.name}")
    safe_extract(cache, paths.external)
    if not (source / "Makefile").is_file():
        die(f"解包后找不到 {source}/Makefile")
    return source


# --------------------------------------------------------------------------
# QEMU recipe
# --------------------------------------------------------------------------

def git_out(paths: Paths, *args: str) -> str:
    return capture(["git", "-C", str(paths.qemu_src), *args])


def git_ok(paths: Paths, *args: str) -> bool:
    proc = subprocess.run(["git", "-C", str(paths.qemu_src), *args],
                          capture_output=True)
    return proc.returncode == 0


def qemu_patch_dir() -> Path:
    value = os.environ.get("QEMU_PATCH_DIR")
    return Path(value).expanduser() if value else ROOT / "env" / "qemu" / "patches"


def patch_entries(patch_dir: Path) -> list[str]:
    """按文件名排序返回 patch（0001、0002... 就是执行顺序）。"""
    if patch_dir.is_dir():
        return sorted(item.name for item in patch_dir.glob("*.patch"))
    return []


def qemu_expected_patches() -> int:
    return len(patch_entries(qemu_patch_dir()))


def current_branch(repo: Path) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), "symbolic-ref", "--short", "-q", "HEAD"],
        capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def valid_branch(name: str) -> bool:
    return subprocess.run(["git", "check-ref-format", "--branch", name],
                          capture_output=True).returncode == 0


def migrate_work_branch(repo: Path) -> None:
    """兼容旧分支名 lab/work：存在且 dev 不存在时直接改名。"""
    if not (repo / ".git").exists():
        return

    def exists(name: str) -> bool:
        return subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", "-q",
             f"refs/heads/{name}"], capture_output=True).returncode == 0

    if not exists("dev") and exists("lab/work"):
        info("迁移旧分支 lab/work -> dev")
        run(["git", "-C", str(repo), "branch", "-m", "lab/work", "dev"])


def qemu_dirty(paths: Paths) -> bool:
    return bool(git_out(paths, "status", "--porcelain"))


def qemu_apply_patches(paths: Paths) -> None:
    entries = patch_entries(qemu_patch_dir())
    if not entries:
        info("没有 QEMU patch（只有基线）")
        return
    for line in entries:
        patch = qemu_patch_dir() / line
        if not patch.is_file():
            die(f"patch 不存在：{patch}")
        info(f"应用 {line}")
        proc = run(["git", "-C", str(paths.qemu_src),
                    "-c", "user.name=lab", "-c", "user.email=lab@localhost",
                    "am", "-q", "--3way", str(patch)], check=False)
        if proc.returncode != 0:
            die(f"应用 {line} 失败。\n"
                f"在 {paths.qemu_src} 解决冲突后执行 git am --continue，"
                f"或 python3 tools/devops.py qemu reset 放弃。")


def init_qemu(paths: Paths, reset: bool) -> None:
    q = paths.qemu_src
    if not (q / ".git").exists():
        if q.exists() and any(q.iterdir()):
            die(f"{q} 已存在但不是 git 仓库；移走或删除后重试")
        say("初始化 QEMU 仓库（只取基线所需对象）")
        q.mkdir(parents=True, exist_ok=True)
        run(["git", "init", "-q"], cwd=q)
        run(["git", "remote", "add", "origin", conf("QEMU_URL")], cwd=q)

    migrate_work_branch(q)

    if not reset:
        if qemu_dirty(paths):
            die(f"{q} 有未提交改动：先 python3 tools/devops.py qemu patch，"
                f"或 git stash；--reset 会丢弃")
        if git_ok(paths, "rev-parse", "--verify", "-q", "dev"):
            base = conf("QEMU_BASE")
            actual = int(git_out(paths, "rev-list", "--count",
                                 "dev", "--not", base) or 0)
            expected = qemu_expected_patches()
            if actual > expected:
                die(f"dev 比 recipe 多 {actual - expected} 个提交："
                    f"先 python3 tools/devops.py qemu patch，或 --reset 丢弃")

    base = conf("QEMU_BASE")
    if not git_ok(paths, "cat-file", "-e", f"{base}^{{commit}}"):
        filter_args = []
        if conf("QEMU_CLONE_FILTER"):
            filter_args = ["--filter", conf("QEMU_CLONE_FILTER")]
        info(f"拉取 QEMU 基线 {base[:12]}")
        proc = run(["git", "-C", str(q), "fetch", "--depth", "1",
                    *filter_args, "origin", base], check=False)
        if proc.returncode != 0:
            info(f"按 SHA 拉取失败，回退到 master 最近 "
                 f"{conf('QEMU_FALLBACK_DEPTH', '200')} 个提交")
            proc = run(["git", "-C", str(q), "fetch", "--depth",
                        conf("QEMU_FALLBACK_DEPTH", "200"),
                        *filter_args, "origin", "master"], check=False)
        if proc.returncode != 0 or not git_ok(paths, "cat-file", "-e",
                                              f"{base}^{{commit}}"):
            die(f"无法获取 QEMU 基线 {base}；检查网络或 QEMU_FALLBACK_DEPTH")

    run(["git", "-C", str(q), "checkout", "-q", "-f", "-B", "dev", base])
    run(["git", "-C", str(q), "reset", "-q", "--hard", base])
    if reset:
        run(["git", "-C", str(q), "clean", "-q", "-fdx"])
    info(f"QEMU：{q}（patches={qemu_patch_dir()}）")
    qemu_apply_patches(paths)


# --------------------------------------------------------------------------
# Linux 内核 patch 队列（external/linux-* 用本地 git 基线看 diff）
# --------------------------------------------------------------------------

def kernel_patch_dir() -> Path:
    value = os.environ.get("KERNEL_PATCH_DIR")
    return Path(value).expanduser() if value else ROOT / "env" / "kernel" / "patches"


def kernel_expected_patches() -> int:
    return len(patch_entries(kernel_patch_dir()))


def kernel_git(paths: Paths, *args: str) -> str:
    return capture(["git", "-C", str(paths.kernel_src), *args])


def kernel_git_ok(paths: Paths, *args: str) -> bool:
    proc = subprocess.run(["git", "-C", str(paths.kernel_src), *args],
                          capture_output=True)
    return proc.returncode == 0


def kernel_dirty(paths: Paths) -> bool:
    return bool(kernel_git(paths, "status", "--porcelain"))


def kernel_apply_patches(paths: Paths) -> None:
    for line in patch_entries(kernel_patch_dir()):
        patch = kernel_patch_dir() / line
        if not patch.is_file():
            die(f"内核 patch 不存在：{patch}")
        info(f"应用内核 patch {line}")
        proc = run(["git", "-C", str(paths.kernel_src),
                    "-c", "user.name=lab", "-c", "user.email=lab@localhost",
                    "am", "-q", "--3way", str(patch)], check=False)
        if proc.returncode != 0:
            die(f"应用内核 patch {line} 失败。\n"
                f"在 {paths.kernel_src} 解决后 git am --continue，"
                f"或 git checkout -f -B dev lab-base 放弃。")


def init_kernel_git(paths: Paths, reset: bool) -> None:
    if os.environ.get("KERNEL_GIT") == "0":
        info("KERNEL_GIT=0：跳过内核 git 基线（之后需要自己 git init）")
        return
    src = paths.kernel_src
    if not (src / ".git").exists():
        info("注意：首次基线会提交当前源码树；如果你已经手改过 "
             "external/linux-*，请先备份，否则这些改动会被当成基线")
        say("初始化内核 git 基线（首次会提交整个源码树，约 1~2 分钟）")
        run(["git", "init", "-q"], cwd=src)
        run(["git", "-C", str(src), "add", "-A"])
        run(["git", "-C", str(src),
             "-c", "user.name=lab", "-c", "user.email=lab@localhost",
             "commit", "-q", "-m", f"linux-{conf('KERNEL_VERSION')} baseline"])
        run(["git", "-C", str(src), "tag", "-f", "lab-base"])
    elif not kernel_git_ok(paths, "rev-parse", "--verify", "-q", "lab-base"):
        die(f"{src} 有 .git 但没有 lab-base 标签；删除该目录后重新 init")

    migrate_work_branch(src)

    if not reset:
        if kernel_dirty(paths):
            die(f"{src} 有未提交改动：先 git commit 或 git stash；"
                f"--reset 会丢弃")
        if kernel_git_ok(paths, "rev-parse", "--verify", "-q", "dev"):
            actual = int(kernel_git(paths, "rev-list", "--count",
                                    "dev", "--not", "lab-base") or 0)
            expected = kernel_expected_patches()
            if actual > expected:
                die(f"内核 dev 比 recipe 多 {actual - expected} 个提交："
                    f"先用 git format-patch 导出，或 --reset 丢弃")

    run(["git", "-C", str(src), "checkout", "-q", "-f", "-B", "dev",
         "lab-base"])
    run(["git", "-C", str(src), "reset", "-q", "--hard", "lab-base"])
    if reset:
        run(["git", "-C", str(src), "clean", "-q", "-fdx"])
    info(f"内核：{src}（patches={kernel_patch_dir()}）")
    kernel_apply_patches(paths)


# --------------------------------------------------------------------------
# init / build
# --------------------------------------------------------------------------

def prepare_kernel(paths: Paths, reset: bool) -> None:
    if not (paths.kernel_src / "Makefile").is_file():
        die(f"内核源码不完整：{paths.kernel_src}")
    ensure_clean_source(paths.kernel_src, "kernel")
    paths.kernel_build.mkdir(parents=True, exist_ok=True)
    target = paths.kernel_build / ".config"
    if reset or not target.exists():
        shutil.copy2(ROOT / "env" / "kernel" / "arm64-virt.config", target)
        info(f"写入内核配置：{target}")


def prepare_busybox(paths: Paths) -> None:
    if not (paths.busybox_src / "Makefile").is_file():
        die(f"busybox 源码不完整：{paths.busybox_src}")
    ensure_clean_source(paths.busybox_src, "busybox")


def cmd_init(args, paths: Paths) -> int:
    if not args.no_doctor and not doctor():
        die("依赖不全，按上面的提示安装后重试（或 --no-doctor）")

    paths.external.mkdir(parents=True, exist_ok=True)
    paths.build.mkdir(parents=True, exist_ok=True)

    if not args.skip_kernel:
        ensure_tarball(paths, f"linux-{conf('KERNEL_VERSION')}",
                       conf("KERNEL_URL"), conf("KERNEL_SHA256"),
                       reset=args.reset)
        prepare_kernel(paths, args.reset)
        init_kernel_git(paths, args.reset)
    if not args.skip_busybox:
        ensure_tarball(paths, f"busybox-{conf('BUSYBOX_VERSION')}",
                       conf("BUSYBOX_URL"), conf("BUSYBOX_SHA256"),
                       reset=args.reset)
        prepare_busybox(paths)
    if not args.skip_qemu:
        init_qemu(paths, args.reset)

    print()
    print("recipe 准备完成：")
    print(f"  内核      {paths.kernel_src}")
    print(f"  busybox   {paths.busybox_src}")
    print(f"  QEMU      {paths.qemu_src}  (base {conf('QEMU_BASE')[:12]}, "
          f"{qemu_expected_patches()} 个 patch)")
    print(f"  构建目录  {paths.build}")
    print()
    print("下一步：")
    print("  python3 tools/devops.py build          # 全部编译")
    print("  python3 tools/devops.py build kernel   # 只编内核")
    print("  python3 tools/devops.py build drivers        # 编 drivers/**")
    return 0


def build_qemu(paths: Paths, job_count: int) -> None:
    if not (paths.qemu_src / ".git").exists():
        die("QEMU 源码还没准备好：先 python3 tools/devops.py init")
    if qemu_dirty(paths):
        info("警告：QEMU 工作区有未提交改动，按当前工作区编译")
    paths.qemu_build.mkdir(parents=True, exist_ok=True)
    if not (paths.qemu_build / "build.ninja").exists():
        args_file = ROOT / "env" / "qemu" / "configure.args"
        cargs = [line.strip() for line in
                 args_file.read_text(encoding="utf-8").splitlines()
                 if line.strip() and not line.lstrip().startswith("#")]
        say("配置 QEMU")
        run([paths.qemu_src / "configure", *cargs], cwd=paths.qemu_build)
    say(f"编译 QEMU（-j{job_count}）")
    run(["ninja", "-C", paths.qemu_build, "-j", job_count,
         "qemu-system-aarch64"])
    info(f"产物：{paths.qemu_bin}")


def build_kernel(paths: Paths, job_count: int) -> None:
    if not (paths.kernel_src / "Makefile").is_file():
        die("内核源码还没准备好：先 python3 tools/devops.py init")
    ensure_clean_source(paths.kernel_src, "kernel")
    paths.kernel_build.mkdir(parents=True, exist_ok=True)
    target = paths.kernel_build / ".config"
    if not target.exists():
        shutil.copy2(ROOT / "env" / "kernel" / "arm64-virt.config", target)
        info(f"写入内核配置：{target}")
    common = ["make", "-C", paths.kernel_src, f"O={paths.kernel_build}",
              f"ARCH={arch()}", f"CROSS_COMPILE={cross()}"]
    say("内核 olddefconfig")
    run([*common, "olddefconfig"])
    say(f"编译内核 Image + modules（-j{job_count}）")
    run([*common, "-j", job_count, "Image", "modules"])
    run([*common, "modules_prepare"], stdout=subprocess.DEVNULL)
    info(f"产物：{paths.kernel_build / 'arch/arm64/boot/Image'}")
    info(f"KDIR：{paths.kernel_build}（可直接给 modules 用）")


def build_busybox(paths: Paths, job_count: int) -> None:
    if not (paths.busybox_src / "Makefile").is_file():
        die("busybox 源码还没准备好：先 python3 tools/devops.py init")
    ensure_clean_source(paths.busybox_src, "busybox")
    paths.busybox_build.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "env" / "busybox" / "busybox.config",
                 paths.busybox_build / ".config")
    log = paths.busybox_build / "build.log"
    common = ["make", "-C", paths.busybox_src, f"O={paths.busybox_build}",
              f"ARCH={arch()}", f"CROSS_COMPILE={cross()}"]
    with log.open("wb") as handle:
        say("busybox oldconfig")
        proc = run([*common, "oldconfig"], stdin=subprocess.DEVNULL,
                   stdout=handle, stderr=subprocess.STDOUT, check=False)
        if proc.returncode != 0:
            tail_file(log)
            die(f"busybox oldconfig 失败（日志 {log}）")
        say(f"编译 busybox（-j{job_count}）")
        proc = run([*common, "-j", job_count], stdout=handle,
                   stderr=subprocess.STDOUT, check=False)
        if proc.returncode != 0:
            tail_file(log)
            die(f"busybox 编译失败（日志 {log}）")
    shutil.rmtree(paths.rootfs, ignore_errors=True)
    paths.rootfs.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as handle:
        proc = run([*common, f"CONFIG_PREFIX={paths.rootfs}", "install"],
                   stdout=handle, stderr=subprocess.STDOUT, check=False)
    if proc.returncode != 0:
        tail_file(log)
        die(f"busybox install 失败（日志 {log}）")
    info(f"产物：{paths.rootfs / 'bin/busybox'}")


# --------------------------------------------------------------------------
# initramfs（纯 Python 写 cpio newc，不需要 root/cpio/gen_init_cpio）
# --------------------------------------------------------------------------

def cpio_newc(entries, output: Path) -> None:
    buffer = io.BytesIO()
    ino = 1

    def emit(name: str, mode: int, data: bytes = b"",
             rdev: tuple[int, int] = (0, 0), nlink: int = 1) -> None:
        nonlocal ino
        name_bytes = name.encode() + b"\0"
        fields = [ino, mode, 0, 0, nlink, 0, len(data), 0, 0,
                  rdev[0], rdev[1], len(name_bytes), 0]
        header = b"070701" + b"".join(f"{value:08x}".encode()
                                      for value in fields)
        buffer.write(header)
        buffer.write(name_bytes)
        buffer.write(b"\0" * ((-len(header) - len(name_bytes)) % 4))
        buffer.write(data)
        buffer.write(b"\0" * ((-len(data)) % 4))
        ino += 1

    for entry in entries:
        emit(*entry)
    emit("TRAILER!!!", 0)

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as raw, \
            gzip.GzipFile(fileobj=raw, mode="wb", mtime=0,
                          compresslevel=9) as gz:
        gz.write(buffer.getvalue())


def cmd_build_initramfs(paths: Paths) -> None:
    busybox = paths.rootfs / "bin/busybox"
    if not busybox.is_file():
        die(f"找不到 {busybox}：先 python3 tools/devops.py build busybox")

    say(f"准备 rootfs：{paths.rootfs}")
    for name in ("dev", "proc", "sys", "tmp", "etc/init.d", "lib"):
        (paths.rootfs / name).mkdir(parents=True, exist_ok=True)

    overlay = ROOT / "env" / "busybox" / "rootfs-overlay"
    if overlay.is_dir():
        shutil.copytree(overlay, paths.rootfs, dirs_exist_ok=True,
                        copy_function=shutil.copy2)
    os.chmod(paths.rootfs / "tmp", 0o1777)

    linuxrc = paths.rootfs / "linuxrc"
    if linuxrc.is_symlink() or linuxrc.exists():
        linuxrc.unlink()
    os.symlink("bin/busybox", linuxrc)

    say("复制交叉工具链运行库")
    for lib in ("ld-linux-aarch64.so.1", "libc.so.6", "libm.so.6",
                "libresolv.so.2"):
        source = Path(capture([f"{cross()}gcc", f"-print-file-name={lib}"]))
        if not source.is_file():
            die(f"工具链里找不到 {lib}（{cross()}gcc）")
        shutil.copy2(source, paths.rootfs / "lib" / lib)

    say(f"打包 {paths.initrd}")
    entries = [(".", stat.S_IFDIR | 0o755, b"", (0, 0), 2)]
    seen = set()
    for root, dirs, files in os.walk(paths.rootfs):
        dirs.sort()
        files.sort()
        rel_root = Path(root).relative_to(paths.rootfs)
        if rel_root != Path("."):
            mode = stat.S_IFDIR | (os.lstat(root).st_mode & 0o7777)
            entries.append((rel_root.as_posix(), mode, b"", (0, 0), 2))
        for name in files:
            full = Path(root) / name
            rel = full.relative_to(paths.rootfs).as_posix()
            st = os.lstat(full)
            if stat.S_ISLNK(st.st_mode):
                entries.append((rel, stat.S_IFLNK | 0o777,
                                os.readlink(full).encode(), (0, 0), 1))
            elif stat.S_ISREG(st.st_mode):
                entries.append((rel, stat.S_IFREG | (st.st_mode & 0o7777),
                                full.read_bytes(), (0, 0), 1))
            else:
                continue
            seen.add(rel)
    for name, mode, dev in (("dev/console", 0o600, (5, 1)),
                            ("dev/null", 0o666, (1, 3))):
        if name not in seen:
            entries.append((name, stat.S_IFCHR | mode, b"", dev, 1))
    if not (paths.rootfs / "etc" / "inittab").is_file():
        die("rootfs 缺 /etc/inittab（overlay 没复制成功？）")
    cpio_newc(entries, paths.initrd)
    info(f"完成：{paths.initrd}（{len(entries)} 项，"
         f"{paths.initrd.stat().st_size / 1024 / 1024:.1f}M）")


def cmd_build(args, paths: Paths) -> int:
    target = args.target
    env_targets = {"qemu", "kernel", "busybox", "initramfs"}

    if target in env_targets or target == "all":
        if args.driver:
            die(f"{target} 不接受 driver 参数；"
                f"编驱动请用 build drivers/路径")
        job_count = jobs(args.jobs)
        targets = (["qemu", "kernel", "busybox", "initramfs"]
                   if target == "all" else [target])
        if "qemu" in targets:
            build_qemu(paths, job_count)
        if "kernel" in targets:
            build_kernel(paths, job_count)
        if "busybox" in targets:
            build_busybox(paths, job_count)
        if "initramfs" in targets:
            cmd_build_initramfs(paths)
        return 0

    # build drivers / drivers/chardev / drivers/chardev/i2c-tmp105
    if target == "drivers":
        selector = args.driver
    else:
        if args.driver:
            die(f"用法：build drivers [驱动路径]（不要写成 "
                f"build {target} {args.driver}）")
        selector = target
    if not selector or selector in ("drivers", "drivers/"):
        selector = None
    return cmd_build_drivers(selector, args, paths)


# --------------------------------------------------------------------------
# 外部模块
# --------------------------------------------------------------------------

def module_dirs() -> list[Path]:
    return sorted(path.parent for path in
                  (ROOT / "drivers").rglob("Kbuild"))


def resolve_driver_dirs(spec: str | None) -> list[Path]:
    all_dirs = module_dirs()
    if not spec:
        return all_dirs

    raw = spec.strip().strip("/")
    if raw.startswith("./"):
        raw = raw[2:]
    rel = raw[len("drivers/"):] if raw.startswith("drivers/") else raw

    for base in (ROOT / raw, ROOT / "drivers" / rel):
        if base.is_dir():
            found = sorted(item.parent for item in base.rglob("Kbuild"))
            if found:
                return found
            die(f"{spec} 下没有 Kbuild 模块")

    matches = [item for item in all_dirs if item.name == rel]
    if len(matches) == 1:
        return matches
    if len(matches) > 1:
        names = "\n".join(f"  {item.relative_to(ROOT)}" for item in matches)
        die(f"目录名 {rel} 不唯一，请写完整路径，例如：\n{names}")

    available = "\n".join(f"  {item.relative_to(ROOT)}" for item in all_dirs)
    die(f"找不到驱动模块：{spec}\n可用模块：\n{available}")


def cmd_build_drivers(spec: str | None, args, paths: Paths) -> int:
    kdir = Path(args.kdir or os.environ.get("KDIR") or paths.kernel_build)
    kdir = kdir.expanduser().resolve()
    arch_value = args.arch or arch()
    cross_value = cross() if args.cross_prefix is None else args.cross_prefix
    if not (kdir / "Makefile").is_file() and not (kdir / "include").is_dir():
        die(f"KDIR 不存在或未准备：{kdir}\n"
            f"先 python3 tools/devops.py build kernel，或用 --kdir 指定")
    dirs = resolve_driver_dirs(spec)
    if not dirs:
        die("drivers/**/Kbuild 一个都没有")
    for directory in dirs:
        say(f"构建 {directory.relative_to(ROOT)}")
        cmd = ["make", "-C", kdir, f"ARCH={arch_value}",
               f"CROSS_COMPILE={cross_value}",
               f"M={directory.resolve()}"]
        if args.jobs:
            cmd.append(f"-j{args.jobs}")
        if args.sparse:
            cmd.append("C=2")
        cmd.append("modules")
        proc = run(cmd, check=False)
        if proc.returncode != 0:
            return proc.returncode
    return 0


def cmd_clean_drivers(args, paths: Paths) -> int:
    kdir = Path(args.kdir or os.environ.get("KDIR") or paths.kernel_build)
    kdir = kdir.expanduser().resolve()
    for directory in module_dirs():
        cmd = ["make", "-C", kdir, f"ARCH={arch()}",
               f"CROSS_COMPILE={cross()}", f"M={directory.resolve()}", "clean"]
        run(cmd, check=False, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
    info("驱动模块产物已清理")
    return 0


def cmd_checkpatch(args, paths: Paths) -> int:
    if not which("perl"):
        die("需要 perl（apt install perl）")
    candidates = [paths.kernel_src, paths.kernel_build]
    kdir_env = os.environ.get("KDIR")
    if kdir_env:
        candidates.insert(0, Path(kdir_env).expanduser())
    script = next((base / "scripts" / "checkpatch.pl" for base in candidates
                   if (base / "scripts" / "checkpatch.pl").is_file()), None)
    if script is None:
        die("找不到 scripts/checkpatch.pl：先 python3 tools/devops.py init，"
            "或用 KERNEL_SRC/KDIR 指定已有内核树")
    files = sorted(
        path for pattern in ("*.c", "*.h")
        for path in (ROOT / "drivers").rglob(pattern)
        if not path.name.endswith(".mod.c")
    )
    if not files:
        die("没有可检查的源文件")
    return run([script, "--no-tree", "--strict", "-f", *files], check=False).returncode


# --------------------------------------------------------------------------
# verify
# --------------------------------------------------------------------------

def cmd_verify(args, paths: Paths) -> int:
    scripts = sorted((ROOT / "tests").glob("*/*/verify_qemu.sh"))
    if args.pattern:
        scripts = [item for item in scripts
                   if any(p in str(item) for p in args.pattern)]
    if not scripts:
        die("没有匹配的 tests/*/*/verify_qemu.sh")
    failed = []
    for script in scripts:
        print()
        print(f"=== {script.relative_to(ROOT)} ===")
        proc = subprocess.run(["bash", str(script)], cwd=ROOT)
        if proc.returncode != 0:
            failed.append(script)
    print()
    if failed:
        print("失败：")
        for script in failed:
            print(f"  {script.relative_to(ROOT)}")
        return 1
    print(f"全部通过（{len(scripts)} 个测试脚本）")
    return 0


# --------------------------------------------------------------------------
# QEMU 改动工作流
# --------------------------------------------------------------------------

def cmd_qemu(args, paths: Paths) -> int:
    if not (paths.qemu_src / ".git").exists():
        die("QEMU 源码还没准备好：先 python3 tools/devops.py init")

    migrate_work_branch(paths.qemu_src)

    if args.action == "status":
        base = conf("QEMU_BASE")
        print(f"仓库      {paths.qemu_src}")
        print(f"recipe    base={base} "
              f"({qemu_expected_patches()} 个 patch，"
              f"目录 {qemu_patch_dir()})")
        try:
            branch = git_out(paths, "rev-parse", "--abbrev-ref", "HEAD")
            print(f"分支      {branch}")
            for line in git_out(paths, "log", "--oneline", "-5").splitlines():
                print(f"  {line}")
        except DevopsError:
            pass
        print("工作区    " + ("有未提交改动" if qemu_dirty(paths) else "干净"))
        return 0

    if args.action == "diff":
        branch = current_branch(paths.qemu_src) or "HEAD"
        print_diff(paths.qemu_src, conf("QEMU_BASE"), branch, args.full)
        return 0

    if args.action == "checkout":
        branch = args.target or "dev"
        if not valid_branch(branch):
            die(f"非法分支名：{branch}")
        if git_ok(paths, "show-ref", "--verify", "-q",
                  f"refs/heads/{branch}"):
            run(["git", "-C", str(paths.qemu_src), "checkout", "-q", branch])
        else:
            info(f"创建 {branch} 并重放当前 patches")
            run(["git", "-C", str(paths.qemu_src), "checkout", "-q", "-B",
                 branch, conf("QEMU_BASE")])
            qemu_apply_patches(paths)
        print(f"已切到 {paths.qemu_src} 的 {branch}")
        print("改完 commit 后执行：python3 tools/devops.py qemu patch")
        print(f"增量编译：ninja -C {paths.qemu_build} qemu-system-aarch64")
        return 0

    if args.action == "patch":
        if qemu_dirty(paths):
            die(f"有未提交改动，先 git -C {paths.qemu_src} commit")
        branch = current_branch(paths.qemu_src)
        if not branch:
            die("当前是 detached HEAD；先 qemu checkout <branch>")
        base = conf("QEMU_BASE")
        if subprocess.run(["git", "-C", str(paths.qemu_src), "merge-base",
                           "--is-ancestor", base, branch]).returncode != 0:
            die(f"{branch} 不是基于 QEMU_BASE={base}；先更新 lab.conf 或 rebase")
        count = int(git_out(paths, "rev-list", "--count", f"{base}..{branch}"))
        if count <= 0:
            die(f"{branch} 相对基线没有提交，无可导出内容")
        patch_dir = qemu_patch_dir()
        patch_dir.mkdir(parents=True, exist_ok=True)
        for old in patch_dir.glob("*.patch"):
            old.unlink()
        info(f"从 {branch} 导出 {count} 个 commit 到 {patch_dir}")
        run(["git", "-C", str(paths.qemu_src), "format-patch",
             "--zero-commit", "--no-signature", "--no-numbered",
             "--full-index", "-o", patch_dir, f"{base}..{branch}"],
            stdout=subprocess.DEVNULL)
        names = sorted(item.name for item in patch_dir.glob("*.patch"))
        print()
        for name in names:
            print(f"  {name}")
        print("\n记得把 env/qemu/patches 一起提交。")
        return 0

    if args.action == "reset":
        branch = args.target or current_branch(paths.qemu_src) or "dev"
        if not valid_branch(branch):
            die(f"非法分支名：{branch}")
        info(f"重置 {branch} 到 {conf('QEMU_BASE')} 并重放 patches")
        run(["git", "-C", str(paths.qemu_src), "checkout", "-q", "-f", "-B",
             branch, conf("QEMU_BASE")])
        run(["git", "-C", str(paths.qemu_src), "reset", "-q", "--hard",
             conf("QEMU_BASE")])
        run(["git", "-C", str(paths.qemu_src), "clean", "-q", "-fdx"])
        qemu_apply_patches(paths)
        return 0

    if args.action == "rebase":
        if not args.target:
            die("用法：python3 tools/devops.py qemu rebase <新 base commit>")
        branch = current_branch(paths.qemu_src) or "dev"
        if not valid_branch(branch):
            die(f"非法分支名：{branch}")
        if not git_ok(paths, "cat-file", "-e", f"{args.target}^{{commit}}"):
            die(f"找不到 commit：{args.target}"
                f"（先 git -C {paths.qemu_src} fetch）")
        info(f"把 {branch} 切到新基线 {args.target} 并重放 patches")
        run(["git", "-C", str(paths.qemu_src), "checkout", "-q", "-f", "-B",
             branch, args.target])
        run(["git", "-C", str(paths.qemu_src), "reset", "-q", "--hard",
             args.target])
        qemu_apply_patches(paths)
        print(f"\n重放成功。请更新 lab.conf：\n  QEMU_BASE={args.target}")
        print("然后执行：python3 tools/devops.py qemu patch")
        return 0

    die(f"未知 qemu 动作：{args.action}")


# --------------------------------------------------------------------------
# 内核 / QEMU 改动查看
# --------------------------------------------------------------------------

def print_diff(repo: Path, base: str, branch: str, full: bool) -> None:
    print(f"仓库：{repo}", flush=True)
    print(f"范围：{base}..{branch}", flush=True)
    run(["git", "-C", str(repo), "--no-pager", "diff", "--stat",
         f"{base}..{branch}"], check=False)
    run(["git", "-C", str(repo), "--no-pager", "diff", "--name-status",
         f"{base}..{branch}"], check=False)
    if full:
        run(["git", "-C", str(repo), "--no-pager", "diff",
             f"{base}..{branch}"], check=False)
    dirty = capture(["git", "-C", str(repo), "status", "--porcelain"]) \
        if (repo / ".git").exists() else ""
    if dirty:
        print("\n未提交改动：", flush=True)
        run(["git", "-C", str(repo), "status", "--short"], check=False)
        if full:
            run(["git", "-C", str(repo), "--no-pager", "diff"], check=False)
        else:
            run(["git", "-C", str(repo), "--no-pager", "diff", "--stat"],
                check=False)


# --------------------------------------------------------------------------
# clean / status / list
# --------------------------------------------------------------------------

def confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        die("非交互环境：加 --yes 确认")
    return input(prompt + " [y/N] ").strip().lower() in ("y", "yes")


def cmd_clean(args, paths: Paths) -> int:
    if args.target in ("drivers", "modules"):
        return cmd_clean_drivers(args, paths)
    targets = [paths.build] if args.target == "env" else [paths.build,
                                                          paths.external]
    print("将删除：")
    for target in targets:
        print(f"  {target}")
    if not confirm("确认？", args.yes):
        return 1
    for target in targets:
        shutil.rmtree(target, ignore_errors=True)
    info("已删除（python3 tools/devops.py init 可重建）")
    return 0


def cmd_status(args, paths: Paths) -> int:
    print(f"仓库      {ROOT}")
    print(f"内核      {conf('KERNEL_VERSION')}")
    print(f"busybox   {conf('BUSYBOX_VERSION')}")
    print(f"QEMU      {conf('QEMU_TAG')}  base={conf('QEMU_BASE')}  "
          f"patches={qemu_expected_patches()} 个")
    print()
    for label, path in (("external", paths.external), ("build", paths.build),
                        ("QEMU 源码", paths.qemu_src),
                        ("内核源码", paths.kernel_src),
                        ("busybox 源码", paths.busybox_src),
                        ("QEMU 产物", paths.qemu_bin),
                        ("内核 Image", paths.kernel_build / "arch/arm64/boot/Image"),
                        ("initramfs", paths.initrd)):
        mark = "OK" if path.exists() else "--"
        print(f"  [{mark}] {label:12} {path}")
    if (paths.qemu_src / ".git").exists():
        try:
            branch = git_out(paths, "rev-parse", "--abbrev-ref", "HEAD")
            dirty = "dirty" if qemu_dirty(paths) else "clean"
            print(f"\nQEMU 分支：{branch}（{dirty}）")
        except DevopsError:
            pass
    return 0


def cmd_list(args, paths: Paths) -> int:
    for directory in module_dirs():
        print(directory.relative_to(ROOT))
    return 0


# --------------------------------------------------------------------------
# Windows -> WSL 转接
# --------------------------------------------------------------------------

def first_wsl_distro() -> str | None:
    try:
        proc = subprocess.run(["wsl.exe", "-l", "-q"],
                              capture_output=True)
    except FileNotFoundError:
        return None
    raw = proc.stdout
    text = raw.decode("utf-16-le", errors="ignore") if b"\x00" in raw \
        else raw.decode("utf-8", errors="ignore")
    for line in text.replace("\r", "\n").splitlines():
        line = line.strip().lstrip("\ufeff")
        if line:
            return line
    return None


def maybe_reexec_wsl() -> None:
    if os.name != "nt" or os.environ.get("DEVOPS_NO_WSL") == "1":
        return
    argv = sys.argv[1:]
    if "--no-wsl" in argv:
        os.environ["DEVOPS_NO_WSL"] = "1"
        sys.argv.remove("--no-wsl")
        return

    script = Path(__file__).resolve()
    script_text = re.sub(r"^\\\\\?\\UNC\\", r"\\\\", str(script))
    distro = None
    linux_script = None
    match = re.match(r"^\\\\wsl(?:\.localhost|\$)\\([^\\]+)\\(.+)$",
                     script_text, re.IGNORECASE)
    if match:
        distro = match.group(1)
        linux_script = "/" + match.group(2).replace("\\", "/")
    else:
        distro = os.environ.get("WSL_DISTRO_NAME") or first_wsl_distro()
        if not distro:
            print("Windows 上需要 WSL2；或先在 WSL 里运行："
                  "python3 tools/devops.py ...", file=sys.stderr)
            raise SystemExit(2)
        try:
            proc = subprocess.run(
                ["wsl.exe", "-d", distro, "--", "wslpath", "-a", "-u",
                 str(Path(script_text).parent)],
                capture_output=True, text=True, check=True)
            linux_script = proc.stdout.strip().rstrip("/") + "/" + script.name
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"无法把 Windows 路径映射到 WSL：{exc}", file=sys.stderr)
            raise SystemExit(2)

    if not linux_script:
        print("无法确定 WSL 中的仓库路径。", file=sys.stderr)
        raise SystemExit(2)
    linux_root = str(PurePosixPath(linux_script).parent)
    cmd = ["wsl.exe", "-d", distro, "--cd", linux_root, "--",
           "python3", linux_script, *argv]
    if VERBOSE:
        print("转交 WSL：" + " ".join(shlex.quote(part) for part in cmd),
              file=sys.stderr)
    raise SystemExit(subprocess.call(cmd))


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="devops.py",
        description="linux-kmods 实验台统一入口（Linux/WSL/macOS；Windows 自动转 WSL）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例：
  python3 tools/devops.py doctor
  python3 tools/devops.py init
  python3 tools/devops.py build all --jobs 8
  python3 tools/devops.py build kernel
  python3 tools/devops.py build drivers
  python3 tools/devops.py build drivers/hwmon/i2c-tmp105
  python3 tools/devops.py verify hwmon
  python3 tools/devops.py qemu status
  python3 tools/devops.py qemu diff --full
""")
    parser.add_argument("--no-wsl", action="store_true",
                        help="Windows 下不转交 WSL（调试用）")
    parser.add_argument("--verbose", action="store_true", help="打印完整命令")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="检查宿主依赖")
    sub.add_parser("status", help="查看版本、路径、产物")
    sub.add_parser("list", help="列出会被构建的模块目录")
    sub.add_parser("help", help="显示帮助")

    init = sub.add_parser("init", help="还原 recipe（下载/解包/打 QEMU patch）")
    init.add_argument("--reset", action="store_true",
                      help="丢弃 external/qemu 的本地改动和本地构建目录")
    init.add_argument("--skip-qemu", action="store_true")
    init.add_argument("--skip-kernel", action="store_true")
    init.add_argument("--skip-busybox", action="store_true")
    init.add_argument("--no-doctor", action="store_true")

    build = sub.add_parser("build", help="编译实验环境 / 驱动")
    build.add_argument("target", nargs="?", default="all",
                       help="all|qemu|kernel|busybox|initramfs|"
                            "drivers[/子系统[/驱动]]")
    build.add_argument("driver", nargs="?",
                       help="直接写路径：build drivers/chardev、"
                            "build drivers/chardev/i2c-tmp105")
    build.add_argument("--kdir")
    build.add_argument("--arch")
    build.add_argument("--cross-prefix")
    build.add_argument("--jobs", type=int, default=0)
    build.add_argument("--sparse", action="store_true")

    sub.add_parser("checkpatch", help="对 drivers/** 跑内核 checkpatch")

    verify = sub.add_parser("verify", help="跑 tests/*/*/verify_qemu.sh")
    verify.add_argument("pattern", nargs="*", help="可选：过滤子串，如 hwmon")

    qemu = sub.add_parser("qemu", help="QEMU 定制工作流")
    qemu.add_argument("action",
                      choices=("status", "diff", "checkout", "patch", "reset",
                               "rebase"))
    qemu.add_argument("target", nargs="?",
                      help="checkout/reset 的分支名（默认 dev），"
                           "或 rebase 的新 base commit")
    qemu.add_argument("--full", action="store_true",
                      help="diff 时输出完整补丁内容")

    clean = sub.add_parser("clean", help="清理产物")
    clean.add_argument("target", nargs="?", default="drivers",
                       choices=("drivers", "modules", "env", "all"))
    clean.add_argument("--yes", action="store_true")
    clean.add_argument("--kdir")

    return parser


def dispatch(args, paths: Paths) -> int:
    global VERBOSE
    if args.command == "help":
        build_parser().print_help()
        return 0
    if args.command == "doctor":
        return 0 if doctor() else 1
    if args.command == "status":
        return cmd_status(args, paths)
    if args.command == "list":
        return cmd_list(args, paths)
    if args.command == "init":
        return cmd_init(args, paths)
    if args.command == "build":
        return cmd_build(args, paths)
    if args.command == "checkpatch":
        return cmd_checkpatch(args, paths)
    if args.command == "verify":
        return cmd_verify(args, paths)
    if args.command == "qemu":
        return cmd_qemu(args, paths)
    if args.command == "clean":
        return cmd_clean(args, paths)
    die(f"未知命令：{args.command}")


def main() -> int:
    global VERBOSE
    maybe_reexec_wsl()
    parser = build_parser()
    args = parser.parse_args()
    VERBOSE = args.verbose
    load_conf()
    paths = load_paths()
    try:
        return dispatch(args, paths)
    except DevopsError as exc:
        print(f"\n[devops] 错误：{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n[devops] 已中断", file=sys.stderr)
        return 130
    except subprocess.CalledProcessError as exc:
        print(f"\n[devops] 命令失败（退出码 {exc.returncode}）：{exc.cmd}",
              file=sys.stderr)
        return exc.returncode or 1


if __name__ == "__main__":
    sys.exit(main())
