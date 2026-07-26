# ADR-0002: AgentTUI 状态用「声明态 + 读时派生态」模型（无守护进程）

- **Status**: accepted（含 2026-07-26 Amendment，已 rootorc accept）
- **Origin**: Arborist dogfood (self-hosting)
- **Date**: 2026-07-22

## 三门自检（都 yes 才该是 ADR，否则留 task notes/guides）
- [x] 难逆（改起来代价大）
- [x] 无上下文会让人惊讶（反直觉）
- [x] 真权衡（有被牺牲的合理替代）

## 背景
注册表要反映每个 AgentTUI 的活/死，但 Arborist 明确不引守护进程（剥离 CCB 的 ccbd/socket/lease）。无常驻进程 → 没有权威的实时状态源。

## 决策
状态分两层：
- **声明态**（agent 自写，仅 `active`/`stopped`，只在 session start 与干净收尾两个可信触点写）（「干净收尾」措辞已由下文 Amendment 收窄为「会话真正结束」——AgentTUI teardown 或 Mode-B 角色交接，见 Amendment 配套写入侧 Guard）；
- **有效态**（读者读表时现算）= f(声明态, `last_seen` 新鲜度, `session_file` mtime 探针)。

`idle` 是纯派生态：agent 空闲时不在运行，物理上不可自写，schema 保留该枚举但 MVP 不自写。stopped/stale 一律是**推定，非确知**；gardener 只保守 GC **条目**（非会话，误删可重建）。阈值 idle 15min / stale 24h 为建议默认。

## 被否方案
- **守护进程维护权威状态**：精确，但重、引依赖、违背剥离 CCB 的初衷。
- **单一 state 字段、每轮自写**：崩溃/关终端无回调 → state 永久停在过期值，读者被误导。

## 后果
- 正：零守护进程、零依赖；读者用 `session_file` mtime 探针零 brand 知识判活。
- 负：「idle 但终端还开着」与「已关终端」不可区分（探针局限）；有效态非确知，编排逻辑须容忍推定误差。遗留（归 gardener 实证回填）：codex 会话文件 mtime 行为**已实证**——随 turn 递增、`codex exec resume` 续同一 rollout，判活探针成立（见 [ADR-0003](./0003-cross-session-reach-semantics.md)）；**仍待实证**：无桥接环境自识别兜底。

## Amendment（accepted 2026-07-26）

**收窄「声明 `stopped` 无条件优先」为「声明优先，但 `stopped` 遇新鲜 live 派生证据矛盾时降级为 contradiction、不无条件采信」。**

**动因（dogfood 暴露的漏洞）**：原派生规则把「声明 `stopped`」列为按序判定首行、无条件压过一切派生证据。实践中某 session 在任务 archive 后手动把 `state` 从 `active` 改为 `stopped`，但同一会话线程随后仍在新鲜窗口内继续处理用户 turn（其 `session_file` 转录 mtime 持续递增）；读者据「声明 stopped 无条件优先」把一个**可证仍活**的会话判成 stopped，且可能被 gardener 当 GC 候选。根因是**任务生命周期**（archive / 收尾）与**会话生命周期**（teardown）的范畴错误，被含糊措辞「干净收尾」放行——既非 GC 误删，也非 mtime 假阳性，而是声明态因范畴错误而失真。

**修订**：`stopped` 不再无条件优先。当声明 `stopped` 与**新鲜 live 派生证据**矛盾——`session_file` 存在且转录 mtime 落在**新鲜窗口**内（距今 < idle 阈值，**或**晚于该 `stopped` 写入记录的 `last_seen`，容小段文件系统时钟偏移）——有效态降级为 **contradiction（可疑 stopped / 疑似仍活）**：reader 视其为 reachable/active；validator 报该不一致叶子；owner 以 heartbeat 修复；**gardener 复核前不得据此 GC**。无矛盾证据时 `stopped` 仍优先，`f(声明态, last_seen, mtime 探针)` 框架与其余判定序不变。

**配套写入侧 guard**：`stopped` 只在**会话真正结束**（AgentTUI teardown 或 Mode-B 角色交接、当前会话不再续任）时有效；session 不得在自身仍是活 session 时写 `stopped`；任务完成 / archive / 末条回复 / 等用户输入 / compact / 上下文重置均非会话结束。详见 [agenttui-registry.md](../agenttui-registry.md) §2.2/§3/§4/§5。

**三门仍成立**：
- 难逆——派生态判定序、validator、gardener GC 共同依赖该优先级语义；定错会让可证仍活的会话被抹除，或让声明态权威凌驾于事实之上难以纠偏。
- 反直觉——「声明是 agent 自写的权威，为何要被派生证据推翻」需上下文才不惊讶：崩溃路径无回调 → 声明态本就不完备，且自写可因范畴错误失真，故对 `stopped` 这一方向须让位于可验证的 live 证据。
- 真权衡——「声明无条件优先」更简单、fail-closed 语义更纯；被牺牲以换取对**可证矛盾**的纠错（代价：读者多一次 mtime 探针与 reconcile 分支）。

**为何作为 amendment 而非新 ADR**：本修订不推翻 ADR-0002 的核心决策（声明态 + 读时派生、无守护进程、declared 一般优先），只在其既定 `f(声明态, last_seen, mtime 探针)` 框架内、复用同一批输入（mtime 探针 / last_seen / idle 阈值）收窄一条边界情形（`stopped` 遇新鲜矛盾证据降级）。未引入新机制、新主键或新数据源，故作为 ADR-0002 的边界修订，与 ADR-0003 对自身的 amendment 同构。

**与既有 ADR 一致**：
- **ADR-0001（session-id 主键）**：contradiction 判定仍以 session_id 定位的 `session_file` 为探针，不改主键、不新增身份维度。
- **ADR-0006（brand 如实声明、fail closed）**：同一「声明须让位于可验证事实」精神在状态维度的延伸——brand mismatch fail closed（拒绝执行），stopped-vs-live-transcript mismatch 降级为 contradiction 待复核（拒绝据以 GC）；两者都拒绝据不可信声明采取破坏性动作，方向一致。
