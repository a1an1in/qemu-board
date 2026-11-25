# env/kernel/patches

`*.patch` 按文件名 0001、0002... 顺序应用，由 `tools/devops.py init`（以及
`kernel reset`）用 `git am --3way` 打到 `external/linux-<ver>`。

推荐用工具生成：

```sh
python3 tools/devops.py init          # 首次（会建立 lab-base git 基线）
python3 tools/devops.py kernel checkout
vim external/linux-4.9.263/drivers/...
git -C external/linux-4.9.263 commit -am "my change"
python3 tools/devops.py kernel patch
```

也可以把现成的 `git format-patch` 文件放进本目录（文件名决定顺序）。
