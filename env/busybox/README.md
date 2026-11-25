# env/busybox —— busybox + initramfs recipe

```
busybox.config              # 完整 .config（动态链接、CONFIG_PREFIX 会被覆盖）
rootfs-overlay/             # 覆盖到 build/rootfs 的文件（inittab/fstab/rcS）
```

- 版本由 `lab.conf` 的 `BUSYBOX_VERSION` 固定，源码按 sha256 校验后解包到 `external/`。
- `make env-busybox` 把 busybox 安装到 `build/rootfs`，`make env-initramfs` 再补
  设备节点、运行库、overlay 并用内核的 `gen_init_cpio` 打包。
- 改 `inittab`/`rcS` 直接改 `rootfs-overlay/`，然后 `make env-initramfs`。
- 运行库由 `aarch64-linux-gnu-gcc -print-file-name=` 定位并复制，不依赖宿主的
  aarch64 sysroot 布局。
