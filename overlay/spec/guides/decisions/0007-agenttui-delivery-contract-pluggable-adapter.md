# ADR-0007: AgentTUI 活 pane 投递 — 契约进规范，具体传输作可插拔 adapter

- **Status**: accepted（rootorc harness 自开发，authored + ratified）
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
