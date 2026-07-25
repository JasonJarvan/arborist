# T3+T6 · 契约单一真源、防漂移、数据字段设计

> 源：`rpc-schema-single-source-of-truth` · `dynamic-cli-catalog-pattern` · `umbrella-registration-drift` · `blacklist-fanout-audit-pattern`（T3）；`usage-aggregation-scope-mix-trap` · `reserved-persisted-fields-need-a-reader` · `streaming-nonstreaming-response-parity` · `stream-and-retry-incompatibility`（T6）。<project> Go server↔npm web 有跨语言契约 → 高相关。

## 契约单一真源 + 防漂移（T3）

- **跨边界契约单一真源**（schema 文件），各侧代码是**衍生物**；drift 检测**双向强制**（一侧 parity 测试 + 一侧 checksum lint）。无法立即 formalize 时走 staged formalize（先 ship 真实形状 + 锁 key-set，再独立立项升格，commit 里点名 follow-up 防搁置）。
- **派生优于手维护镜像**：不要手工维护"镜像另一系统表面"的白名单；用反射/派生在请求时生成，令重命名/增删零改动传播；失败要 graceful degrade 不抛。
- **注册漂移**：任何"批量注册 + 另处手工展开该批量"的结构必漂移（新成员只进批量、漏进手工展开，测试走批量全绿、生产挂）→ 重构成 `_except_X` helper 让生产集**派生自**批量集 + parity 回归；重复注册 **raise 而非 last-wins**。
- **安全集合审计**：扩展黑/白名单、权限表、feature flag 时不能只 `grep 常量名`——if/elif 阶梯、正则、参数化测试里藏"影子副本"。三查（常量名 + 字面值 + 领域措辞）；根治靠单源常量 + 内省测试 + 用常量本身参数化测试。

## 数据/字段契约设计（T6）

- 同一 payload 内数值字段必须**同一聚合 scope**（全 per-session 或全 lifetime），混填 = 自相矛盾 baseline；混用则字段名带 scope 前缀；新实体 boot baseline 硬编码 0/null，不读 cross-scope 聚合器。
- **预留字段需有真读者**：keep 前全仓 grep 验证；零读者的"为未来预留"是投机重量，不是 forward-compat。
- **双路径 parity**：同一对象由两条独立路径组装（流式/非流式、方法级 fallback）会静默漂移；任何消费某字段的 feature **两条路径都要验**，专门覆盖较少走的那条。
- **streaming ⊥ auto-retry**：流式与自动 retry 本质冲突（重启重发 token/需 dedup），必须显式声明 retry policy（"不 retry 交 caller"是合法选择），禁止把 retry 偷偷塞进 stream 路径。

## 落点
`.trellis/spec/guides`（契约/防漂移）+ code-review 规则；agent 层 ADR。
