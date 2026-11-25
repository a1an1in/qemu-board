# env/kernel/patches

`*.patch` 按文件名 0001、0002... 顺序应用，由 `tools/devops.py init` 用
`git am --3way` 打到 `external/linux-<ver>`。

生成方式（直接用 git）：

```sh
cd external/linux-4.9.263
git checkout dev
# 改代码并 commit
rm -f ../../env/kernel/patches/*.patch
git format-patch --zero-commit --no-signature --no-numbered --full-index \
    -o ../../env/kernel/patches lab-base..dev
```

也可以把现成的 `git format-patch` 文件放进本目录（文件名决定顺序）。
