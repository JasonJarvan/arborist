# T1 · LLM / Agent 测试方法论

> 源：`stochastic-llm-tool-choice-testability` · `message-tool-routing-sticky-assumption` · `ec-isolation-via-home-env`（剥离产品特定的消息/总线细节）。<project> 有 AI agent → 最高价值一簇。

## 核心

- **LLM 选哪个 tool 是随机的**，单条 happy-path mock 覆盖不到 dud 路径。agent 集成测试必须：
  - **N+1 tool-variant 矩阵**：每个已注册 tool 一个用例 + 一个纯文本（不调 tool）用例；
  - **真 provider 随机 smoke**：temperature>0 跑 **10+ 次**，看分布而非单次；
  - **force-pick 关键 path**：system-prompt 会把某 tool 频率压到近零 → 对关键 path 用 mock 强制选中，别指望随机 smoke 覆盖到。
- **子系统别在构造期绑死 output sink**：给 runtime 覆盖 API，否则 caller 想 redirect 会撞黑洞。runtime swap + `finally` restore 要用 `swapped: bool` guard，不要用 `prev is not None`（原值合法为 None 时会留孤儿）。
- **测试隔离**：①用专用配置/home env var 隔离状态，别硬编码 home 靠 HOME 劫持（会污染 git/缓存等无关状态）；②LLM 调用用 mock response 隔离，**不烧 token**；关键 path 才跑真 provider。

## 落点
<project> agent 相关包的 `.trellis/spec/<pkg>/` 测试规范；trellis-before-dev checklist。
