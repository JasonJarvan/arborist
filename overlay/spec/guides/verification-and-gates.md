# Verification Topology & Merge Gates（<project>）

> 验证镜头、安全门与合并门的拓扑。实例特定的工具/分支/命令一律引 `host-config`（见 [`generalization-boundary`](./generalization-boundary.md)），本篇只定义**拓扑与门的语义**。

## 验证 lens（多镜头）

| Lens | 问题 | 工具 | 何时 |
|---|---|---|---|
| trellis-check | 规范/lint/type/test/跨层 | `trellis-check` | 每次实现后 |
| 行为自验 | 行为是否真对 | SP `verification-before-completion` | 收尾前（与 check 并列**双 lens**）|
| prd 验收核对 | 是否交付了 prd 承诺 | 逐条对 `prd.md` 验收标准 | 2.2 final pass |
| security-scan | 依赖/供应链是否回归 | host-config `security_scan[]` | 依赖变更 + MR 前 |
| 人工 smoke | 真人在真应用里能用吗 | host-config `smoke[]` skill | 用户可见/交互改动 |

## security-scan（依赖安全扫描）—— 接 MR-into-release 硬 gate

- **工具按子树**：变更命中哪个子树、用哪个扫描器，由 host-config `security_scan[]` 的 `match → tool` 映射定义（可达性扫描器如 govulncheck 对**代码触及已知 CVE 路径**也算命中，非仅依赖清单变更）。
- **触发**：依赖变更时必跑；多子树各跑各的。
- **gate 位置（关键）**：真闸是 **MR 进 release 分支**（host-config `git.release_target`），**不是** `task.py archive`（本地簿记，拦不住发货）。→ security-scan pass 是 **建 MR（host-config `git.pr`）的前置**；**未跑或未裁决 → 不得合入 release**。policy=ask-first（基线已知 CVE 由用户裁 accept-vs-fix）。
- 跳过（无依赖变更）用 Auto-Skip Log；跳过一个**有**依赖变更的扫描 = Recipe Invariant Exception。

## 人工 smoke gate

用户可见/交互改动在收尾前产人工 smoke 清单（覆盖自动化够不到的：真 LLM 输出、视觉/交互保真、确认层、忙态时序），挂 host-config `smoke[]` 声明的 skill。full-lane 建议做；纯后端/逻辑改动可跳（Auto-Skip Log）。

## 代码评审（Phase 3）

- 接实例定制层声明的评审命令（如 `<code-review>` / 安全相关 `<security-review>`）+ SP `requesting-code-review`。
- 收到反馈按 SP `receiving-code-review`：**先核实再改，不橡皮图章**（技术上站不住的建议要质疑，不 performative 同意）。

## Merge Gates + Challenge-before-ack + HITL 晋升门

- **HITL 晋升门**（知识进 `.trellis/spec/` 或 ADR）：finish 时把晋升候选列给用户评审再落盘，不自动写。
- **Challenge-before-ack（subagent 驱动，close-out 时跑）**：晋升候选被 ack **前**必须由一个**独立 challenge/red-team subagent** 唱反调。**在哪跑**（对齐 `roles-and-tiering.md` 收尾职责分层）：full-lane 由 **L2 收尾起草**时派（对自己交付唱反调）；fast-lane-直做 与**跨任务裁决**由 L4/human 派。**独立性**：subagent 与派方共享先验，靠**对抗立场**补（prompt 明令「尽力反驳、默认候选不成立」）——立场独立优先于上下文独立。subagent **只挑战 + 列冲突**；最终 ack（`proposed→accepted`）与冲突仲裁归 owner（L4/human），不由 subagent 或起草方自裁。**至少**做两件事：
  1. **查重**：把每个晋升候选与既有 `.trellis/spec/` + ADR + methodology + 已有 mem 逐条比对，确认**不存在重复**（重复则删、不晋升）；结构性事实用 codegraph 核（代码可派生的不进 mem）。
  2. **查矛盾**：候选是否与既有 spec/ADR/mem **冲突**（同一主题不同结论、被推翻的旧决策未标 superseded）；**有矛盾则明确列出冲突双方 + 供 user 决定**（保留哪个 / 合并 / 标 superseded），不由子代理或主会话自行裁。
  其余仍查：过度晋升？可逆选择当永久？验收未达标？被否的更强方案？子代理**只挑战**，最终 owner（HITL 时=用户）看着反调 + 冲突清单再拍。
- **顺序**：security-scan（依赖变更时）pass → 进 MR；HITL 晋升在 archive 后（RepoMem.merge 语义）。
- 一个变更未过 trellis-check + 行为自验，不进收尾；依赖变更未过 security-scan，不合 release。
