# 角色/任务分层 L1–L4 + 生命周期（<project>，吸纳自 HarnessStack）

> 同一个人同时开多 session，共享这一套 harness，各按级别从 Pipeline 挑 steps；级间靠 sendbox 交办。**四级**（顶→底）：

| 级 | 角色 | = Trellis | Multica | 强制力 |
|---|---|---|---|---|
| **L4** | **RootOrche** 根编排 | 与 human 对话、编排整仓；非被派任务 | 对应 <project> 项目/repo 级 | **无强制力**（顶，人直接接口，无上级派它）|
| **L3** | **SubOrche** 子编排 | parent task（管一批 L2 的开放任务）| L3 父 issue（架构决策+进度矩阵）| 受 L4 派 |
| **L2** | **Impler** 实现者 | child task（一个可独立验证交付）| L2 子 issue（`multica_parent`→L3）| 受 L3/L4 派 |
| **L1** | **subagent**（**auto-spawn**）| 无 task/issue，短生命 | — | 由 L2 自动派（trellis-implement/check/research）|

（与 **Lane(fast/full) 正交**：L1–L4 是角色/任务结构；fast/full 是文档集大小。）

## L2→L1 brand 不变式

`effective_subagent_brand = impler.spec.brand`

Impler 派出的 implement、TDD、refactor、Explore、check、challenge、research 等 L1 工作都继承 Impler 在 AgentTUI 注册表中如实登记的 brand，形成 **same-brand** chain。`brand=codex` 时全链路使用 Codex subagents；`brand=claude-code` 时全链路使用 Claude Code subagents。模型档位只能在选定 brand 内决定，不能用另一个 provider 的模型名把工作跨 brand 转发。

派活前必须先解析 Impler 的实际 brand。brand 缺失、未知，或 dispatch provider 与 Impler brand 发生 **brand mismatch** 时必须 **fail closed**：停止派活并修正注册或 handoff；不得猜测默认 brand、不得伪装兼容、不得降级为跨 brand 路由。

## 各级跑哪些 Pipeline steps

- **L4 RootOrche**：Phase 1 research-first + brainstorm（与 human）→ 分解 L3/L2 任务、定 Lane → 派活（sendbox）→ Phase 3 **轻量 accept**（跨任务一致性 + 翻 ADR `proposed→accepted` + commit/push/MR 对 human；见下「收尾职责分层」）。**不**跑 L2 的 TDD loop、**不**替 L2 做本任务收尾起草。
- **L3 SubOrche**：把 parent(L3) 分解/排序成 child(L2)、维护 L3 dashboard、逐个派 L2 给 Impler、cohort 集成验收 → 回报 L4。**不**直接实现、**不**替 L4 做对-human 的 HITL。
- **L2 Impler**：本 L2 的 1.0b research-first + RepoMem.read → Phase 2 TDD loop（红-绿-重构，**派 L1 subagent** 做切片）→ 3.3 **收尾起草**（见下「收尾职责分层」：full-lane 起草 ADR `proposed` + 派独立 challenge subagent + 打包「待接受包」；fast-lane 全权自收尾）→ sendbox 回报 done。
- **L1 subagent**：`trellis-implement`/`trellis-check`/`trellis-research` 自动派生，做单一切片/检查/检索；不再往下派、不越权。dispatch prompt 带 `Active task:`（见 workflow.md 2.1）。

## 收尾职责分层（close-out split · 防 rootorc 阻塞）
收尾不再整块压在 L4；按 Lane 切：
- **fast lane**：L2 Impler **全权收尾**（自 trellis-check + 行为自验 + WIMTB 自任务 + flip status）；无 L4 门。commit 仍 ask-first 对 human。
- **full lane**：L2 Impler 做**收尾起草**——check/自验 → WIMTB 自任务草稿 → ADR 候选**写成 `Status: proposed` 的真文件**（不再只 surface 文本）→ **派独立 challenge subagent** 唱反调（见 `verification-and-gates.md` «Challenge-before-ack»）→ 备好 commit/status 但不执行 → done 信打包**「待接受包」**（proposed ADR 列表 + WIMTB 草稿 + challenge 裁定 + 拟提交范围）回 L4。
- **L4 轻量 accept**：只做 L2 做不了的——**跨任务/集成一致性扫描**（唯 L4 见姊妹任务）+ **翻 ADR `proposed→accepted`**（晋升最终权）+ **commit/push/MR**（对 human）+ flip issue status done。
- **永不下放（rootorc/human 安全边界）**：产品仓 commit/push · 跨任务裁决 · ADR 最终接受。
- **Impler 收敛：可「问」orch，不可「转派」给 orch**（close-out split 的本意，见 [ADR-0004](./decisions/0004-closeout-split-l2-draft-l4-accept.md)）：起草收敛后仍有残务，出口是**收敛自己做完**，不是把活弹回上级。
  - **可以问**（成本低、保住第二双眼睛）——把这些写成 done 信里的**「Impler 提的问题」清单**：冲突仲裁、跨任务 / 对外契约的验收、scope 缺陷、blocker。问题是「请你判断 X」，不是「请你替我做 X」。
  - **不可转派**：别把「帮我 commit / 帮我翻这个开关 / 帮我 reconcile 这几处」递上去——那是把 split 本要消除的瓶颈重新造回来，也模糊了交付归属。运行 commit/branch/MR 流程本身（受 human ask-first 约束）**留在 Impler**。
  - **orch 确需动手的写成具名例外 + 理由**，别把「弹回上级」当默认：如**架构决策的最终验收**、**跨任务一致性裁决**、**ADR `proposed→accepted`**——这些本就是 L4/human 保留项（见上「永不下放」），以「具名例外 + 为何非 orch 不可」的形式交接，而非泛泛「交回你了」。

## worktree 步与纪律（L2/L3 默认在 worktree 工作）

L2/L3 默认在独立 `git worktree` 里干活，把产品代码与并发 session 隔离。但 `git worktree` 只物化 **tracked** 文件，而 harness overlay（`.trellis/ .work_context/ .arborist/ .claude/ docs/`）对产品仓 git 隐身（`.git/info/exclude`）→ 新 worktree 里这些**全缺** → 从 cwd 解析仓根的工具（`task.py` / multica / codegraph）**静默返回空**（`task.py list` 报 0 而非报错），跨任务一致性自检得到**假阴性**，护栏静默失效。

- **worktree 步 = 建完 worktree 立刻跑 `scripts/harness_worktree_link.sh`**：它把上述 harness 目录从当前 worktree symlink 回主树（用 `git rev-parse --git-common-dir` 定位主树，不写死路径），幂等、可重跑。不跑这一步，本 worktree 里所有 cwd 根工具与护栏都在「静默空世界」里运行。

> **这一步目前无上游机械执行者**：stock Trellis 的任务记录有 `worktree_path` 字段却**无 setter 子命令**、激活步也不校验它非空——所以「先建 worktree」现在只靠执行方记得，属荣誉制门。link 脚本是 Arborist 侧能给的缓解（手动、幂等），但真正的机械闭合要等上游补 setter/激活校验。缺口登记见 [`verification-and-gates.md` «已知上游 Trellis 缺口»](./verification-and-gates.md#已知上游-trellis-缺口门存在但无执行者)。

两条 symlink 引入的纪律，务必内化：

- **搜索用 `-R`，不用 `-r`**：`grep -r` **不跟随 symlink 目录**，对 symlink 化的 harness 目录返回**静默零命中**（不报错），会让你误判「仓里没有 X」。一律 `grep -R`（或用跟随符号链接的检索工具）。这是工具级已知局限，详见 [tool-registry 已知局限](./tool-registry.md#已知局限)。
- **写 symlink 化的 harness 目录 = 写共享主树状态**：产品代码被 worktree 隔离，但落 spec / 改 guide / 写任务态（`.trellis/` `.work_context/` `.arborist/`）会**立刻影响所有并发 session**——因为它们物理上就是主树那一份。改这些前按归属边界确认是你 lane、且知会到并发方。

故意**不** symlink 两样（与脚本注释同源）：

- **codegraph 索引目录**：索引基于**主树代码**构建，worktree 里经 symlink 复用会让 `impact`/依赖分析对着**另一棵树**的代码状态给结论——那状态在本 worktree 并不存在。**静默错比不可用更糟**。要么在 worktree 内单独建索引，要么把该能力当不可用并按 tool-registry fallback 上报。
- **hgit 式 wrapper 及其 git-dir**（`hgit` + `.harness-vcs/`）：wrapper 用 `dirname $0` 推根并作为 `--work-tree` 传给底层 git，symlink 会让根**指错树**、令 `--work-tree` 落在错误工作树上。它本就应只在主树里对主树运行。

> exclude 侧配套：symlink 要能被 `git check-ignore` 匹配、令 `git status` 归零，主树 `.git/info/exclude` 须含 harness 名的**不带斜杠**形式（带斜杠只匹配真目录、不匹配 symlink）；`adopt.sh` 负责两形式都写。exclude 在 common git dir，主树写一次覆盖所有 worktree。

## 建议的生命周期（按场景，从开始到结束跑哪些 step，非强制）

### 场景 A：单体小改（fast lane，L2 Impler 直做，或 L4 直做）
`no_task → 建 task(Lane=fast) → 1.0b research-first(轻) → [brainstorm 常跳，记 skip-log] → prd-only → start → 2.1 实现(fast-lane 琐碎可免 red-test-first，记 skip-log；否则 TDD) → 2.2 trellis-check → 3.3 判 spec/ADR(多为无) → /commit(ask-first) → /pr 进当期 release(security-scan 若动依赖) → finish-work`。无 L3/L4 编排、无 sendbox。

### 场景 B：中等特性（full lane，L4→L2 单派）
`L4: research-first + RepoMem.read + brainstorm(与 human) → 建 task(Lane=full, prd+design+implement) → [4.1 grill / 4.2 red-team 可选] → sendbox handoff 给 Impler(read_first 绝对路径 + process 声明) → L2 Impler: start → 2.1 TDD(派 L1 subagent) → 2.2 check + security-scan(动依赖)+人工 smoke(风险触发) → 3.3 **收尾起草**(check/自验 + WIMTB 自任务草稿 + ADR 候选写成 `proposed` 真文件 + **派独立 challenge subagent** 唱反调 + 备好 commit/status 不执行) → done 信打包**「待接受包」**回 L4 → L4: /code-review → **轻量 accept**(跨任务/集成一致性 + 翻 ADR `proposed→accepted`) → /commit + /pr(进 release) → archive(WIMTB 进 Multica) → RepoMem.merge`。

### 场景 C：大特性/超长程（full，L4→L3→多 L2 并发）
`L4: 分解成 parent(L3 cohort) + 多个 child(L2) → 派 L3 给 SubOrche → L3 SubOrche: 维护 L3 dashboard、排序、逐个 sendbox 派 L2 给多个 Impler(并发 session) → 各 L2 Impler 跑场景 B 的 L2 段(含**收尾起草** + 独立 challenge subagent)、done 信打包**「待接受包」**回 L3 → L3: cohort 集成验收 → 回报 L4 → L4: 整体**轻量 accept**(跨 cohort 一致性 + 翻 ADR `proposed→accepted`) + 上线 → 各 L2 archive→WIMTB, L3 收敛→WIMTB 进 L3 父 issue`。human 同时盯这些 session → 用 Dashboard 看待办。

> step 细节见 workflow.md Phase 1/2/3 + `pipeline-mapping.md`（HS 15-step 落点）；门控 policy 见 `execution-policy.md`；交办见 `sendbox.md`。

## 级间交办：durable 走 sendbox，transient 是可插拔扩展点
- **durable**（handoff/decision/plan-ready/晋升/改 scope）→ **sendbox 文件协议**：写信物落 `.work_context/sendbox/` + 认作已定前 HITL 确认（见 `sendbox.md`）。这是本 repo **内置**的编排通道。
- **transient**（催活/问答/要即时结论的瞬态 chatter）→ 属于**可插拔的通信后端扩展点**：本 repo 缺省不内置具体实现（一个可见多 window TUI / A2A 自动回投的运行时可作为外接后端接入）。开箱即用时瞬态协调退化为人工在并发 session 间带话，或由 Trellis 原生 subagent 承担单会话 fan-out。
- L4/L3/L2 各自开独立 session（人驱动并发）；L1 subagent 由 L2 在会话内 auto-spawn。

## ATUI 归属边界：通报 ⊥ 交办（绝不抢别人 lane 的活）

**硬规则**：有其他 ATUI 归属、且不归当前 ATUI 管的任务，**绝不接手**。不让活在 ATUI 之间弹来弹去。

可判定的关键是把**通报**和**交办**切开：

| 你收到 / 看见的 | 它是什么 | 你的默认动作 |
|---|---|---|
| 别的 ATUI 就**它自己 lane 内**的问题给你的**通报**（FYI）| **不是派活** | **「知道了」**，不是「我来做」 |
| **显式交办**（sendbox `handoff` 信）或 **human 指派** | 才转移归属 | 按信 / 指派接手 |
| 你**看见别人 lane 里**的问题 | 不归你 | **只为周知地告诉归属方或 human**——不接过来做，**也不包装成「问题」递上去逼对方处理**（那是换了向的弹飞）|

- **归属判据**（拿不准就问 human，别默认「我看见了就归我」）：
  - **gardener**：harness · 两张注册表（ATUI / 工具）· spec 与 ADR 的落盘 · `.git/info/exclude` 与 git 配置。
  - **rootorc / impler**：产品代码 · 任务编排。
- **失效模式不是「谁偷懒」，是「通报被当成交办」**：归属方出于礼貌只报不做，接收方出于责任心接过来做 → 活在 ATUI 间弹飞、**归属方自己的排序被抢先**、两个 ATUI 同时动同一批文件。责任心在这里的正确出口是**报告**，不是**接手**。
- **弹飞有两个方向，都要防**：① 把不归你的活**接过来做**（向下 / 横向抢）；② 把不归你的活**包装成问题递给 human / 上级**（向上换向弹飞）——② 看着像「报告」，但只要它给对方制造了一个 **action item**，就仍是交办。**真报告 = 只为周知、不产生待办、不转移归属**（写 `fyi` 信正为此）。

> **范例（泛化自一次真实因果链）**：一个 gardener 发现某编排决定使一批 harness 文件在产品仓主树未跟踪，风险是并发 impler 任一跑 `git add -A` 会把它们扫进功能分支 / MR。它把这条**通报**给 orchestrator，信里注明「这是你的编排决定，我没替你做」。orchestrator 出于责任心**接过来**当自己的活——核险、给方案、去申请产品仓提交授权。**与此同时归属方（gardener）已在自己 lane 内把问题消解**（把 exclude 改回全排除、未跟踪数归零），且纳入产品仓需先办若干配套前置。**若 orchestrator 真提交了，恰好违背归属方自己的排序，还两个 ATUI 同动同一批文件。** 病根就是那句「通报」被读成了「交办」。

- **通报要显式标注不转移归属**：写「我在自己 lane 处理 / 已处理，你知道就好」的信，用 sendbox 的 **`fyi`（通报）**信型（见 [sendbox.md](./sendbox.md) 信型目录）——它与 `blocker`（「我卡住了，你来定」）语义相反：**不请求接收方行动、不转移归属**。

- **向 human 汇报只列你自己 lane 的待办**（归属边界在「对 human」这条方向的落地）：你的 ask 清单**只准装归你、且需 human 拍板的项**。别的 session 的阻塞 / 待决策**不是**你的 ask——把它**转交那个 session**（或它的 human 接口），**至多**在你的报告里作**一行**明确标注「**非我归属、你（human）就此对我不可行动**」的背景，绝不并进你自己的 ask 清单。把多个 owner 的待办混成一张单子，会逼 human 去当两个 agent 之间的人肉中继、且分不清哪条阻塞谁——这正是 ① 抢活、② 上向弹飞之外的第三种越界（替别人把待办推给 human）。

## 与 Trellis 原生的关系
Parent/Child Task Trees + 子代理 dispatch + `task.py --mine`/assignee 是载体。channel-driven 面向程序化 peer；本模型是**人驱动并发 session + sendbox 异步 durable 信**，用 native/tdd + sendbox。
