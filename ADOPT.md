# 采纳 Arborist

把本 overlay 叠进一个已用 Trellis 的项目仓。核心理念：**overlay 铺进 `.trellis/spec/guides/` + 少量 workflow.md 定制，用 `.git/info/exclude` 从产品仓隐身，用独立 `hgit` 本地仓记历史。**

## 前置（依赖分级见 [`overlay/spec/guides/tool-registry.md`](./overlay/spec/guides/tool-registry.md) §2.5）
- **required（不装没法用；adopt.sh 会探测，缺失醒目告警 + 给装法，不中断铺设）**：
  - **Trellis**：`npm i -g @mindfoldhq/trellis`，并在你项目 `trellis init --claude --codex -u <name>`（选你的平台）。
  - **Superpowers**（workflow 定制层各步骤依赖其 skills）：Claude Code 内 `/plugin install superpowers@claude-plugins-official`。
- **optional（拒装走各自 fallback，不卡流程）**：`agentsview`（agent 会话历史检索）、`multica`（issue 台账）、`codegraph`（符号图谱 MCP）。adopt.sh 末尾逐个探测处理，见「手动收尾」。

## 一键
```bash
cd /path/to/your-repo
bash /path/to/Arborist/adopt.sh
```
脚本做：required 依赖检查（Trellis/Superpowers，缺失只告警）→ 铺 guides / scripts / hgit / `.work_context` 模板 / `.arborist/` 注册表骨架 → 写 `.git/info/exclude` → 建 `.harness-vcs` 本地仓打基线 → optional 工具置备（逐个问，绝不代装）。

## 手动收尾（脚本会提示）
1. **workflow.md 定制层**：把 [`overlay/workflow-customization.md`](./overlay/workflow-customization.md) 的块粘进 `.trellis/workflow.md`（`## Core Principles` 后），替换 `<占位>`；并按其尾注调 Phase 1/2/3：
   - Phase 1 加 `1.0b research-first + RepoMem.read`（required·read-only，先于 brainstorm）；
   - `[workflow-state:planning]` / `[workflow-state:planning-inline]` / Active Task Routing 里 `Load trellis-brainstorm` → 改指 SP `brainstorming`（防双跑）；
   - Phase 2.2 加验证拓扑（双 lens + security-scan 接 MR 硬门 + 人工 smoke）；
   - Phase 3.3 加 ADR 分流 + HITL 晋升门 + Challenge-before-ack；
   - Phase 3.4 defer 你的 git/MR 约定；Phase 3.5 加 Multica WIMTB。
2. **Multica**（可选）：设 `MULTICA_WORKSPACE_ID` / `TRELLIS_MULTICA_PROJECT_ID`；`.trellis/config.yaml` 挂 `hooks.after_start/after_archive: python3 scripts/trellis_multica_sync.py on-start|on-archive` + `session_auto_commit: false`。不用 Multica 则跳过。
3. **codegraph**（可选）：`codegraph init && codegraph install`（写 `.mcp.json`）。
4. **optional 工具置备的行为**（agentsview / multica / codegraph；guide：[`tool-registry.md`](./overlay/spec/guides/tool-registry.md) §2.5）：adopt.sh 末尾逐个探测——已装则问「登记进 `~/.arborist/tools/`？」（同意 → 从模板拷 `tool.json`，幂等不覆盖，再把 `<占位>` 换实况）；未装则问「需要吗？」（同意 → 只打印装法，**不代装**）；拒绝 → 打印该工具 fallback（如 Multica 拒装 = 台账退化为本地 `.trellis/tasks/` + sendbox 交办），流程照常。非交互（CI/pipe）只打汇总，不 prompt、不失败。
5. 重启 AI session。

## 适配面（替换 一个内部仓 worked-example）
| 占位 | 换成 |
|---|---|
| `<REPO_ROOT>` | 你仓库绝对路径（sendbox read_first 需绝对路径）|
| Multica IDs | 你的 workspace/project（env）|
| 子树/语言、安全扫描器 | 你的（示例 Go+npm / govulncheck+npm audit）|
| git/MR 约定 | 你的（示例 GitLab 发布列车 + `/commit` `/pr`）|
| 本地文档约定 | 你的（示例 `.work_context/` + engineering.md §12）|

## 日常
- **harness 改动**：`./hgit add -f <path> && ./hgit commit -m "..."`；回退 `./hgit checkout <sha> -- <path>`；产品代码照常 `git`。
- **多机/团队**：`./hgit remote add origin <url> && ./hgit push`（届时把 `.developer`/tasks 等 per-machine 项从跟踪收窄）；或 Trellis 原生 `trellis init -r gh:org/repo/specs` / `--workflow-source`。

## 卸载
删 `.git/info/exclude` 里 overlay 段 + `.harness-vcs/` + 铺进去的 guides/scripts；`git status` 恢复。
