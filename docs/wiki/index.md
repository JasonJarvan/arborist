# Arborist Wiki

> **阐释层**文档:把规范/设计里的重要机制展开讲透(时间线、状态机、走查示例)。规范本体(canonical)在 `overlay/spec/guides/`,设计稿在 `docs/superpowers/specs/`;wiki 页只阐释、不另立规则,冲突时以规范为准。

| 页面 | 内容 |
|---|---|
| [AgentTUI 生命周期与状态机](./agenttui-lifecycle-and-states.md) | 状态集(声明态/保留枚举/有效态)+ 生命周期时间线逐节点走查 + 派生规则 + 设计理由 |
| [安全启动 AgentTUI + brand-capacity observer](./agenttui-launch-and-brand-capacity.md) | 启动走查(new-tab 清父身份 → resolve 稳定 pane → 定向 bootstrap → 自登记 brand)+ 容量 source/freshness 诚实模型 + `/usage` collector 采信门 + recommend 决策流 |
