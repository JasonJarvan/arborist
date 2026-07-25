# T5 · 依赖 / 迁移治理

> 源：`vendor-fork-strategy` · `third-party-backend-fallback-ladder` · `cross-language-rpc-adapter-pattern` · `dsl-vs-python-api-decision`（剥离产品特定选型细节）。

## 核心

- **vendor 上游**：pin commit（记 SHA/时间/分支）、不做 wholesale replace 按分阶段流程、明写 **re-evaluation triggers**（何时该切维护策略）、配 attribution（LICENSE/NOTICES）。
- **第三方 backend 选型 4 级 fallback 阶梯**：L0 上游 → L1 vendor → L2 替代 → L3 自实现；每级 **number-driven 触发条件 + 工时预估 + 维护监控责任人**。避免"YOLO 假设"与"过早双 backend 抽象"两极。
- **接口迁移用 adapter/绞杀者**：≥N（约 10）个消费方依赖旧接口时，薄 adapter 包新实现暴露旧形状 → 零改动保留消费方；配决策矩阵 + 退役准则（逐个迁移后整体删）+ 铁律"**adapter 纯透传、绝不加逻辑/改事件名**"。
- **DSL vs 宿主语言 API**：主消费者是 **AI agent 时 DSL 价值近零**（非程序员友好/生态互通都用不上）→ 直接用宿主语言 + 原生测试生态。警惕"DSL 显专业""将来有非程序员用户(YAGNI)"两个 bias。

## 落点
ADR（选型决策，带 `Origin`）/ dependency-selection guide。
