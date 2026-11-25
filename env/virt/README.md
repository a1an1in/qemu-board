# env/virt —— 可选的板级物料

- `virt_custom.dts`：从现成 DTB 反编译出来的完整设备树，仅作**备份/参考**。
- `make_dtb.sh`：生成 `build/virt_custom.dtb`。
- `make_flash.sh`：生成 64M pflash 镜像（`FLASH=build/flash.img make run` 才用）。

> 默认不要传 `-dtb`。自研 QEMU 在 `machvirt_init()` 里生成 FDT，才会包含
> `/i2c@9060000/tmp105@48` 等节点；`virt_custom.dtb` 不含 tmp105 节点，
> 传了反而导致驱动不 probe（见 `doc/hwmon/i2c-tmp105/设计文档.md` §7）。
