# AgentTUI 注册表：并发 session 同伴发现层

> **AgentTUI** = 一个跑在终端里的 coding-agent TUI 会话（Claude Code / Codex …），以 **session-id 为主键**。本注册表是纯文件式静态表 + 约定驱动，回答「本项目/本机有哪些 AgentTUI、各自 role / description / 当前 task / session-id / 状态」，让并发 session 能**互相发现**。**core 无守护进程、无常驻自动投递 runtime**——CCB 式 A2A 自动回投 / `message→attempt→reply` 三段链 / callback 续跑仍属长期目标，另行追踪，不在本规范内。**往活 pane 的字节注入投递则不再是绝对 out-of-scope**：经 [ADR-0007](./decisions/0007-agenttui-delivery-contract-pluggable-adapter.md) 修订为受契约约束的**可插拔 adapter**——core 只规定投递【契约】、保持 transport 中立（仍无守护进程），具体 zellij pane / 字节注入是**参考 adapter · opt-in**、不在 core（契约见 §3「投递契约」）。投递 adapter 是**送达侧新增的一类更可靠选项**，不改下述三通道与「记录⊥送达正交」——durable 内容仍必留信不变。但**跨 session 触达本身是现成的**：Claude Code 原生支持 `claude -p --resume <session_id> "<msg>"` 向指定会话追加消息——注册表存 `session_id` 作触达句柄正是为了利用这一能力。触达分**三通道**（直投 / 写信 sendbox / 用户投），且**记录与送达两轴正交**——durable 内容必留信物（写信），是否另行直投作送达提醒由发送方定，见 §3 末「跨 session 触达」。
>
> 姊妹规范：**[工具注册表](./tool-registry.md)**（「本机/本项目有哪些可选能力可用」；本表 = 「有谁」）+ **[安全启动 AgentTUI + brand-capacity observer](./agenttui-launch-and-brand-capacity.md)**（**启动侧姊妹**：如何安全启动一个**新**独立 AgentTUI + 建 Impler 前按容量选 brand；本表 §3 投递契约 = 往**已存在**活会话注入，两侧共用 pane 定向 `--pane-id`）。三者同构、共用 `.arborist/` 级联、同由 gardener 维护。

## 1. 位置：全局-项目级 级联

```
~/.arborist/                      # 全局（机器本地，跨项目）
  index.json                      # 项目清单 + 各项目 AgentTUI 摘要（gardener 持有）
<repo>/.arborist/                 # 项目级（机器本地运行时态，git 隐身）
  agents/<name>/
    spec.json                     # 稳态身份
    runtime.json                  # 活体状态
```

- **渐进式披露**：需要读表时 → 先读**当前项目 `<repo>/.arborist/agents/*`**（+ 全局 index 摘要）；仅当确需触达**别的项目**的 AgentTUI，才经全局 `index.json` 查到目标项目路径，再读其 `.arborist/`。
- **git 隐身**：`.arborist/` 是机器本地运行时态（session-id 只对本机会话文件有意义），须列入 `.git/info/exclude` + `.gitignore`（adopt 脚手架已代劳）；全局 `~/.arborist/` 天然在仓外。
- **脚手架模板**：adopt 时铺 `<repo>/.arborist/templates/`（源：Arborist 仓 `overlay/arborist-templates/`），示例值即字段文档。

## 2. Schema

### 2.1 `spec.json`（身份，稳定，自登记时一次写成）

| 字段 | 说明 |
|---|---|
| `name` | 唯一名 = 目录键。归一化小写，建议满足 `^[a-z][a-z0-9_-]{0,31}$`；避开保留名（`all` / `user` / `system`）；同项目内唯一（gardener 校验） |
| `role` | `rootorc` / `suborc` / `impler` / `subimpler` / `gardener`（见 §2.4） |
| `brand` | 会话的 **actual runtime brand**：`claude-code` / `codex` /（可扩展）。自登记必须写正在运行本会话的真实 ATUI brand；不得按模板示例、期望路由或模型名猜测，也不得把一个 brand 伪装成另一个 brand。声明值与实际 runtime 不符时，注册校验必须 fail closed。 |
| `description` | 这个 AgentTUI 是干什么的（人读） |
| `task` | 当前在做的任务：自由文本或 task/issue 引用 |
| `project` | `{ "path": 项目根绝对路径, "project_id": 路径哈希 }`；约定 `project_id` = **`realpath` 归一化（解析 symlink、去尾斜杠）后**的绝对路径 sha256 前 12 位十六进制（保证跨表一致、可机械重算；不归一化会让同一仓经不同路径拼写裂成两条 index 记录） |
| `created` | 建立时间（ISO8601） |
| `lineage` | **角色继承代数**（整数，首任=1；每经一次 inheritance-mode 交接（sendbox Mode B：承担者换人、角色不变）+1）。**缺字段读作 `1`（首任）**，向后兼容。放 `spec.json` 因其是**稳态身份**——不随会话重启变，与 `runtime.json.generation`（会话重启代数）分居两文件。**消歧（俩概念被混淆的根因）：`generation` = 同一承担者换会话的次数；`lineage` = 换承担者的次数**——两者结构上独立、不可互推（承担者跨多会话时 generation 会大于 lineage） |
| `lineage_origin` | 可选。本代继承所依据的 handoff 信**溯源面包屑**（建议格式：`前任 session_id + 信文件名`）。**⚠️ 非权威、可悬空**——inheritance handoff 信按 sendbox 协议在承接方首个里程碑后 `burn`，此值届时指向已烧文件；**真要审计继承链请去 git 历史 / ledger，切勿把本字段当审计指针**。注册表是快照（见 [ADR-0002](./decisions/0002-agenttui-declared-derived-state-model.md)/[ADR-0005](./decisions/0005-agenttui-role-lineage-vs-generation.md)），只答「当前第几代」（发现用），不答「继承链长什么样」（审计用） |

### 2.2 `runtime.json`（活体，易变，可信触点刷新）

| 字段 | 说明 |
|---|---|
| `session_id` | **主键 / 触达句柄**。`claude -p --resume <session_id> "<msg>"` 向该会话**追加**一条消息并让其在自身完整上下文里处理（实测：append 非 fork，回复走调用方 stdout）。触达前须按 §3 末判活选通道 |
| `session_file` | 会话落盘**绝对路径**（判活探针，令读者零 brand 知识）。Claude Code：`~/.claude/projects/<munged-repo-path>/<session_id>.jsonl`（逐轮 append，mtime = 最近活动，已实证）；Codex：`~/.codex/sessions/YYYY/MM/DD/rollout-<ISO时间戳>-<session_id>.jsonl`（逐轮 append，mtime = 最近活动，**已实证**：`codex exec resume` 续同一 rollout、mtime 随 turn 递增、不新建文件，与 Claude Code 同——见 [ADR-0003](./decisions/0003-cross-session-reach-semantics.md) 实测边界） |
| `state` | **声明态**：`active` / `stopped`（`idle` 为保留枚举值，MVP 不自写，见 §3）。`stopped` 有**写入门槛**（仅会话真正结束才写，见 §3/§4）且遇活转录矛盾会被派生规则**降级为 contradiction**——声明态非确知，读者据 §3 现算，不无条件采信 `stopped` |
| `last_seen` | 心跳时间戳（ISO8601，可信触点顺带刷新）。**写 `stopped` 时也须记 `last_seen`**——它是活转录矛盾检测的基准：若 `session_file` mtime 晚于该 `stopped` 写入记录的 `last_seen`（容小段文件系统时钟偏移），即声明与派生活性证据矛盾（见 §3） |
| `generation` | 重启代数（同一 `name` 重启/换 session 时 +1） |
| `pane_ref` | 可选：**投递 adapter 用的** 终端复用器 pane/tab 引用。core 不强制（未启用活 pane 投递时置 `null`）；启用活 pane 投递 adapter 时按 [ADR-0007](./decisions/0007-agenttui-delivery-contract-pluggable-adapter.md) 契约填，供 adapter 寻址目标 pane。注意：送达证据（transcript 字节边界 / per-send nonce / marker）是 **per-send 运行时态，不入本静态表**，故此表**不**新增存 nonce/证据的字段 |

### 2.3 全局 `index.json`（摘要级，gardener 维护）

`{ "projects": [ { "project_id", "path", "name", "agents": [ { "name", "role", "brand", "state", "session_id", "lineage" } ] } ] }` —— 仅作跨项目发现的入口，细节以各项目 `.arborist/agents/*` 为准。摘要带 `lineage`（缺省=1）是为跨项目「找当前那一代承担者」的常见意图；不带 `lineage_origin`（溯源属细节，且非权威，见 §2.1）。

### 2.4 role 枚举（语义对齐 [roles-and-tiering.md](./roles-and-tiering.md)）

| role | 级 | 说明 |
|---|---|---|
| `rootorc` | L4 | 开发产品本身、对人、编排整仓 |
| `suborc` | L3 | 子编排，管一批 impler |
| `impler` | L2 | 实现一个可独立验证交付 |
| `subimpler` | L1 | session 内短生命 subagent（implement/check/research）；**默认不入表**——短命、无需被发现，仅作保留枚举值 |
| `gardener` | meta | 横切：维护 harness + AgentTUI/工具两注册表（登记/清理条目、持全局 index）；非 L 链一环 |

## 3. 状态模型（读表方必读）

- **声明态**（agent 自写，仅两个可信触点）：`active` —— session start 自登记及心跳触点写；`stopped` —— **仅会话真正结束时写**（写入门槛见下「stopped 写入门槛（Guard）」；含糊措辞「干净收尾」已作废，因它把任务生命周期事件误当会话结束）。崩溃/关终端没有回调，崩溃路径的 `stopped` 永远不会被写——这是结构性事实，读者不得假设声明态完备；且自写的 `stopped` 可因范畴错误而失真（见下 reconcile），读者亦不得无条件采信。
- **`idle` 是派生态**：agent 空闲时不在运行，物理上无法自写。schema 保留该枚举值，兼容未来平台 hook 机械写入的增强（留验证的增强路径，MVP 不依赖）。
- **有效态 = f(声明态, last_seen 新鲜度, session_file mtime 探针)**，由**读者读表时现算**（无守护进程，观测退化为读时派生）：

| 条件（按序判定） | 有效态 |
|---|---|
| 声明 `stopped`，但 `session_file` 存在且转录 mtime 落在**新鲜窗口**内（距今 < idle 阈值，**或**晚于该 `stopped` 写入记录的 `last_seen`，容小段文件系统时钟偏移） | **contradiction —— 可疑 stopped / 疑似仍活**：reader 视其为 reachable/active；validator 报该不一致叶子；owner 以 heartbeat 修复；**gardener 复核前不得据此 GC** |
| 声明 `stopped`（无上述矛盾证据） | stopped |
| `session_file` mtime 距今 < idle 阈值 | active |
| mtime 距今 ≥ idle 阈值 且 < stale 阈值 | idle（推定） |
| mtime 距今 ≥ stale 阈值，或 `session_file` 不存在 | stopped/stale（推定；gardener GC 候选） |

- 阈值：idle **15min** / stale **24h**，均为**建议默认值**，按项目节奏可调。`session_file` 不可读时退用 `last_seen` 作新鲜度依据（较粗：只反映可信触点，不反映逐轮活动）。
- **探针局限（必须知道）**：会话落盘是 open-append-close 写入，空闲期无进程持有其 fd ⇒ 无法经 fd 把 pid 映射回 session；mtime 停跳时，「idle 但终端还开着」与「已关终端」**不可区分**。因此 idle 与 stopped/stale 一律是**推定，不是确知**。
- **stopped 写入门槛（Guard）**：`stopped` 是**会话生命周期**信号，不是任务生命周期信号。
  - **会话真正结束**才可写 `stopped` = AgentTUI teardown，**或** Mode-B 角色交接（sendbox inheritance：承担者换人、当前会话不再续该角色）。
  - 明确**不构成**会话结束、因而**不得**触发 `stopped` 写入的事件：任务完成 / 任务 archive / 末条 assistant 回复 / 等待用户输入 / prompt 空闲 / compact / 上下文重置。这些是任务或轮次事件，会话线程仍会继续处理后续 turn。
  - **session 不得在自身仍是活 session 时写 `stopped`**——防「archive 完顺手标 `stopped` 却继续处理用户 turn」这一任务-会话生命周期**范畴错误**（本 guard 的直接由来）。收尾（任务/里程碑洁癖收口）只刷 `last_seen` 心跳、更新 `task`，**不写 `stopped`**。
  - 若配备生命周期命令（adopter 自置），`stop` 应要求**显式会话结束确认**（confirm-session-exit），`heartbeat` 应同时刷项目级 leaf 与全局 index。具体命令名/路径属 adopter 本地，不入本规范。
- **活转录矛盾检测（reconcile：declared `stopped` 不再无条件优先）**：读者现算有效态时，先按上表首行做 reconcile——当声明 `stopped` 与**新鲜 live 派生证据**矛盾（`session_file` 存在且转录 mtime 落在**新鲜窗口**内）时，**不采信 `stopped`**，标记为 **contradiction**（可疑 stopped / 疑似仍活），有效态视为 reachable/active。
  - **新鲜窗口的判定**（复用 §2.2 已实证的 mtime 探针，Claude Code 与 Codex 同）：`stat` 该 `session_file` 的 mtime，满足任一即算「新鲜、与 stopped 矛盾」——(a) mtime 距今 < idle 阈值（转录近期仍在逐轮 append）；(b) mtime **晚于**该 `stopped` 写入时记录的 `last_seen`（容小段文件系统时钟偏移）——即「声明停后转录还在写」。`session_file` 不可读时退用 `last_seen`（较粗），无矛盾证据可判则回落到 stopped。
  - **判据 (a) 的预期短暂误报窗（须知，免得读者惊讶）**：刚**干净 teardown** 的会话，末轮留下的 mtime 在其后一个 idle 窗口内仍是「近期」——此时「末轮遗留的新鲜 mtime」与「仍在 append」不可区分，判据 (a) 会把这个**真已结束**的会话误判为 contradiction。这是预期的**短暂误报窗**，危害低：越过 idle 阈值后 mtime 停跳、判据 (a) 不再命中，有效态自愈回落到 stopped；期间保守视为 reachable/active、不 GC，也只是延后清理而非误删。判据 (b)（mtime 晚于 stopped 的 `last_seen`）才是**精确**的范畴错误探测器——只在「声明停后转录确实又写了」时命中，无此误报窗。
  - **对 reader / gardener 的约束**：contradiction 条目**不得据以 GC**，gardener 须先复核（如经 §3 末通道触达 owner、或等新鲜窗口过后 mtime 停跳再判）；validator 应把该不一致叶子报出；owner（本人）下一个可信触点以 heartbeat 修复（改回 `active` 并刷 `last_seen`）。参见 [ADR-0002](./decisions/0002-agenttui-declared-derived-state-model.md) Amendment。
- **GC 保守原则**：gardener 清理的是**注册表条目，不是会话**；条目可由本人随时重建，误删无害——但仍应保守（只 GC 超 stale 阈值者），避免把仍活跃的同伴从发现视野里抹掉。
- **Human-direct 豁免**：由 human 直接启动、且不需要被其他 AgentTUI 发现或路由的 **human-direct harness** 会话不属于注册对象。它们 **must not be reported as unregistered**，也不得因为没有 `spec.json` 被 validator 或 gardener GC 当作残缺注册项。会话一旦要参与 A2A 发现或路由，豁免即结束，并须按 actual runtime brand 自登记。

**跨 session 触达（三通道 + 记录⊥送达正交）**：`session_id` 是触达句柄。跨 session 通信有**三个通道**（user 定义 2026-07-23）：

| 通道 | 定义 |
|---|---|
| **① 直投** | `claude -p --resume <session_id> "<msg>"`——**不论对方活性**（对活 session 注入受支持，见 [ADR-0003](./decisions/0003-cross-session-reach-semantics.md) Amendment）。向其 `.jsonl` **追加**消息（实测 append 非 fork、携带完整历史上下文）；异步单向、无原生回执 |
| **② 写信 / sendbox** | 定向信落 sendbox（见 [sendbox](./sendbox.md)）/ Agent Teams mailbox——产生 outlive 会话、可审计、可 HITL 的**信物（记录）** |
| **③ 用户投** | 用户亲自把 prompt 发给目标 session——**仅当用户明确说「给我 prompt 我去说」之类**才用；缺省不选它 |

**选择规则（记录与送达两轴正交，不是二选一）**：
- **记录轴（是否需要信物）**：**durable 承诺级**（handoff / decisions / plan-ready / 交付 done）→ **必写信**（信 = 记录 / 信物；为 outlive 会话、可审计、落定前 HITL）；**瞬态 chatter**（催活 / 问答 / 通知 / ack）→ 无需写信。
- **送达轴（怎么送达 / 提醒）**：**直投**是送达提醒，由发送方自定——**写信不排斥同时直投，直投也不豁免写信**（内容 durable 时）。
- 故：durable = 写信（必）+ 直投（可选，作送达提醒）〔或 ③ 用户投〕；瞬态 = 直投即可（无需写信）〔或 ③〕。
- 用户说「你告诉 xxx 去做什么」= 一条**直投**指令；其内容若 durable，则成为**信 + 直投**。只有用户明确要 prompt 时才是 **③ 用户投**。
- 活性探针的剩余价值：预估对方多快看到 + gardener GC，**不再决定通道**。

- **单向、无原生回执**：`--resume` 是「投递并让对方处理」，`-p` 回复走**调用方 stdout**、不进对方 TUI；要双向 / 等回复需外层协调（sendbox 回信 / mailbox / 轮询）。
- **NOTE（机制事实，非禁令）**：即便对方是活 TUI，`-p --resume` 的回复仍返回**调用方 stdout**，对方的活 TUI 界面上**不会可见地弹出**这条注入 / 回复；这只是回执机制的客观描述，不构成对活 peer 注入的禁止。
- **Agent Teams mailbox**（`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`，`~/.claude/teams/<team>/inboxes/<agent>.json`）是原生结构化 A2A，但实验性 + 限 team 范畴、非任意 session 对投；作可选增强，非本表依赖。
- **lookup 定位（待实证）**：`--resume` 疑似须在原 session 创建目录（或其 worktree）内执行才能定位 `.jsonl`；跨目录 / 跨项目 resume 行为未实证，归 gardener 待测回填。
- **实测边界**：append-非-fork + 上下文携带已由 gardener 在一次性 session 实证（见 [ADR 0003](./decisions/0003-cross-session-reach-semantics.md)）。早期版本曾因「活-TUI 并发 resume 未实证」对活 peer 采保守「不注入」规则；**已更正**——对活 session 的 `--resume` 注入受支持（user 决定 2026-07-23，ADR-0003 Amendment），通道选择改按三通道 + 记录⊥送达正交模型（上表）。

**投递契约（规范性 · 任何活 pane 投递 adapter 必须满足 · 权威见 [ADR-0007](./decisions/0007-agenttui-delivery-contract-pluggable-adapter.md)）**：往活 pane 注入字节把消息送进对方 transcript，是通道①之外**送达侧新增的一类更可靠选项**（记录⊥送达正交不变：durable 内容仍必留信）。core 只规定以下契约、保持 transport 中立；具体终端复用器（zellij 等）与字节注入实现是 **opt-in 参考 adapter，不在 core**。任何投递 adapter 必须满足：

1. **brand + 活性感知的 submit 路由**：活性取自 §3 读时派生态（contradiction 按活跃处理）。
   - 有效**活跃** + `brand=codex` → 写入信封后**发一次 Tab（byte `9`）入队**到下一 turn，**不 steer** 当前 turn（让当前 turn 先跑完，防外部 agent 把决策注入到实现进行到一半之中）；
   - **空闲 Codex** → 发 **Enter（byte `13`）** 提交；
   - **Claude Code** → **不分活性一律 Enter 提交**。**为何不照搬 Codex 的 Tab**（#12 官方补充裁定）：Claude Code 官方 keybinding 只有 `chat:submit`=Enter，其 Tab 用于 autocomplete / tab 导航，**没有 Codex-Tab 那样的独立「入队到下一 turn」动作**；目标忙碌时由 **Claude Code 自身的 receiver-side queue** 在当前 turn 跑完后处理，故活跃/空闲都用 Enter。**⚠️ 勿给 Claude Code 套用 Codex 的 Tab**——那会落进 autocomplete/导航语义、不入队提交，是误改。
   - 与 [ADR-0006](./decisions/0006-runtime-brand-is-routing-authority.md) 一致：submit-key 路由本身即 brand-keyed，是「按实际 brand 路由」在投递维度的延伸。
2. **不盲目重发入队键**：送达未观测到时**不得**重发 Tab——盲目重发会入队重复信封。
3. **送达证据必须 message-specific（fail-closed，绝不假阳性）**：注入前**记录目标 transcript 字节边界**；每次发送生成**唯一 nonce**；**仅当**该信封的 nonce marker 出现在边界**之后**才返回 `delivered`，否则返回 `queued-unverified`。pane 命令成功 / pane 存在 / 转录 size 增长 / mtime 变化**都不是**送达证据（忙碌目标会自行增长转录）；**peer 回复是唯一的语义 ACK**。
4. **fail-closed**：未验证即 `queued-unverified`，绝不当 `delivered`。

- **参考 adapter（随发 · opt-in · 二选一别混）**：
  - `scripts/agenttui.py`（adopt 铺到 `<repo>/.trellis/scripts/`）是**满足本契约的 operational 参考实现**——按注册表 `pane_ref` 用 `zellij … write-chars --pane-id <目标 pane>` **定向注入**（不靠焦点），带齐上述 4 条；调用见工具表条目 `agenttui-direct`（`python3 .trellis/scripts/agenttui.py {status|send|heartbeat|stop}`，发前可 `--dry-run` 验路由）。**operational 投递一律走它。**
  - `scripts/agenttui_deliver_zellij.py` 是**契约的 seam 化演示，非 operational**：默认注入器**收 `pane_ref` 却不定向、只写当前焦点 pane**，跨 session / 跨 brand（目标 pane ≠ 焦点 pane）必投错——**未补 `--pane-id` 前不得当跨 pane operational 路**（下游把它误当正道，正是跨 brand 发信「表现不佳 / 不稳定」的根因）。
- **契约里的 nonce ≠ §5.2 自识别 nonce**（用途不同，勿混淆）：本节的 per-send nonce 是**送达证据**——证明「这一条信封确实进了对方 transcript」；§5.2（自登记步骤 2）的无桥接 nonce grep 是**自识别探针**——本会话往自己终端吐一个随机串、再回自己 brand 目录 grep 定位**自身** `session_id`/`session_file`。前者验对端送达、后者定位本端句柄，各自独立。
- **证据是 per-send 运行时态，不入注册表**：字节边界 / nonce / marker 均随单次发送产生与消亡，注册表是静态发现表，**不**为其新增字段（`pane_ref` 只存寻址句柄，见 §2.2）。
- **候选未来 transport（备注，非依赖）**：官方 **Channels** 能把外部事件推进一个已运行的 Claude Code 会话，是一个**候选未来投递 transport**（成熟后可作满足本契约的又一 adapter 后端）；但它当前仍是 **research preview**、且**需会话启动时显式 opt-in**，故**暂不作 Arborist 默认依赖**（与「可插拔 adapter、opt-in、transport 中立」一致）。

## 4. 生命周期与角色分工

- **自登记（主路径）**：AgentTUI 启动读 harness 后，**自建**整条 leaf（spec.json + runtime.json，单写者原子写）。自建覆盖所有角色——rootorc / gardener 没有 handoff 信，登记不能挂在派活方身上。
- **handoff 供素材**：经 sendbox handoff 而来的会话，信中 role / task / description 直接用作 spec.json 素材；派活方可在信中提醒「按注册表规范自登记」，但**不代写**——session_id 在会话创建前不存在，派活方物理上写不了。
- **心跳**：处理 turn 的可信触点（每轮收尾、阶段切换等）顺带刷 `runtime.json.last_seen`；约定驱动，无守护进程。
- **收尾（任务/里程碑）≠ 会话结束**：任务完成 / archive / 末条回复 / 等用户输入 / compact / 上下文重置**都不是会话结束**，此时只刷 `last_seen` 心跳、**不写 `stopped`**。`state: "stopped"` 仅在**会话真正结束**（AgentTUI teardown 或 Mode-B 角色交接、当前会话不再续任）时写；**session 不得在自身仍活时标 `stopped`**（见 §3「stopped 写入门槛」）。误标的 `stopped` 会被读者 reconcile 成 contradiction（§3），且下一次可信触点应由本人 heartbeat 改回。
- **gardener**：持有并更新全局 `index.json`（跨项目摘要汇总）；按 §3 保守 GC stale 条目；校验 name 唯一；探针遗留项由 gardener 实测后回填本 guide：codex mtime **已实证**（见 §2.2）；**待实证**——无桥接自识别兜底（nonce grep，§5.2）、跨目录/跨项目 `--resume` lookup（§3 末）。
- **rootorc / suborc / impler**：登记自身、读表知同伴、专注本职；**subimpler 不建条目**。
- **归属边界（跨 ATUI 别抢活）**：ATUI 只管自己 lane 的活；别的 ATUI 就其自身 lane 的**通报**（`fyi`）是 FYI 非交办，默认「知道了」不接手；看见别人 lane 的问题 → 告诉归属方或 human。权威定义见 [roles-and-tiering.md](./roles-and-tiering.md)「ATUI 归属边界」。

## 5. 操作说明：首次进项目怎么读表 / 自登记

**读表（发现同伴）**

1. `ls <repo>/.arborist/agents/` —— 目录名即同伴名；逐个读 `spec.json` + `runtime.json`。
2. 按 §3 派生规则现算各自有效态（`stat` 其 `session_file` 的 mtime）。
3. 需跨项目 → 读 `~/.arborist/index.json` 查目标项目 `path` → 再读其 `.arborist/`。

**自登记（建自己那条 leaf）**

1. 定 `name`：小写归一；查 `agents/` 下无重名。**默认用 `<role>-<task/issue>` 命名**（如 `impler-eve68`）——降低同角色并发会话撞名概率；gardener 唯一性校验兜底。
2. 取 `session_id`：已 adopt Trellis + Arborist 的仓，Bash 环境直接读 `TRELLIS_CONTEXT_ID`（SessionStart hook 桥接注入，形如 `claude_<session-id>`，去前缀即得）；或从平台 hook stdin 载荷取 `session_id` / `transcript_path`。无桥接环境的兜底法（向会话输出一个随机 nonce，再到 brand 会话目录 grep 含该 nonce 的最新文件）**待实证**。**此处 nonce 是「自识别」用途**——定位**本会话自身**的 `session_id`/`session_file`；与 §3「投递契约」（[ADR-0007](./decisions/0007-agenttui-delivery-contract-pluggable-adapter.md)）里验证**对端送达**的 per-send nonce 是不同用途，勿混淆。
3. 取 `session_file`：`transcript_path` 直接给出；否则按 brand 路径推导（见 §2.2）。
4. `mkdir -p <repo>/.arborist/agents/<name>/`，写 spec.json + runtime.json（`brand` = actual runtime brand；`state: "active"`、`generation: 1`、`lineage: 1`（首任；经 Mode B 继承则见第 7 点）；字段示例见 `<repo>/.arborist/templates/`）。
5. 同一 `name` 重启换新 session：更新 runtime.json（新 session_id / session_file，`generation` +1），spec.json 不动（`lineage` 是稳态身份，重启不变）。
6. （可选）把自己追加进全局 `~/.arborist/index.json` 摘要（含 `lineage`）；不追加则留给 gardener 汇总。
7. **经继承接管（sendbox Mode B）**：若本会话是经 inheritance-mode handoff 接管某角色（承担者换人、角色不变），spec.json 写 `lineage = 前任 lineage + 1`、`lineage_origin = 前任 session_id + 交接信名`（面包屑，非权威，见 §2.1）；`generation` 仍按本会话自身重启计（新会话即 1，与 lineage 无关）。
8. **写 `stopped` 的门槛（自登记指南硬约束）**：只有**会话真正结束**（AgentTUI teardown 或 Mode-B 角色交接、当前会话不再续任）才写 `state: "stopped"`——任务完成 / archive / 末条回复 / 等用户输入 / prompt 空闲 / compact / 上下文重置**都不是会话结束**（定义见 §3「stopped 写入门槛」）。**严禁在本会话仍将继续处理 turn 时标 `stopped`**；这类场景只刷 `last_seen` 心跳。**修复误标**：本人下一个可信触点直接把 `state` 改回 `active` 并刷 `last_seen`（heartbeat 同步项目 leaf 与全局 index）；gardener 复核到 contradiction 条目时亦按此修复、不 GC。

## 6. 许可说明

本规范的机制思路（spec/runtime 两文件分离、扫目录即发现、last_seen + generation 判活等）借鉴自 CCB（AGPL-3.0）的**设计概念**，全部以自有措辞重述，未复制其任何源码或原文；Arborist 及本 guide 保持 Apache-2.0。
