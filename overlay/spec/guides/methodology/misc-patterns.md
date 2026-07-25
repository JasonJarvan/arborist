# Tier3 · 杂项窄技巧（备查，剥离产品细节）

> 源见各条。低频/窄，全收但不强调。

- **override fail-closed**（`node-discovery`）：用户显式设了 override（env）时必须 fail-closed，**绝不静默 fallback**——静默回退掩盖配置错误、产诡异版本 bug。
- **配置默认真实生效点**（`tui-config-driven-defaults`）：一个"默认值"的真实生效点在它**最后被写入处**（如 config poll 的 normalizer），不在初始化处；改默认前先定位权威写路径。附：白名单 gating 导致的写失败若被 `.catch(()=>{})`/裸 recover 吞掉会静默失败。
- **append 崩溃半行修复**（`locked-append-crash-newline-repair`）：崩溃的 writer 留无尾换行的半行，朴素追加会黏连毁两条记录；locked_append 应在锁内检查最后字节、缺 `\n` 先补。读侧"跳过半行" + 写侧"补换行"是两件独立容错，改动两侧都要在。<project>(Go) 若有 append-only 日志/JSONL/事件流适用。
- **out-param 加 cross-cutting 数据**（`usage-sink-mutable-dict-pattern`）：给多 caller 路径加 usage/metrics/trace_id 而不能改 return type 时，用可选 out-parameter（mutable dict / 传入容器）in-place populate，default 空 = 零开销零破坏；仅当数据是"tap"而非"result"且 caller 集是开集时用。
- **小协议 build-vs-buy**（`python-node-ipc-protocol`）：当框架抽象与需求（细粒度错误码、cancellation、通知/响应共享写锁）冲突时，自写 ~155 LOC + 测试可能更划算；配 anti-drift（注册重复即 raise + umbrella 测试"生产集≡完整集"）。
- **plan 前先研究框架默认**（`tui-plan-writing-checklist`）：写 spec/plan 前先研究框架/运行时默认行为，别重复定义框架已自治的部分（信号/退出码）；plan 别预填 import 列表，让 TDD 自然决定、事后清未用。
- **命令面对齐三类 gap**（`three-case-gap-handling-pattern`）：对接两套独立演化的接口面时——我有他无→透传；他有我无→按 description 去重后 triage，**不 ticket flood**；两边都有→只写集成测试不重复开发。判等价看 description（verb+object+side-effect 三元组）而非字面名。
- **存储旁路 reader**（`session-store-direct-glob-consumers`）：有权威 store manager 时仍会有 reader 绕过它直接扫底层存储；改存储布局时 manager 改完不会自动波及旁路消费者，**改布局前先 grep 旁路 reader** 当独立扫除项。
