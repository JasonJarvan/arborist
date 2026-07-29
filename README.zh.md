# Arborist

> **A stronger agent harness for ultra-long-horizon coding — the Trellis + HarnessStack workflow & orchestration core.**
>
> 专为超长程 Coding 任务设计的更强 agent harness —— Trellis + HarnessStack 的工作流与编排内核。
>
> 血统 / lineage：**[Trellis](https://www.npmjs.com/package/@mindfoldhq/trellis)**（工作流引擎）× **CodeTeam 方法论**（HarnessStack 纪律层）。
>
> **[Arbor](https://github.com/JasonJarvan/arbor)（Apache-2.0）的 fork**，剥离了 CCB 多代理运行时 —— 见 [与 Arbor 的关系](#与-arbor-的关系)。

`Apache-2.0` · `Trellis 的 overlay` · `依赖：Trellis —— AGPL，自行安装、不打包` · [English README](./README.md)

**是什么。** Arborist 是一个**可 adopt 的 overlay**，把 Trellis 增强成一套能扛**超长程编码**的 harness —— 一个目标跨几十个会话、多个并发子任务、需要审计与回退。
**给谁。** 面向在多会话里做 AI 编码的团队（或个人）：当单个 agent 跨会话「丢了线索」、门被静默跳过、harness 改动无法干净回退时，你需要它。
**解决什么。** 它在 Trellis 之上叠加角色分层、显式门控、记忆分层、跨会话语义交办 —— 且**全程不污染产品仓**;瞬态协调后端保持可插拔（见下）。

两支柱：

- **Trellis** —— 工作流引擎（3 阶段 Plan/Execute/Finish、任务系统、breadcrumb）。
- **CodeTeam 方法论** —— 吸纳自 HarnessStack 的纪律层：L1–L4 角色分层、显式门控（含 auto-judge/HITL）、记忆分层（RepoMem + ADR + 晋升门 + challenge-before-ack）、多镜头验证、sendbox 语义交办、Dashboard 待办投影、任务台账。

两层编排分工：**任务台账存任务档案 · sendbox 存 durable 语义交办（内置的文件通道）**。而**瞬态实时协调**后端（可见多 window TUI、A2A 自动回投运行时……）是**可插拔扩展点** —— 缺省不内置具体实现；开箱即用时，瞬态协调靠人在并发 session 间带话，或用 Trellis 原生 subagent 做单会话 fan-out。

它不是 fork Trellis，而是一个**可 adopt 的 overlay**：照常 `trellis init`，再把本仓 overlay 叠上去。**全程不污染产品仓**（`.git/info/exclude` + 独立 `hgit` 本地版本仓）。它**是** Arbor 的 fork —— 见下文。

---

## 为什么需要它（Trellis 之外多了什么）

Trellis 原生擅长：任务脚手架、per-turn breadcrumb、跨工具对话检索（`trellis mem`）、TDD 模板。但面对**超长程任务**（一个目标跨几十个会话、多个并发子任务、需要审计和回退），会缺几层。Arborist 补齐：

| 能力 | Trellis 原生 | Arborist 增强 |
|---|---|---|
| **角色/任务分层 L1–L4** | parent/child + 子代理 | 显式 **RootOrche / SubOrche / Impler / subagent** 四级，各按级别挑 Pipeline steps；生命周期走查（fast 单改 / full 特性 / 超长程并发） |
| **门控与审计** | 建任务/commit 确认 | 四级 **Execution Policy**（auto / **auto-judge** / ask-first / HITL）+ Skip Bias 轴 + 禁止静默跳过（双机制审计） |
| **记忆分层** | spec 更新 + journal + mem | **三层认知论**（规范/描述/权威）+ ADR（persist/architecture，带 Origin 溯源）+ Document Boundary 权威表 + Pairing Rules + **HITL 晋升门 + Challenge-before-ack**（防橡皮图章） |
| **验证拓扑** | 单 check | 多镜头：trellis-check + 行为自验双 lens + **依赖安全扫描接 MR 硬门** + 人工 smoke |
| **跨会话交办** | mem/journal（回忆） | **sendbox** 定向交办信（`toAgent/`+`toHuman/`，read_first 绝对路径 + process-completeness + 生命周期/WIMTB） |
| **认知负担** | breadcrumb/statusline | **Dashboard** 跨会话「此刻轮到人做什么」单一投影 |
| **持久化** | 本地文件 | **Multica** issue 镜像（一 task=一 issue，parent/child↔L3/L2，完成 WIMTB 附件+摘要） |
| **代码情报** | grep/glob | **codegraph** MCP（符号/调用/影响面）——喂养 red-team 证据、晋升纪律的客观基准 |
| **多代理编排** | 一次性 subagent | **角色分层 + sendbox** durable 交办；瞬态实时协调是**可插拔后端**（不内置）；任务落 Multica |
| **不污染产品仓** | `.trellis/` 提交进仓 | **`.git/info/exclude` overlay + 独立 `hgit` 本地版本仓**：harness 有史可退、却永不进功能分支/push |
| **方法论沉淀** | — | 9 簇 `methodology/`（LLM 测试、验证纪律、契约防漂移、MR、依赖治理、错误处理、本地文档、handoff 归因…）从真实项目提炼 |

---

## 给谁用 / 何时先别用

**适合 adopt** 如果你：在多会话里对一个长目标做 AI 编码、会同时协调不止一个 agent、并且需要工作**可审计、可回退** —— 而且想要这套纪律**却不把 harness 文件提交进产品仓**。

**（暂时）不需要** 如果你的活是单会话、单 agent、短程任务 —— 裸 Trellis（或不上 harness）更轻。Arborist 的价值恰恰在**会话边界、并发子任务、或「我们怎么走到这一步的」审计**会让你付代价时才显现。

基础 overlay 之外一切**可选**：任务台账、codegraph 都是 opt-in。**最小可用** = `adopt.sh` + 粘贴 workflow 定制块。

---

## 快速上手

**方式 A —— 把 prompt 交给 agent（推荐）。** 把 [INSTALL.md](./INSTALL.md) 里的引导 prompt 粘进一个在你仓库根打开的全新 coding-agent 会话；它会装依赖（Trellis，可选 codegraph）、`trellis init`、clone Arborist、跑 `adopt.sh`。

**方式 B —— 手动。**
```bash
# 1) 在你的仓库初始化 Trellis（选平台）
npm i -g @mindfoldhq/trellis        # 必需；可选：codegraph
trellis init --claude --codex -u <your-name>

# 2) 叠加 Arborist overlay
git clone https://github.com/<owner>/arborist.git /tmp/arborist
bash /tmp/arborist/adopt.sh            # 见 ADOPT.md：铺 guides、装 overlay、建本地版本仓、写 .git/info/exclude

# 3) 重启 AI session —— workflow.md 定制层 + guides 即生效
```
细节、逐步适配、可调项：见 **[ADOPT.md](./ADOPT.md)**。

### Adopt 之后你会得到什么（最小首跑）

对一个原样的仓库，`adopt.sh` 铺下这些 —— 全部被 `.git/info/exclude` 对产品 git 隐身：

- `.trellis/spec/guides/` —— 纪律与方法论 guides（[索引](./overlay/spec/guides/index.md)），agent 在 Plan/Execute/Finish 时按需读。
- `.trellis/workflow.md` —— 你粘入[定制块](./overlay/workflow-customization.md)后，Pipeline（门控、验证拓扑、晋升门）即生效。
- `AGENTS.md` + workflow Phase Index —— 两处一致的 `ARBORIST-BRAND-COMPAT:v1` managed block，让 Codex 与 Claude Code 都按真实 brand 保持同品牌 subagent 链。
- `.claude/agents/trellis-implement-full.md` + `trellis-explore.md` —— Claude Code 的固定 Opus/Sonnet 路由，不依赖全局 subagent model 环境变量。
- `.work_context/` —— sendbox（定向交办信）+ Dashboard（待办投影）脚手架。
- `.harness-vcs/` + `hgit` —— harness 专用本地版本仓，`hgit log` / `hgit checkout <sha>` 与产品 `git` 解耦地回退。

重启 AI session，guides + workflow 定制生效。产品仓 `git status` 保持干净 —— 以上一切它都看不见。

---

## 架构：overlay + 本地版本仓

- **overlay**：本仓 `overlay/` 铺进你项目的 `.trellis/spec/guides/`、`scripts/`、`.work_context/` 模板 + 一段 workflow.md 定制层。
- **不进产品仓**：这些路径写进你项目的 `.git/info/exclude`（per-clone，不提交）→ 产品仓 / 功能分支 / push **永远看不见**。
- **有史可退**：一个独立 git 仓（`.harness-vcs`，无 remote）+ `hgit` wrapper 专门版本化 harness——`hgit log` / `hgit checkout <sha> -- <path>` 回退，与产品 `git` 互不干扰。
- **多机/团队**：`hgit remote add` + push 即变共享；或走 Trellis 原生 `--workflow-source` 自定义 marketplace。

三个仓，刻意分开：

```
        ┌──────────────────────────────────────┐
        │  Arborist 模板仓（本仓）                  │   Apache-2.0
        │  overlay/ guides · scripts · templates│   泛化；占位 <REPO_ROOT>/<project>
        └───────────────────┬──────────────────┘
                            │  adopt.sh （铺 overlay + 特化占位）
                            ▼
  ┌──────────────────────────────────────────────────────────┐
  │  你的产品仓  (git)                                        │
  │                                                           │
  │    src/  ...................  你的代码 —— 照常 commit/push │
  │    .trellis/spec/guides/  ...  overlay（harness 本体）     │
  │    .git/info/exclude  ........  让 overlay 对产品 git 隐身 │
  └───────────────────────────┬──────────────────────────────┘
                              │  harness 改动由此版本化
                              ▼
  ┌──────────────────────────────────────────────────────────┐
  │  .harness-vcs   (hgit —— 本地 git 仓，无 remote)          │
  │    hgit log   ·   hgit checkout <sha> -- <path>  （回退）  │
  └──────────────────────────────────────────────────────────┘
```

产品 remote 永不见 harness；harness 有自己可回退的历史；Arborist 上游保持泛化，改进两向流动（见 [`arborist-sync`](./skills/arborist-sync/SKILL.md)）。

---

## Guides（本仓核心）

Arborist 的核心是它的纪律 + 方法论 guides，铺进 `.trellis/spec/guides/`。含「何时读」的完整索引见 [`overlay/spec/guides/index.md`](./overlay/spec/guides/index.md)。

| Guide | 覆盖 |
|---|---|
| [角色层与任务分层 L1–L4](./overlay/spec/guides/roles-and-tiering.md) | RootOrche / SubOrche / Impler / subagent + 各级 Pipeline 切片 + 生命周期场景 |
| [Execution Policy & Skip](./overlay/spec/guides/execution-policy.md) | 四级门控（auto / auto-judge / ask-first / HITL）+ Skip Bias + 跳过审计 |
| [RepoMem：文档边界与晋升](./overlay/spec/guides/repomem-doc-boundary.md) | 三层认知论 + Document Boundary 权威表 + Pairing Rules + persist 纪律 |
| [Verification & Gates](./overlay/spec/guides/verification-and-gates.md) | 多 lens 验证 + security-scan 接 MR 硬门 + 评审 + challenge-before-ack |
| [Sendbox 定向交办](./overlay/spec/guides/sendbox.md) | 跨 session 定向交办信（read_first 绝对路径 + process-completeness + 生命周期/WIMTB） |
| [Dashboard 待办投影](./overlay/spec/guides/dashboard.md) | 跨 session「此刻轮到人做什么」单一投影 |
| [AgentTUI 注册表](./overlay/spec/guides/agenttui-registry.md) | 并发 session 同伴发现：`.arborist/` 级联 + spec/runtime schema + 声明/派生状态模型 + 自登记 |
| [安全启动 AgentTUI + brand-capacity observer](./overlay/spec/guides/agenttui-launch-and-brand-capacity.md) | 安全启动不变量（一 tab 一 ATUI、清父身份、resolve 稳定非插件 pane、启动器选二进制而会话自登记 brand）+ 单写者无凭证容量 observer（source/freshness 显式、仅建 Impler 前推荐） |
| [工具注册表](./overlay/spec/guides/tool-registry.md) | 可选能力插件层：`.arborist/tools/` 级联 + `tool.json` schema + required/optional 置备与逐工具 fallback |
| [知识收尾（洁癖式）](./overlay/spec/guides/knowledge-closeout.md) | 交付后全仓知识一致性门：事实面矩阵 + 两阶段汇报 + 触发分级（收尾方自跑，补 trellis-check 改动面之外）；可在任意 lane 用 `/neat`、`neat skill`、`洁癖 skill` 手动触发 |
| [HS 15-step 落点映射](./overlay/spec/guides/pipeline-mapping.md) | HarnessStack 15 步 → Trellis 阶段/guides 对照 |
| [方法论簇](./overlay/spec/guides/methodology/index.md) | 9 簇（LLM 测试 / 验证纪律 / 契约防漂移 / MR / 依赖治理 / 错误处理 / 本地文档 / handoff 归因 …） |
| [ADR 模板](./overlay/spec/guides/decisions/TEMPLATE.md) | 架构决策记录（三门自检 + `Origin` 溯源） |

机制展开讲透的阐释页（时间线、状态机、走查）见 [`docs/wiki/`](./docs/wiki/index.md)；规范本体仍以上表 guides 为准。

---

## 适配面（本仓以 一个内部仓 为 worked example，adopt 时替换）

- `<REPO_ROOT>` → 你仓库的绝对路径（sendbox read_first 需绝对路径）。
- Multica：设 `MULTICA_WORKSPACE_ID` / `TRELLIS_MULTICA_PROJECT_ID`（不用 Multica 则禁用 config.yaml 的 hooks）。
- 子树/语言（示例是 Go+npm 多子树）、安全扫描器（govulncheck / npm audit）、git/MR 约定（示例是 GitLab 发布列车 + `/commit` `/pr`）→ 换成你的。
- 本地文档约定（示例 `.work_context/` + engineering.md §12）→ 换成你的。

---

## 目录

```
overlay/spec/guides/            # 纪律与方法论 guides（本仓核心）
  roles-and-tiering.md          # L1–L4 角色/分层 + 生命周期
  execution-policy.md           # 四级门控 + Skip + hooks add-only
  repomem-doc-boundary.md       # 记忆分层 + 文档边界 + Pairing
  verification-and-gates.md     # 多 lens + security gate + challenge-before-ack
  sendbox.md / dashboard.md     # 跨会话交办 / 待办投影（host 配置 + 规范）
  pipeline-mapping.md           # HarnessStack 15-step → Trellis 落点
  decisions/TEMPLATE.md         # ADR 模板（带 Origin）
  methodology/                  # 9 簇工程纪律（真实项目提炼）
overlay/scripts/                # trellis_multica_sync.py（env 配置）+ hgit
overlay/project-instructions/   # Codex 自动可见 managed 指令源
overlay/platform-templates/     # 平台专属 managed agent 模板
overlay/work_context-templates/ # sendbox（toAgent/toHuman）+ Dashboard 脚手架
overlay/workflow-customization.md # workflow.md 定制层
scripts/                        # brand compatibility installer + validator
skills/arborist-sync/              # 双向 overlay 同步（去隐私 + 冲突调解）
adopt.sh / ADOPT.md             # 一键 adopt + 说明
```

---

## 与 Arbor 的关系

Arborist 是 **[Arbor](https://github.com/JasonJarvan/arbor)（Apache-2.0）的 fork**。Arbor 的血统是
**Trellis（工作流内核）+ HarnessStack（多代理编排纪律）+ CCB（可见多 window TUI / A2A 通信运行时）**。
Arborist 保留前两者，**完全移除 CCB** —— 是那个不绑定后端的 harness 内核。

**相对 Arbor 的改动：移除了 CCB 运行时，瞬态实时协调后端改为可插拔扩展点。**

| | Arbor | Arborist |
|---|---|---|
| Trellis 工作流内核 | ✅ | ✅ |
| HarnessStack 纪律（角色/门控/RepoMem/验证/方法论）| ✅ | ✅ |
| Sendbox durable 文件交办 | ✅ | ✅ |
| 瞬态实时协调运行时 | **CCB**（内置，tmux pane agents + `ask`）| **可插拔扩展点，不内置** |
| 依赖足迹 | Trellis + 可选 CCB | 仅 Trellis |

**为什么 fork。** 一些采纳者想要工作流 + 编排纪律，却不想绑定某个具体终端复用器或 A2A 后端。Arborist 就是这一层：
durable 编排走 sendbox 文件协议，瞬态后端如需可另行外接。两者的改进通过泛化、后端中立的 guide 双向流动。

---

## 贡献

Arborist 是一套泛化的工程纪律语料 —— 欢迎贡献新的方法论簇、guide 改进、adopt/sync 工具。铁律：guide 保持泛化（用占位符，无绝对路径 / 内部名 / 密钥）、绝不拷入源自 AGPL 依赖的文本、commit 用英文。见 **[CONTRIBUTING.md](./CONTRIBUTING.md)**。

---

*吸纳自 HarnessStack（OpenSpec / Superpowers / RepoMem / ECC 方法论）。Trellis 是 MindfoldHQ 的作品；本仓是其上的增强 overlay，不隶属、不 fork。*

---

## License

Arborist 本体（guides / scripts / config 模板 / 文档）以 **Apache-2.0** 开源（见 `LICENSE`）。

**依赖工具各自独立、Arborist 不打包其代码**：Trellis（AGPL-3.0-only）、可选 codegraph / Multica 均需你**自行安装**，仍受其各自 license 约束。Arborist 只通过 CLI 与它们互操作（独立进程），是**互操作性 overlay**，非其衍生作品。

> English: see [README.md](./README.md).
