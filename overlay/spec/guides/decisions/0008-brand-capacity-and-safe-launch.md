# ADR-0008: brand-capacity 是观测非权威 headroom；observer 只观测；launcher 选二进制、session 自登记 brand

- **Status**: accepted
- **Origin**: 07-29-brand-capacity-launch-issue14（上游 issue #14：brand-capacity observer + safe AgentTUI launch contract）
- **Date**: 2026-07-29

## 三门自检（都 yes 才该是 ADR）
- [x] 难逆（改起来代价大）—— 「容量语义（source/freshness）」「observer 的能/不能」「launcher 与 brand 自登记的分工」被 observer、启动契约、编排选 brand 的正确性共同依赖；定错会让陈旧/派生值被当权威 headroom、或让启动器代写 brand 而污染路由权威。
- [x] 无上下文会让人惊讶（反直觉）—— 「有个 `used_percent` 数字看着就能当 headroom 用」看似显然，但被动落盘的 Codex rate_limits 可能陈旧、cost/burn 根本不是 headroom、Claude 的 `/usage` 可能命中内部缓存（`cachedUsageUtilization`）而非服务器往返；「启动器顺手把 brand 也登记了」看着省事，实则破坏「actual runtime brand 是路由唯一权威」(ADR-0006)。
- [x] 真权衡（有被牺牲的合理替代）—— 把容量限定为「观测 + 只读推荐」牺牲了「observer 直接按容量拉起/切换会话」的自动化便利，换取无不可逆调度、无凭证接触的安全边界；collector 借本机登录态 poll 牺牲了「完全零 CLI 依赖」，换取 Claude Code 可被随时 poll。

## 背景
Arborist adopter 需要两项相关能力:安全启动独立 AgentTUI(不继承父身份、不投错 pane、不代写 brand),与建新 Impler 时按容量选 brand。缺少共享契约,启动器会继承父 session 身份、往匿名焦点 pane 打字、或替被启动方猜 brand;容量侧则会把陈旧/派生值当权威 headroom。上游 issue #14 要求把这两项收敛为 durable 契约。

## 决策
记录三条决策(实现见 `arborist_brand_capacity.py` + guide `agenttui-launch-and-brand-capacity.md`):

1. **容量是观测,不是权威 headroom**:每条观测显式带 `source`(`polled`/`self-reported`/`unavailable`)与 `observed_at`(freshness);`unknown`/stale 观测不可伪装成 fresh headroom(`observed_at=null` 永不可选);cost / burn rate / time-to-window-boundary 等**非-headroom 派生值禁入** `used_percent`,至多进 `diagnostics`。Claude Code 的 `observed_at` 是**查询新鲜度**而非服务端数据生成时刻。

2. **observer 是观测者不是执行者**:它**绝不**启停会话、改 agent 注册、代写 brand、跨 brand 切既有 Impler(或其 L1 链)、做不可逆调度;**不读/存/打印凭证**、无网络;单写者 `flock` 下**原子写**快照(占用即 fail-closed)。推荐**仅建新 Impler 前合法**。

3. **launcher 选二进制,session 自登记 brand**:启动器只选启动哪个真实 CLI 二进制;被启动会话按 [ADR-0006](./0006-runtime-brand-is-routing-authority.md) 自登记其 **actual runtime brand**(启动器绝不代写)。既有 Impler 及其 L1 链**绝不跨 brand 切换**——容量耗尽则停下 handoff 给新建 Impler;多账户歧义 **fail back 人工确认**。

## 被否方案
- **让 observer 直接按容量拉起/切换会话**:自动化更省事,但引入不可逆调度 + 需碰凭证/会话生命周期,破坏「观测者非执行者」边界。
- **把 cost/burn 当 headroom 代理**:ccusage 类指标现成,但它们不是剩余容量,会系统性误选 brand。
- **启动器顺手代写被启动方 brand**:省一步自登记,但违背 ADR-0006「actual runtime brand 是路由唯一权威」,让声明与实际 runtime 脱钩。
- **Claude Code 恒 unknown,除非已登记会话自报**(issue 正文原 prose):collector 出现前的模型;现被 collector supersede——外部进程可机械借登录态零副作用 poll `/usage`,self-report 降为 fallback(见 guide §2.4 supersede 说明)。

## 后果
- 正:容量语义诚实(source+freshness 显式),陈旧/派生值无法伪装 fresh headroom;observer 无不可逆副作用、无凭证接触,可安全随时跑;启动契约与 brand 自登记分工清晰,路由权威(ADR-0006)不被污染。
- 正:collector 让 Claude Code 可被随时 poll,不再依赖「必须有已登记活跃会话」。
- 负:`claude -p /usage` 字段/行为随版本变(guide 标注版本相关性),漂移时 collector 降级 best-effort、fail-closed 到 unknown。
- 负:无闭集 / 采信门不过等场景 observer **主动 fail-closed**,不给「尽力猜一个」的便利;多账户共享 `~/.codex/sessions` 则是**文档化的已知局限**——observer 不分账户、取全局最新观测,跨账户须**人工判定**(非机械检测,不自动记 diagnostics)。两者都刻意不猜,是取舍。

## 与既有 ADR 一致
- **ADR-0006(actual runtime brand 是路由权威)**:决策 3 的「launcher 选二进制、session 自登记 brand」是同一原则在**启动/选 brand 维度**的延伸——启动器不代写、runtime 自登记。
- **ADR-0007(投递契约 + 可插拔 adapter)**:本 ADR 的启动契约(guide §1)是投递契约的**启动侧姊妹**,共用 pane 定向(`--pane-id`)与「fail-closed、不猜」取向;core 仍 transport 中立(命令用泛化占位)。
- **ADR-0002(声明+派生态,无守护进程)**:observer `serve` 是**可选前台循环、非 daemon**,与「core 无守护进程」一致;快照是读时消费的声明态,freshness 由消费方判定。
