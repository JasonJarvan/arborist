# Sendbox：跨 session 定向交办（<project> host 配置 + 信规范）

> 角色间（L4 RootOrche / L3 SubOrche / L2 Impler / L1 subagent）的异步文件交办。操作用 **`sendbox-protocol` skill**（handoff/inherit verbs）；本篇是 <project> 宿主配置 + **信的命名/frontmatter 规范**。吸纳自 HarnessStack longterm § Cross-Session Sendbox Convention。

## Handoff brand contract

**默认 brand-agnostic**：跨 session 交给 Impler、SubOrche、Reviewer 等执行角色的 handoff **默认不钉执行者 brand**。任何受支持 brand 的 session 都能接，谁接就以自己的 **actual runtime brand** 跑——作者不替未来的执行者预先钦定 provider。此时 `recipient_brand` / `route_policy` **省略**。

**仅能力驱动地钉 brand**：**只有当任务依赖某个 brand 独有的能力**（该 brand 特有的工具 / 特性，换 brand 无法等价完成）时，handoff 才携带顶层 `recipient_brand` + `route_policy`，把执行钉到该 brand。判据：

- 能写出「本任务非 `<brand>` 不可」的具体能力理由 → 钉 brand（带 `recipient_brand` + route block）。生成器只用 `(recipient_brand, lane, task_kind)` 从 `brand_routing.route_policies` 精确选择 leaf，不从作者 brand、模型名、目录名或旧信正文推断。
- 写不出这个理由 → **保持 brand-agnostic，省略 `recipient_brand` / `route_policy`**（这是默认，绝大多数 handoff 走这条）。
- 一旦钉了 brand：值缺失、未知或生成结果出现 brand mismatch —— handoff/inherit 都必须 fail closed，列出支持值并要求修正；不补默认值、不跨 brand fallback。

**与链内 same-brand 不变式区分（务必别混）**：上面讲的是**跨 session 替执行者预先钦定 brand**（默认不做）。它**不同于**链内不变式——一旦某 Impler 以某 brand 实际开跑，其向下所有 L1 subagent 必须同 brand、不伪装：

`effective_subagent_brand = impler.spec.brand`

（implement / TDD / refactor / Explore / check / challenge / research 都不跨 provider；见 ADR-0006。此不变式**恒成立**，与 handoff 是否钉 brand 无关：brand-agnostic handoff 只是把「以哪个 brand 开跑」留给接手方决定，接手后链内仍严格同 brand。）

Human 收件人不执行 task，从不带 brand。执行角色**默认也不带**；只有上述能力驱动情形才带。

宿主配置的 `brand_routing` 是**能力驱动 handoff 用到的路由表**（brand-agnostic handoff 不查它）。启用时必须采用 cc-sendbox 0.6 的 `brand_routing` schema：`task_executing_roles`、`supported_brands`、`same_brand_policy: strict`，以及精确三层 `route_policies.<brand>.<lane>.<task-kind>`。每个 leaf 都必须有全局唯一 `policy_id`、非空 `route_fragment` 和显式 `agent` / `model`（由 runtime 决定时写 YAML `null`）。缺 tuple、重复 ID 或旧 schema 都是不兼容配置，必须在写信前失败。

## 目录结构（`toAgent/` + `toHuman/`）
```
.work_context/sendbox/
  toAgent/                 # 收件人是 agent 角色
    toRootOrche/           # per-project 近似单例 → 通用目录
    toSubOrche/            # 同上
    to<TaskName>Impler/    # impler 多实例 → 按任务限定（如 toAgentAuthImpler/），勿铺通用 toImpler/
  toHuman/                 # 收件人是人
    toUser/
    toTestTeam/
```
- `<Role>`/`<Receiver>` 是**角色/职能**，非 session 名（session 短命、角色不）。
- **impler 收件目录必须按任务限定 `to<TaskName>Impler/`**：impler 是**多实例**（每个并发任务一个 impler），通用 `toImpler/` 会让多个并发 impler 的信在同一目录里相互冲突。理由分层：rootorc / suborc / gardener 近似 per-project 单例 → 保持通用 `toRootOrche/` 等；impler 多实例 → 必须任务限定。TaskName 取该任务 slug（如 `eve-42` → `toEve42Impler/`）。
- 都在 `.work_context/`（git-ignored → 本地；副仓 `hgit` 记历史）。

## 持久化与可见性（形态 A / B —— **本布局 = 形态 B**）
信件的持久化与可见性取决于宿主仓 git 配置，两形态，adopt 时确定并写明：

- **形态 A —— sendbox 纳入宿主 git**：信随分支合并流动，跨 worktree / 跨 checkout / 跨机器协作方可见、可经 MR 评审；代价是内部协作记录进产品仓历史。
- **形态 B —— sendbox 排除出宿主 git（Arborist 脚手架默认推荐，本仓即此）**：`.work_context/` 被 `.git/info/exclude` 排除、由副仓 `hgit` 记史。含义：
  - **`sendbox-protocol` skill 的「把信提交在 worktree 分支上、随合并流动」这条 Cross-cwd 路径在本布局不成立**——信不在产品 git 里。跨 worktree / 跨 cwd 只能**用绝对路径直写宿主主仓**的 sendbox——**这才是 `read_first` 必须绝对路径的根因**（不只是「相对路径悬空」，是信与规范本身都不在 worktree 里；worktree 里静默拿到空结果比报错更危险）。
  - **可回溯性靠 `hgit`（人工触发、无 remote）**：无步骤强制 `hgit` 时「有历史」是习惯非保证，换机 / 删除即全丢——而信的 lifecycle 常含跨天 `persist`，此承诺要额外留意。
  - **跨机 / 跨人不可见**：协作方在另一台机器上，这封信对它不存在；跨机需另走渠道。
  - **精确暂存到文件**：`hgit add <file>` 按文件、勿整目录 `add -A`——整目录会把并发会话改到一半的文件一并提交。
- **脱敏 × git 归属**：若你用的写信技能在信尾追加 `<!-- These letters are committed to git … -->`，**那句在形态 B 不成立**（信不进产品 git，别据它判断可见性 / 该不该写敏感信息）；但**脱敏要求两形态都保留**——任何形态下都不写明文密钥 / token / PII（本机 `hgit` 同样是可读态）。

## 信命名规范
`from-<task>-<type>.md` —— `<task>` = 来源 L2/L3 task 的 slug；`<type>` ∈
`handoff`（派活）· `done`（交付回报）· `ack`（确认）· `blocker`（阻塞）· `greenlight`（放行请求）· `plan-ready`（计划待评审）· `decisions`（决策记录）· `smoke`（人工 smoke 手册）· `fyi`（通报：我在自己 lane 处理 / 已处理，你知道就好——**不转移归属、不请求行动**；与 `blocker`「我卡住你来定」语义相反。防「通报被当交办」，见 [roles-and-tiering.md](./roles-and-tiering.md)「ATUI 归属边界」）。
例：`toAgent/toEve42Impler/from-eve-42-handoff.md`（impler 目录按任务限定 `to<TaskName>Impler/`，见 §目录结构）、`toHuman/toUser/from-eve-42-greenlight.md`。

## Frontmatter 规范
**单收件人 + 瞬态**信可省 frontmatter（默认 burn，收件人 lifecycle 结束即 `rm`）。**多收件人 / durable** 信**必须**带：
```yaml
---
recipients:
  - role: <Impler|SubOrche|RootOrche|User|TestTeam>
    purpose: <为何读这封>
    lifecycle: <终止条件，如 "L2 started" / "signed off">
recipient_brand: <claude-code|codex>  # 可选；仅能力驱动 handoff 用（任务依赖某 brand 独有能力时才带），否则省略 → 谁接谁定
route_policy:                         # 可选；与 recipient_brand 成对出现，仅能力驱动 handoff 用
  policy_id: <selected-policy-id>
  lane: <fast|full>
  task_kind: <implement|explore|check|challenge|research>
  agent: <selected-agent-or-null>
  model: <selected-model-or-null>
on_lifecycle_end: burn | archive | wimtb   # wimtb=蒸馏进对应 Multica issue 后 rm
task: <L2/L3 task 目录>
multica_issue: <task.json.meta.multica_issue，如有>
created: <YYYY-MM-DD>
created_in: <来源角色/session>
---
```
- 无 frontmatter 又无单一明确收件人的信 = 畸形。

## Handoff 信必备正文（交办给执行角色，见 `_TEMPLATE-handoff.md`）
1. **`read_first`（绝对路径，硬性 N19）**：`<REPO_ROOT>/.trellis/workflow.md` + 相关 guides + 该任务 `prd.md`（worktree/独立 session 看不到被 exclude 的 harness overlay，相对路径悬空）。
2. **process-completeness（N20）**：遵标准 Pipeline，或逐条声明短路的 step（接收方抄进自己 task 记录）；不得静默省略 TDD/security-scan/HITL。
3. **任务引用** + Multica issue。
4. **（仅能力驱动 handoff）recipient brand + route block**：默认省略——brand-agnostic handoff 不写 `recipient_brand` / `route_policy`，谁接谁以自己的 actual runtime brand 跑。仅当任务依赖某 brand 独有能力时才带：顶层 `recipient_brand` 与 `route_policy` 必须来自 `_handoff-config.yaml` 的精确 `(brand, lane, task_kind)` leaf；`policy_id` / `agent` / `model` 必须一致，正文只渲染该 leaf 的 `route_fragment`。

## 自动路由 vs 人确认（durable 边界，A2A 自动化判据）
交办可自动化（若接入了某个瞬态通信后端）到什么程度，按下列切分：
- **瞬态 = 全自动、免确认**：ack / 状态 / done 通知 / blocker 上报 / 提问 —— 纯协调 chatter，直接自动路由。
- **durable = 自动送达 + 落定前人确认**：满足任一——① 映射到某 task/EVE；② 产生/改变决策、计划、晋升候选；③ 需 outlive 会话成为记录（plan-ready / decisions / 改 scope 的 delivery / 晋升候选）。**自动送达**，但接收侧/门在"认作已承诺/落定"前**停下等 user 确认**（对齐 HITL/ask-first）。
- 一句话：**协调 chatter 全自动；承诺级记录 自动送达 + 落定前人确认。**

## 生命周期
- 瞬态（ack/greenlight/blocker/done/fyi）→ **burn**。
- durable 且映射 L2/L3 → **wimtb**（蒸馏进 Multica issue + 附原信 → 验证 → `rm`；同 verification-and-gates WIMTB 不变式）。
- 无 EVE 的 durable 信 → 留 `.work_context/` 或升级 guide，不硬塞无关 issue。

## Inherit（接收方"继承"handoff——handoff 的读取侧）
handoff 是**写**（派活方投信）；inherit 是**读/接管**（接收会话"继承"这封信开工）。接收角色开一个新 session 后：
1. **校验 recipient brand + route policy（仅当 handoff 钉了 brand）**：若信**未带** `recipient_brand`（默认 brand-agnostic）→ 任何受支持 brand 的 session 都可继承，直接以**当前 actual runtime brand** 开跑，无需校验此步。若信**带了** `recipient_brand`（能力驱动）→ 它必须是受支持值且与当前 actual runtime brand 一致；再按 frontmatter 的 lane/task_kind 重解 config leaf，并核对 `policy_id` / `agent` / `model` 与正文 Selected route，任一不一致即停止继承。（注：无论哪种，接手后链内 L1 派活仍严格遵 `effective_subagent_brand = impler.spec.brand`。）
2. **读 `read_first`**（信里列的绝对路径：workflow.md + 相关 guides + 该任务 prd）——绝对路径保证 worktree/独立 session 也能加载被 exclude 的 harness overlay（N19）。
3. **按 process-completeness 声明续流程**：遵 workflow.md 标准 Pipeline，或采纳信里逐条声明的短路 step（抄进自己 task 记录，不静默绕门）。
4. **认领任务**：从信的 `task` 字段定位 L2/L3 task 目录 + Multica issue，进入对应 Phase（如"从 Phase 2 TDD 入"）。
5. 完成后按信尾写 `from-<task>-done.md` 回投来源角色。
> handoff/inherit 是一对动作，操作可由 `sendbox-protocol` skill 的 handoff/inherit verbs 执行；本节定义 Arborist 语义。

## 与 Trellis 的关系
Trellis 无原生定向交办；`trellis mem`+journal+task 目录覆盖"回忆/连续性"，sendbox 补"定向指令"层。live 多代理才考虑 `trellis channel`。
