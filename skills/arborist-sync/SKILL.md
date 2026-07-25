---
name: arborist-sync
description: 在 Arborist 模板仓与某个采纳实例仓（如 myproject）之间双向同步 overlay guides。push（实例→Arborist）先去隐私化再解冲突；pull（Arborist→实例）先特化占位再解冲突。因需隐私审计 + 冲突调解的判断，必须由 Agent 执行，不能只跑脚本。
---

# arborist-sync：Arborist ↔ 实例仓 双向同步

Arborist（泛化模板，占位 `<REPO_ROOT>`/`<project>`）与实例仓（具体值，harness overlay 在 `.trellis/spec/guides/` 等、`hgit` 记史）**故意解耦**，中间隔一道泛化 gap。同步**不是 git pull**，是**带转换 + 人判断**的操作。脚本（`sync.sh`）只做机械 copy+sed；**你（Agent）负责隐私审计与冲突调解**。

## 前置
确认并设好：
- `ARBORIST_ROOT`（Arborist 仓根）、`INSTANCE_ROOT`（实例仓根）
- `INSTANCE_ABS`（实例绝对路径，如 `/abs/path/to/proj`）、`PROJECT`（实例项目名，如 `myproject`）
- 同步范围：默认 `spec/guides/`（含 methodology、decisions/TEMPLATE）；`scripts/`、`workflow-customization.md` 按需。

## push：实例 → Arborist（把实验田改进泛化上推）
1. **选文件**：`hgit -C $INSTANCE_ROOT log`/`diff` 找本轮改动的 guide；或用户点名。
2. **机械泛化**：`sync.sh generalize <files>` → 拷到 staging + sed（`$INSTANCE_ABS`→`<REPO_ROOT>`、`$PROJECT`→`<project>`、`$HOME`→`<HOME>`）。
3. **隐私审计门（阻断，必须过）**：`sync.sh audit <staging>` 扫——绝对路径 / 内部仓名（其它私有项目）/ 密钥 / UUID / 邮箱 / 组织内网名。**有残留就停下修，绝不带泄漏 push。** 脚本报的可疑项你逐条人判（有的是正当示例）。
4. **冲突调解**：`diff` staged-泛化 vs Arborist 当前。Arborist 可能有外部改动——**做意图级合并**，别覆盖无关的 Arborist 改动；真冲突列给用户定。
5. **落定**：给用户看 diff → 批准后写入 Arborist → commit（Apache 头/NOTICE 不动）→ push。

## pull：Arborist → 实例（把模板更新拉回实例）
1. **机械特化**：`sync.sh specialize <files>` → 拷 Arborist overlay 到 staging + sed（`<REPO_ROOT>`→`$INSTANCE_ABS`、`<project>`→`$PROJECT`）。
2. **冲突调解**：`diff` staged-特化 vs 实例当前 guide。实例可能有本地定制——**意图级三方合并**，真冲突列给用户定，别盖掉本地定制。
3. **落定**：给用户看 diff → 批准后写入实例 → `hgit add -f + commit`。

## Skill 还必须做（超出"双向+去隐私+解冲突"的补充职责）

**发现 / 状态**
- **diff-first**：先 `hgit -C $INSTANCE_ROOT diff` / Arborist 侧 `git log` 找**本轮真改动**的文件，别全量盲扫。
- **status 先行**：动手前 `sync.sh status` 出"两侧差异表"（增/删/改、哪侧领先），让用户先看清 push/pull 的影响。

**门禁（push 前，阻断，全过才 push）**
- **隐私门**：`sync.sh audit`（绝对路径 / 邮箱 / UUID·密钥 / 内部名）。
- **许可证来源门（关键）**：确认没有 **AGPL 来源文本**（从 Trellis 出厂文件拷来的 seed/原文）混进 Apache 的 Arborist。`sync.sh audit` 会标可疑 seed 短语；你人判——Arborist 只收**原创**内容。
- **占位完整性**：push 后 staging **不得残留具体值**（`$INSTANCE_ABS`/`$PROJECT`/`$HOME`）；pull 后实例 **不得残留 `<REPO_ROOT>`/`<project>`/`<HOME>` 占位**（`sync.sh verify-placeholders`）。
- **实例私有排除**：Multica IDs/env、workflow.md 里 `<project>` 具体值、`tasks/`、`workspace/`、`.harness-vcs/` —— **永不上推**。

**合并**
- **带 base 的三方合并**：读/写 `INSTANCE_ROOT/.arborist-sync/manifest`（记上次同步两侧 commit SHA）；两侧都动过同一文件时用 base 做 3-way，别瞎猜。同步成功后更新 manifest。
- **增/删传播 + 索引**：新增 guide → 加进 Arborist **并更新 `overlay/spec/guides/index.md` 表**；删除要传播。

**校验 / 治理**
- **同步后一致性检查**：`index.md` / `workflow.md` 指向 guide 的链接、ADR 索引——**不悬空**。
- **可回滚 + 报告**：实例侧 `hgit` 可退；Arborist 侧普通 commit（**不 force**）。结尾报告：同步了啥 / 去隐私了啥 / 冲突怎么解 / 剩什么。
- **不碰 `LICENSE`/`NOTICE`**；Arborist commit 用英文、守其规范。
- **首次 vs 增量**：新实例首次走 `adopt.sh` 全量；之后仅增量。

## 铁律
- **绝不盲目覆盖**：两向都先 diff + 意图合并 + 冲突交人。
- **push 前三门必过**（隐私 + 许可证来源 + 占位完整性），任一不过则中止。
- 脚本只做 copy+sed+扫描；**审计裁定 + 冲突调解 + 增删/索引判断是你（Agent）的活**——这就是它是 Skill 不是纯脚本的原因。
- 主流向是 push（实例=实验田→泛化上模板）；pull 用于模板收到外部贡献时。

## 长期更省心
若把 guide 正文做到**完全泛化**（实例特例移进 workflow.md 定制层 + host-config），两边 guide 就一致，同步退化成纯拷贝 / `git subtree`，无需本 Skill 的 sed 转换（仍需冲突判断）。见 README「适配面」。
