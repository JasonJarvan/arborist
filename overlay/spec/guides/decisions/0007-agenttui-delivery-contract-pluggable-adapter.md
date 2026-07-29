# ADR-0007: AgentTUI 活 pane 投递 — 契约进规范，具体传输作可插拔 adapter

- **Status**: accepted（rootorc harness 自开发，authored + ratified；**amended 2026-07-29**，见文末 Amendment）
- **Origin**: dogfood — 下游 adopter 实证出活 pane 投递缺口并先行实现，上游 rootorc 收敛为契约
- **Date**: 2026-07-27

## 三门自检（都 yes 才该是 ADR）
- [x] 难逆（改起来代价大）—— 投递契约、送达证据语义、submit-key 路由被任何 adapter 与编排正确性共同依赖；定错会让消息静默丢失或假阳性「已送达」。
- [x] 无上下文会让人惊讶（反直觉）—— 「往 composer 敲 Enter 就送达了」看似显然，但 Enter 会 steer 一个正忙的 Codex turn 而非入队 → 静默不送达；且「pane 命令成功 / 转录增长 / mtime 变化」看着像送达证据，其实都不是。
- [x] 真权衡（有被牺牲的合理替代）—— 把投递拉进规范牺牲了 §3 原本「无自动投递」的极简边界；而「契约进 core + 具体传输作 adapter」又牺牲了与下游即时全量对齐，换取 core 的 transport 中立。

## 背景
Arborist 注册表刻意 **transport 中立**（剥离了 CCB 全部 tmux/pane/send-keys 细节），agenttui-registry §3 原将「往活 pane 注入」列为**明确 out-of-scope 的长期目标**，现成跨 session 触达只有三通道（直投 `--resume` / 写信 sendbox / 用户投）。

实证暴露两个真缺口：
1. **直投不可靠**：`claude -p --resume` 对活 TUI 注入会与其正进行的 turn 竞态、其回复走调用方 stdout 而非对方 TUI；`codex exec resume` 对活 session headless 续跑会挂死。发送方无法确认对方是否真的看见。
2. **送达无诚实证据**：pane 命令成功只证明字节到了 pane，不证明进了对方 transcript；固定延时解决不了状态竞态；转录 size/mtime 增长也非有效证据（忙碌目标会自行增长转录）。

下游 adopter 已 dogfood 出解法（active Codex 用 Tab 入队、nonce 越界 marker 作送达证据、fail-closed），请求上游采纳。

## 决策
把**投递契约**收进规范（agenttui-registry §3），将原「无自动投递 runtime」的绝对边界修订为：**投递是一个受本契约约束的可插拔 adapter；core 只规定契约、保持 transport 中立**。

**契约（规范性，任何投递 adapter 必须满足）：**
1. **brand + 活性感知的 submit 路由**：
   - 有效**活跃** + `brand=codex` → 写入信封后**发一次 Tab（byte 9）入队**到下一 turn，**不 steer** 当前 turn；
   - **空闲 Codex** → 发 Enter（byte 13）提交；
   - **Claude Code** → **不分活性一律 Enter 提交**。**为何不照搬 Codex 的 Tab**（#12 官方补充裁定）：Claude Code 官方 keybinding 只有 `chat:submit`=Enter，其 Tab 用于 autocomplete / tab 导航，**没有 Codex-Tab 那样的独立「入队到下一 turn」动作**；目标忙碌时由 **Claude Code 自身的 receiver-side queue** 在当前 turn 跑完后处理，故活跃/空闲都用 Enter 即可、无需另找入队键。**⚠️ 勿给 Claude Code 套用 Codex 的 Tab**——那会落进 autocomplete/导航语义、不会入队提交，是误改。
   - 理由（Codex 侧）：对活跃 turn 入队让其先跑完，防外部 agent 把决策注入到实现进行到一半之中。
2. **不盲目重发入队键**：送达未观测到时**不得**重发 Tab（会入队重复信封）。
3. **送达证据必须 message-specific**：注入前**记录目标 transcript 字节边界**；每次发送生成**唯一 nonce**；仅当该信封的 nonce marker 出现在边界**之后**才返回 `delivered`；否则返回 `queued-unverified`，**绝不假阳性成功**。pane 命令成功 / pane 存在 / 转录增长 / mtime 变化**都不是**送达证据；**peer 回复是唯一的语义 ACK**。
4. **fail-closed**：未验证即 `queued-unverified`，不是 `delivered`。

**具体传输（zellij pane + 字节注入）= 可插拔参考 adapter，不进 core**，与 [roles-and-tiering.md](../roles-and-tiering.md)「transient 是可插拔扩展点」同一取向（core 定契约、具体后端可插拔 opt-in）。core 规定契约，不规定终端复用器。activity（活跃/空闲）取自 ADR-0002 的读时派生态（含 contradiction 亦按活跃处理）。

## 被否方案
- **把下游的 zellij-pane + submit-key 字节注入整套塞进 core template/generator**：与下游即时全量对齐，但把 Arborist 焊死到 zellij 这一具体传输、放弃当初从 CCB 剥离换来的 transport 中立。
- **维持投递完全 out-of-scope**：留下直投竞态 + 无送达证据的真痛点不解，且各下游各自重建互不兼容的投递层（现实已在发生）。
- **Enter-only / 固定延时 / 转录增长当证据**：正是本 ADR 记录的失效模式。

## 后果
- 正：编排获得可靠、brand 感知、证据诚实的投递契约；下游对齐到**一份契约**而非各自发散实现。
- 正：core 保持 transport 中立，终端复用器可换；参考 adapter 随发但 opt-in。
- 负：想要活 pane 投递的 adopter 须提供/启用一个满足契约的 adapter；参考 adapter 是 opt-in 非默认。
- 与 [ADR-0003](./0003-cross-session-reach-semantics.md) 三通道关系：本 ADR 在通道①（直投）之外**新增一类可插拔投递能力**（活 pane 入队投递 + 诚实证据），**记录⊥送达正交不变**——durable 内容仍必留信，pane 投递只是送达侧的一个更可靠选项。
- **候选未来 transport（备注，非依赖）**：官方 **Channels** 能把外部事件推进一个已运行的 Claude Code 会话，是一个**候选未来投递 transport**——若成熟可作为满足本契约的又一 adapter 后端。但它当前仍是 **research preview**，且**需在会话启动时显式 opt-in**，故**暂不作 Arborist 的默认依赖**（与「可插拔 adapter、opt-in、core 保持 transport 中立」一致）。

## 与既有 ADR 一致
- **ADR-0001（session-id 主键）**：adapter 寻址 pane，但送达证据仍锚在 session_id 定位的 `session_file`/transcript 上，不改主键。
- **ADR-0002（声明+派生态）**：submit 路由的「活跃/空闲」直接复用读时派生态（含 contradiction 按活跃处理），不新增状态源。
- **ADR-0006（brand 是路由权威）**：submit-key 路由本身就是 **brand-keyed**（codex vs claude-code 分流），是同一「按实际 brand 路由」原则在投递维度的延伸。

## Amendment（2026-07-29）

**动因**：dogfood 巡检（一个 adopter 实例的全机巡检 + 上游 gardener 复核）暴露原契约三处失真 + 一处遗留可回填。原决策正文**照旧留档不删**（决策历史保持诚实）；本 Amendment 只**增补与更正**下述四点，规则 1（brand + 活性感知 submit 路由）、规则 2（不盲目重发）、规则 4（fail-closed 精神）**均不变**。**证据等级逐条标注**——「上游已独立复现」与「下游实测、上游未复现」不得混为一谈。

### A. 规则 3 的字节边界在 transcript 被重写时产生假阴性（**取代**原规则 3 的判定路径）

原规则 3 把「transcript 单调 append」当**不变量**：记边界 → 只在边界之后搜 nonce → 否则 `queued-unverified`。**该不变量不成立**：Claude Code 的 **compact / rollout 重写**会原地重写会话文件，字节偏移不再对应「投递后新增」。

**实测（下游 adopter 实例 dogfood；上游 gardener 未独立复现）**：一次投递后**全文件** grep 到该 per-send nonce 多次、目标输入框已清空（**确实送达**），但按边界 `tail -c +N` 检测得 **0 次**；目标刚做过 compact。

**后果为何严重**：这是**假阴性**（实为送达、判为未送达），而 `queued-unverified` 正是调用方**重发**的信号 ⇒ **重复投递**——恰好撞上规则 2 要防的事。fail-closed 本意是「宁可不确认」，不是「制造错误的否定」。

**修订后的判定（已同步写入 agenttui-registry §3 规则 3）**：
- 注入前记**位置指纹 = inode + size**（不是裸偏移）；
- 指纹可核对（inode 未变、size 未缩小）→ 边界之后搜 nonce，命中 = `delivered`，证据等级 `envelope-nonce-found-after-boundary`（强）；
- 指纹不匹配（inode 变 / size 变小 / 无法核对）⇒ 文件已被重写 → **降级为全文件 nonce 搜索**，命中 = `delivered`，证据等级 `envelope-nonce-found-fullfile`（弱，但**仍是送达证据**）；**不得**因指纹核不上就判 `queued-unverified`；
- 「未验证」重新界定为**两路都没搜到 nonce**；规则 4 的 fail-closed 由此保持不变。
- **为何全文降级不引入假阳性（本 Amendment 的关键论证）**：nonce 是 **per-send 唯一**的，只可能由本次发送写入 ⇒ 全文命中蕴含「本次信封进了对方 transcript」。字节边界原本防的是「把历史里的旧 marker 误当本次送达」，而**唯一 nonce 已在源头排除该情形**；边界因此只是**证据强度加成**，不是防假阳性的必要条件。**边界仍不可废**：它区分强/弱证据，且对使用**可复用固定 marker**（非唯一 nonce）的 adapter 而言，全文降级**不成立**、必须留在边界路。
- 不变：pane 命令成功 / pane 存在 / size 增长 / mtime 变化都**不是**送达证据；peer 回复是唯一的语义 ACK。

### B. `--pane-id` 寻址不免除聚焦 ⇒ 投递抢焦点是**已知架构局限**

**实测（下游 adopter 实例 dogfood；上游 gardener 未独立复现——上游无法在人类正在使用的 session 里试焦点抢夺）**：zellij `write-chars --pane-id <目标>` **跨 tab 不生效**，跨 tab 投递必须先 `focus-pane-id` 聚焦。这**推翻**了 agenttui-registry §3 参考 adapter 段原先那句「按 `pane_ref` 定向注入（**不靠焦点**）」——该句已据实更正。

**架构后果（本 ADR 正式记录为局限，而非缺陷待修）**：投递因此**必须抢焦点**，与「人类正在同一 zellij session 里切 tab / 移焦点」**结构性冲突**。这不是参数没调好，是「用 GUI 焦点做投递寻址」这一 transport 的固有性质。

**处置**：终端复用器的选择**正在评估**（评估中，本 ADR **不承诺**任何具体替代复用器）。**core 的 transport 中立正是为此保留的**：契约（规则 1–5）不依赖 zellij，换复用器只换 adapter 与 `pane_ref` 值域，契约不动。在替代方案落定前，唯一诚实的规避是「投递期间避免人机同时操作同一 session」。

### C. pane 存在性探针裁定（**新增**规则 5）

契约新增规则 5（transport 中立表述）：**存在性 preflight 必须选「对不存在的 pane 会明确报错」的探针，且按 stdout 文本判定；不得靠退出码，禁用「静默返回空」的读屏类命令。** zellij 侧具体裁定：
- `zellij action dump-screen -p … --pane-id <不存在>` → **静默返回空且 rc=0**（**上游 gardener 已独立复现**）⇒ 用作 preflight 会得**假阳性**（把不存在的 pane 认作存在），禁用；
- `zellij action focus-pane-id <不存在>` → 明确打印 `Pane with id Terminal(<N>) not found` 且不改焦点 ⇒ 可靠探针；**但它 rc 也是 0**（**上游复现时发现，下游报告未提**）⇒ 必须**解析 stdout 文本**。

存在性 preflight 只解决**寻址**，本身**不是**送达证据（不改规则 3）。

### D. 跨目录 `--resume` lookup 回填（原「遗留待实证」结项）

**实测（下游 adopter 实例 dogfood；上游未独立复现）**，按 brand 拆开：`codex exec resume` **跨目录可行**；`claude --resume`（含 `-p --resume`）**跨目录必失败**，须在**目标项目目录**内执行。故跨项目直投 Claude Code 会话前必须先切到 `spec.project.path`。ADR-0003「后果」里归 gardener 待测的该项**至此回填**（其余待实证项不受影响）。

### 实现状态（**必须与契约分开读**）

本 Amendment 收紧的是**契约**。随发 operational adapter `overlay/scripts/agenttui.py` 截至 2026-07-29 **尚未**实现 A（双指纹 / 全文降级 / 证据等级标注）、B（`focus-pane-id` 前置聚焦）、C（存在性 preflight），port 任务另行追踪；缺口已在 agenttui-registry §3「随发 adapter 的契约缺口」逐条标注。**规范先于实现是刻意的**（契约是判据、实现向它收敛），但**任何「契约要求、实现未做」的点都必须显式可见**——不得写成「参考 adapter 已满足全部契约」。

### 三门仍成立 / 为何是 amendment 而非新 ADR

三门：难逆（送达证据语义被所有 adapter 与编排正确性共依，A 改的正是判定核心）、反直觉（「记边界再比对」看着比全文搜索更严格，实则在文件被重写时更弱——它把假阴性当成了保守；「`--pane-id` 就是定向寻址」看着显然，实测却要靠焦点）、真权衡（全文降级牺牲了「边界之后」这层额外强度，换取不再制造假阴性与重复投递；记录 inode 牺牲了实现简洁）。

不是新 ADR：核心决策未动——投递仍是**受契约约束的可插拔 adapter**、core 仍 **transport 中立**、submit 路由仍 brand-keyed、fail-closed 仍在。A 只改规则 3 的**判定路径**（其「message-specific、绝不假阳性」的目的不变），B 记录已知局限，C 补一条同族规则，D 回填遗留实证。与 ADR-0002/0003/0006 的自我 amendment 同构。
