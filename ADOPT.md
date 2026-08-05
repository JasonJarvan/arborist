# 采纳 Arborist

把本 overlay 叠进一个已用 Trellis 的项目仓。核心理念：**overlay 铺进 `.trellis/spec/guides/` + 少量 workflow.md 定制，用 `.git/info/exclude` 从产品仓隐身，用独立 `hgit` 本地仓记历史。**

## 前置（依赖分级见 [`overlay/spec/guides/tool-registry.md`](./overlay/spec/guides/tool-registry.md) §2.5）
- **required（不装没法用；adopt.sh 会探测，缺失醒目告警 + 给装法，不中断铺设）**：
  - **Trellis**：`npm i -g @mindfoldhq/trellis`，并在你项目 `trellis init --claude --codex -u <name>`（选你的平台）。
    > ⚠️ **若 `.claude/settings.json` 已被产品仓 git-tracked**（团队共享配置的常见形态）：`trellis init -y` 会**跳过**它以免覆盖团队文件，**后果是 hook 没装上**——SessionStart 不注入，`[local]` 块（含下面的自登记入口）一条都不到达 session，而 init 本身**不报错**。改把 hook 写进 **`.claude/settings.local.json`**（Claude Code 读它、且它按约定不进产品 git），产品文件**零改动**。装完务必**机械验证 hook 真的命中**（起一个新 session 看 `[local]` 行有没有出现），别只看 init 的成功输出。
  - **Superpowers**（workflow 定制层各步骤依赖其 skills）：Claude Code 内 `/plugin install superpowers@claude-plugins-official`。
- **optional（拒装走各自 fallback，不卡流程）**：`agentsview`（agent 会话历史检索）、`multica`（issue 台账）、`codegraph`（符号图谱 MCP）。adopt.sh 末尾逐个探测处理，见「手动收尾」。

## 一键
```bash
cd /path/to/your-repo
bash /path/to/Arborist/adopt.sh
```
脚本做：required 依赖检查（Trellis/Superpowers，缺失只告警）→ 铺 guides / scripts / hgit / `.work_context` 模板 / `.arborist/` 注册表骨架 → 把 `ARBORIST-BRAND-COMPAT:v1` 幂等写入 `AGENTS.md`（Trellis 块外）和 workflow Phase Index（Phase 1 前）并安装 Claude 固定模型 agents → 写 `.git/info/exclude` → 建/校正 `.harness-vcs` 本地仓（**首次建时用 `hgit snapshot` 打 durable 基线**；**每次 adopt 都按 allowlist 校正侧史 exclude** + 探测可见性；已存在的侧史仓**只校正 exclude、不暂存任何文件**，落定归 gardener）→ optional 工具置备（逐个问，绝不代装）。

### 侧史可见性：allowlist 的效力边界（重要）
侧史 exclude 写的是 allowlist（不是裸 `/*`），用意是让 durable 面（`.trellis/spec/**`、`.trellis/scripts/`、`.arborist/tools/`、`.work_context/sendbox/`）里**新建的未跟踪文件对 `hgit status` 现形**，运行时态 / 缓存 / 备份 / 凭证 `*.env` 继续隐身；块外 adopter 自加条目原样保留。

但 gitignore 优先级是**源级**的：**产品仓工作树里的 `.gitignore` 严格压过 `$GIT_DIR/info/exclude`**（无论该 `.gitignore` 是否已被产品仓跟踪）。侧史的 work-tree 就是产品仓根，所以：

- 产品仓的 `.gitignore` **没有**把 harness 目录列进去 → allowlist 生效，新建 durable 文件确实对 `hgit status` 现形。
- 产品仓的 `.gitignore` **列了** `.trellis/` 一类 harness 目录（很多仓为防误提交会这么写；Arborist 自己的仓就是）→ 该面的 allowlist **完全失效**，且带尾斜杠的 `.trellis/` 会终止目录遍历，底下任何 negation 都救不回来 —— 这是 git 语义，无法从我们这层绕过。adopt.sh 会用 canary 路径探测并打 `✗✗` 告警指明压制来源。

**两种配置下都成立的 durable 捕获面**是显式快照 `./hgit snapshot`：它按固定 durable 白名单**逐文件**枚举并 `add -f`，不依赖 untracked 可见性；同时逐文件剔掉 `*.env` / `__pycache__/` / `*.pyc` / `*.bak` 等，凭证与缓存**绝不进史**。

## 手动收尾（脚本会提示）
1. **workflow.md 定制层**：把 [`overlay/workflow-customization.md`](./overlay/workflow-customization.md) 的块粘进 `.trellis/workflow.md`（`## Core Principles` 后），替换 `<占位>`；并按其尾注调 Phase 1/2/3：
   - Phase 1 加 `1.0b research-first + RepoMem.read`（required·read-only，先于 brainstorm）；
   - `[workflow-state:planning]` / `[workflow-state:planning-inline]` / Active Task Routing 里 `Load trellis-brainstorm` → 改指 SP `brainstorming`（防双跑）；
   - Phase 2.2 加验证拓扑（双 lens + security-scan 接 MR 硬门 + 人工 smoke）；
   - Phase 3.3 加 ADR 分流 + HITL 晋升门 + Challenge-before-ack；
   - Phase 3.4 defer 你的 git/MR 约定；Phase 3.5 加 Multica WIMTB。
2. **Brand compatibility 自检**：安装过程不会覆盖 managed block 外的 `AGENTS.md` / workflow 文本，也不会覆盖用户自有的同名 Claude agent。已有 `_handoff-config.yaml` 若仍是旧 schema，adopt 会保留原文件并 fail closed，提示按新模板人工合并。验证已安装结果：`python3 scripts/install-brand-compat.py --source-tree /path/to/Arborist --check`。
3. **Multica**（可选）：设 `MULTICA_WORKSPACE_ID` / `TRELLIS_MULTICA_PROJECT_ID`；`.trellis/config.yaml` 挂 `hooks.after_start/after_archive: python3 scripts/trellis_multica_sync.py on-start|on-archive` + `session_auto_commit: false`。不用 Multica 则跳过。
4. **codegraph**（可选）：`codegraph init && codegraph install`（写 `.mcp.json`）。
5. **optional 工具置备的行为**（agentsview / multica / codegraph；guide：[`tool-registry.md`](./overlay/spec/guides/tool-registry.md) §2.5）：adopt.sh 末尾逐个探测——已装则问「登记进 `~/.arborist/tools/`？」（同意 → 从模板拷 `tool.json`，幂等不覆盖，再把 `<占位>` 换实况）；未装则问「需要吗？」（同意 → 只打印装法，**不代装**）；拒绝 → 打印该工具 fallback（如 Multica 拒装 = 台账退化为本地 `.trellis/tasks/` + sendbox 交办），流程照常。非交互（CI/pipe）只打汇总，不 prompt、不失败。
6. 重启 AI session。

## 适配面（替换 一个内部仓 worked-example）
| 占位 | 换成 |
|---|---|
| `<REPO_ROOT>` | 你仓库绝对路径（sendbox read_first 需绝对路径）|
| Multica IDs | 你的 workspace/project（env）|
| 子树/语言、安全扫描器 | 你的（示例 Go+npm / govulncheck+npm audit）|
| git/MR 约定 | 你的（示例 GitLab 发布列车 + `/commit` `/pr`）|
| 本地文档约定 | 你的（示例 `.work_context/` + engineering.md §12）|

## 日常
- **harness 改动**：`./hgit snapshot --dry-run` 复核 → `./hgit snapshot && ./hgit commit -m "..."`；回退 `./hgit checkout <sha> -- <path>`；产品代码照常 `git`。
  - `snapshot` 的白名单：`.trellis/spec` `.trellis/scripts` `.trellis/workflow.md` `.trellis/config.yaml` `.arborist/tools` `.work_context/sendbox` `AGENTS.md` `hgit` `.claude/agents/trellis-{explore,implement-full}.md` `scripts/{trellis_multica_sync,install-brand-compat,validate_brand_compat}.py`。要改这张面就改 `overlay/scripts/hgit` 的 `SNAPSHOT_PATHS`（adopt 打基线用的是同一张，不另写一份）。
  - 想只落定单个文件仍可 `./hgit add -f <path>`。**别**手写 `./hgit add -f .trellis .work_context` 这类整面 force-add：会把 `.work_context/multica.env` 一类凭证与运行时机器态（`tasks/**`、`workspace/**`、`Dashboard/**`）钉成 tracked，而 exclude 只管未跟踪文件 —— 钉上就再也隐不回去。删除 durable 文件用 `./hgit rm <path>`（`snapshot` 只暂存现存内容）。
- **多机/团队**：`./hgit remote add origin <url> && ./hgit push`（届时把 `.developer`/tasks 等 per-machine 项从跟踪收窄）；或 Trellis 原生 `trellis init -r gh:org/repo/specs` / `--workflow-source`。

## 卸载
删 `.git/info/exclude` 里 overlay 段 + `.harness-vcs/` + 铺进去的 guides/scripts；`git status` 恢复。
