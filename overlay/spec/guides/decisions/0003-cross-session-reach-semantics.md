# ADR-0003: `session_id` 触达语义 = `--resume` 追加，据活性选通道

- **Status**: accepted（**amended 2026-07-23**，见文末 Amendment）
- **Origin**: gardener 实证回填（dogfood）
- **Date**: 2026-07-22

## 三门自检（都 yes 才该是 ADR，否则留 task notes/guides）
- [x] 难逆（改起来代价大）—— 触达语义定错会让 agent 去 corrupt 同伴活会话
- [x] 无上下文会让人惊讶（反直觉）—— 「无消息投递」曾被读成「跨 session 通信完全不存在」，实则原生可用
- [x] 真权衡（有被牺牲的合理替代）—— 直投 vs 文件信，按对方活性取舍

## 背景
[agenttui-registry.md](../agenttui-registry.md) 曾以一句笼统的「无守护进程、无消息投递、无自动注入——属长期目标」概括通信能力，同时又把 `session_id` 定为「触达句柄」。二者张力导致读者（含本 harness 自身）误判：以为跨 session 只能靠人带话。需澄清 `session_id` 到底支撑哪种真实触达语义，并给出安全用法。

## 决策
以 `session_id` 为**跨 session 触达句柄**，语义按对方**有效态**（ADR-0002 派生模型）分通道：

- **非活（stopped/idle）**：`claude -p --resume <session_id> "<msg>"` 向对方 `.jsonl` **追加**消息，对方下次 resume 在完整上下文里处理。异步单向、无原生回执（`-p` 回复走调用方 stdout）。
- **活（active TUI）**：**不**做 `--resume` 注入（官方未文档化，多头写同一 transcript 会 interleave）；改走 durable 文件信（sendbox）或 Agent Teams mailbox。

「不含自动投递」的原范围收窄为：不含**常驻自动化 runtime**（A2A 自动回投 / callback 续跑 / `write-chars` 注入），非否定手动一次性触达。

## 实测证据
gardener 于一次性 throwaway session 实证 `claude -p --resume`：
- 同一 `.jsonl` 行数 11→18、无新 session 文件生成 → **append，非 fork**（官方文档 "appends new messages to the existing conversation" 得到本地印证）。
- resumed 那轮准确复述前一轮设定的暗号 → **完整携带历史上下文**。
- 活-TUI 并发 resume 的竞争行为：官方未文档化，本地亦未实证（非交互环境难复现活 TUI）→ 对活 peer 采保守「不注入」规则，不依赖未证行为。
- **Codex 判活探针**（附带实证，解 ADR-0002 遗留）：`codex exec` 建 rollout `~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<sid>.jsonl`；`codex exec resume <sid>` 续**同一** rollout（14→25 行、mtime 21:29:02→21:29:26 递增、今日文件数仍为 1）→ Codex mtime 随 turn 递增，判活探针成立，与 Claude Code 同。

## 被否方案
- **一律用 `--resume` 直投（含活 peer）**：简单，但对活 TUI 是未文档化竞争，可能扰乱 / 破坏对方会话。
- **一律走 sendbox 文件信**：安全，但对非活 peer 放弃了原生、即时、进对方上下文的投递能力，退化为「等人带话」——正是本 ADR 要纠正的误判。

## 后果
- 正：触达句柄语义明确、可执行；据活性探针选通道，既用上原生能力又避开未证风险；与 sendbox（durable handoff）分工清晰。
- 负：无原生回执，双向 / 等回复仍需外层协调（sendbox 回信 / mailbox / 轮询）。遗留（归 gardener 待测回填）：跨目录 / 跨项目 `--resume` 的 lookup 行为；~~活-TUI 并发 resume 的确切竞争表现~~（已由 Amendment 解决）。

## Amendment（2026-07-23）

**「活 peer 不注入」条款被推翻**：按 user 决定，对**活** session 的 `claude -p --resume` 注入是**受支持的行为**，可以使用。原条款的依据（官方未文档化 + 本地未实证 → 保守推定）不再成立。此处**不删除原推理**（决策历史保持诚实）——原「多头写同一 transcript 会 interleave」的 interleave 顾虑视为**已接受 / 退役**，而非从未存在；本 Amendment 取代（supersede）上文「活→不注入、改走文件信」的保守条款，其余原文照旧留档。

修正后的决策：**三通道 + 记录⊥送达正交**（user 定义 2026-07-23，取代早前「按消息性质二选一」的中间表述）。跨 session 通信有三个通道：
- **① 直投** = `claude -p --resume <session_id> "<msg>"`——**不论对方活性**（含活 peer）；
- **② 写信 / sendbox** = durable 文件信 = 信物 / 记录（outlive 会话、可审计、落定前 HITL）；
- **③ 用户投** = 用户亲自把 prompt 发给目标——**仅当用户明确说「给我 prompt 我去说」之类**才用。

关键：**记录轴与送达轴正交，不是单一通道二选一**——
- **记录轴（是否需要信物）**：durable 承诺级（handoff / decisions / plan-ready / 交付 done）**必写信**（信 = 记录）；瞬态 chatter（催活 / 问答 / 通知 / ack）无需写信。
- **送达轴（怎么送达 / 提醒）**：直投是送达提醒，由发送方自定——**写信不排斥同时直投，直投也不豁免写信**（内容 durable 时）。
- 故：durable = 写信（必）+ 直投（可选）〔或 ③〕；瞬态 = 直投即可〔或 ③〕。用户说「你告诉 xxx 去做什么」= 直投指令，其内容 durable 则成为信 + 直投。

「被否方案」表相应更新：「一律用 `--resume` 直投（含活 peer）」作为**送达手段**不再被否；被否的只剩「durable 内容**只**直投、不写信」（缺可独立评审的信物与审计面）。活性探针保留原价值：预估触达时延 + gardener GC。

同步修改：`agenttui-registry.md` §3 触达段已按此重写（三通道 + 记录⊥送达正交，不再按对方活性或单纯消息性质二分）。
