# T4 · MR 可评审纪律

> 源：`large-vendor-import-pattern` · `scope-based-clean-mr-pattern`。<project> GitLab 发布列车 + gofmt/prettier 直接命中。补充 <project> `/pr` `/commit` skill。

## 核心

- **机械改动拆独立 commit**：大体量机械改动（vendor / 批量重命名 / 生成码 / 全树格式化）**必与逻辑改动拆成独立 commit**，message 讲清边界，reviewer 才能跳过机械 diff——否则 PR 永远合不了。
- **type-alias 减 churn**：符号改名引发 N 文件 churn 时用 type-alias 收敛。
- **批量 find-replace 单轮必漏**：需多轮 + 每轮重 grep 复核。
- **格式化淹没 review 的解法**：当 whole-tree format baseline（ruff/prettier/gofmt）把功能 review 淹没、reviewer 拒 merge 时：`git -w`/`-X`/revert **全失效**（有实证）；改用 **path-based scope filter 重做 clean MR**，跳过的 lint 存 local side branch 另行处理。

## 落点
`.trellis/spec/guides` 的 git-MR 纪律；`/pr` `/new-branch` skill 的补充操作手册。**注意**：<project> 的具体 MR 流程以你仓库的工程文档 + MR 约定为准，本篇是可泛化原则。
