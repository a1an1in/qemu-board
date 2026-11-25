# env/kernel/patches/<series>

`series/<series>` 里列出的 patch 会由 `tools/devops.py init`（以及
`kernel reset`）按顺序用 `git am --3way` 应用到 `external/linux-<ver>`。

推荐用工具生成：

```sh
python3 tools/devops.py init          # 首次（会建立 lab-base git 基线）
python3 tools/devops.py kernel hack
vim external/linux-4.9.263/drivers/...
git -C external/linux-4.9.263 commit -am "my change"
python3 tools/devops.py kernel export
```

也可以把现成的 `git format-patch` 文件放进本目录，并把文件名追加到
`env/kernel/series/base`。
