# env/busybox —— busybox + initramfs recipe

```
busybox.config              # 完整 .config（动态链接、CONFIG_PREFIX 会被覆盖）
rootfs-overlay/             # 覆盖到 build/rootfs 的文件（inittab/fstab/rcS）
```

- 版本由 `lab.conf` 的 `BUSYBOX_VERSION` 固定，源码按 sha256 校验后解包到 `external/`。
- `python3 tools/devops.py build busybox` 把 busybox 安装到 `build/rootfs`；
  `python3 tools/devops.py build initramfs` 再补设备节点、运行库、overlay 并打包。
- 改 `inittab`/`rcS` 直接改 `rootfs-overlay/`，然后
  `python3 tools/devops.py build initramfs`。
- 运行库由 `aarch64-linux-gnu-gcc -print-file-name=` 定位并复制，不依赖宿主的
  aarch64 sysroot 布局。
- initramfs 由 `tools/devops.py` 用纯 Python 写 cpio newc，不需要 root/fakeroot。
