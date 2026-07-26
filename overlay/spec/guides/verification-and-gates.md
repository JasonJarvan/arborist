# Verification Topology & Merge Gates（<project>）

> 验证镜头、安全门与合并门的拓扑。实例特定的工具/分支/命令一律引 `host-config`（见 [`generalization-boundary`](./generalization-boundary.md)），本篇只定义**拓扑与门的语义**。

## 门有执行者吗（通则：没有机械产物的规则是装饰）

对 overlay 里**每一条规则**问一句：**「谁、在哪个时刻，会注意到这条没有被做？」**

- **有答案** → 它有执行者：一个真会失败的 gate、一个流程必然到达的「必答时刻」、或一个必须落盘的机械产物。
- **没有答案** → 它只是散文，唯一的强制力是「执行 agent 记得遵守」，而**没有任何东西能察觉它被静默跳过**。这种规则是**装饰**，且会**稀释**那些真有执行者的规则——荣誉制门越加越多，能被当真的门越少。

修一条「只靠自觉」的门，首选是**给它一个机械产物**（一个必须产出的落盘物、一个必答的 run-or-skip 记录），**而不是加一条更强的禁令**——更强的禁令同样只能靠自觉，一样会被静默跳过。把「做没做」从**不可审计**翻成**一眼可见**，才真正闭合了门。本篇下面的 **landing manifest** 与 **门控矩阵的「必答时刻」** 都是这条通则的实例；[「已知上游 Trellis 缺口」](#已知上游-trellis-缺口门存在但无执行者)一节则是这条测试**目前答不出**的几处（门写在纸上、执行者在 stock Trellis 里缺席）。

## 门的触发钉在 hazard 上（通则：别拿代理量当开关）

与上一条「门有执行者吗」并列的另一半：一个门**即便有**执行者，只要它的**触发条件**钉错了地方，仍会系统性误火——执行者忠实地执行了一条对不准风险的触发。

**通则：一个门的触发必须钉在它所防的 hazard 本身上，绝不能拿 hazard 的代理量（proxy）当开关。**「文档集大小」（Lane=fast/full）、「任务类别」（后端/前端、是否 user-visible）这类是**任务形状**的代理量——它们与真实**风险形状**只是弱相关，用它们当开关必然出现两类误火：

- **漏火（危险的一类）**：一个任务满足全部"低档"代理条件（fast lane、纯后端、无 UI），却恰好是全仓最高风险（动 authn/authz、或正确性依赖框架/服务器运行时默认）——门据代理量判它"不用跑"，于是**真正需要它的那一次恰好被豁免**。这一格曾漏掉真实 HIGH 授权绕过与 secret-leak。
- **误火（稀释性的一类）**：一个高档代理任务其实无风险，门照跑，喂养"门是走过场"的心态、稀释真有风险时的严肃度。

**修法**：把触发从代理量换成 hazard 的**直接判据**——"这次改动是否触及 authn/authz/secrets/…"、"正确性是否依赖框架/服务器运行时默认"。代理量至多作**附加**触发项（"full lane 也一律跑"），**绝不作唯一开关**。本篇 [「人工 smoke gate」](#人工-smoke-gate) 与 [「Challenge-before-ack」](#merge-gates--challenge-before-ack--hitl-晋升门) 两门的风险形触发即这条通则的实例；二者**共享**的「框架/服务器运行时默认」判据互相[交叉引用](#人工-smoke-gate)、同增同减，正是为了不让任一门悄悄漂回任务形。

## 验证 lens（多镜头）

| Lens | 问题 | 工具 | 何时 |
|---|---|---|---|
| trellis-check | 规范/lint/type/test/跨层 | `trellis-check` | 每次实现后 |
| 行为自验 | 行为是否真对 | SP `verification-before-completion` | 收尾前（与 check 并列**双 lens**）|
| prd 验收核对 | 是否交付了 prd 承诺 | 逐条对 `prd.md` 验收标准 | 2.2 final pass |
| security-scan | 依赖/供应链是否回归 | host-config `security_scan[]` | 依赖变更 + MR 前 |
| 人工 smoke | 真人在真应用里能用吗 | host-config `smoke[]` skill | (a) 用户可见/外部接口 或 (b) 正确性依赖框架/运行时默认（任一命中；(b) 纯后端不豁免，见下「[人工 smoke gate](#人工-smoke-gate)」）|

## security-scan（依赖安全扫描）—— 接 MR-into-release 硬 gate

- **工具按子树**：变更命中哪个子树、用哪个扫描器，由 host-config `security_scan[]` 的 `match → tool` 映射定义（可达性扫描器如 govulncheck 对**代码触及已知 CVE 路径**也算命中，非仅依赖清单变更）。
- **触发**：依赖变更时必跑；多子树各跑各的。
- **gate 位置（关键）**：真闸是 **MR 进 release 分支**（host-config `git.release_target`），**不是** `task.py archive`（本地簿记，拦不住发货）。→ security-scan pass 是 **建 MR（host-config `git.pr`）的前置**；**未跑或未裁决 → 不得合入 release**。policy=ask-first（基线已知 CVE 由用户裁 accept-vs-fix）。
- 跳过（无依赖变更）用 Auto-Skip Log；跳过一个**有**依赖变更的扫描 = Recipe Invariant Exception。

## 人工 smoke gate

**触发钉在风险形，不看是不是"用户可见"——(a)/(b) 任一命中即必跑**（触发钉在 hazard 上的通则见 [上节](#门的触发钉在-hazard-上通则别拿代理量当开关)）：

- **(a) 用户可见 / 外部接口变更** —— 收尾前产人工 smoke 清单，覆盖自动化够不到的：真 LLM 输出、视觉/交互保真、确认层、忙态时序；
- **(b) 正确性依赖框架或服务器运行时默认** —— ASGI/WSGI scope、proxy headers、超时、连接复用、信号处理、中间件顺序等。**这类 bug 对进程内测试结构性不可见**：进程内 ASGI/WSGI 测试没有真服务器在环、不过真 socket，运行时的改写/默认行为根本不发生，单测全绿也测不出——只有真服务器过真 socket 能抓。通用例：uvicorn 默认 `--proxy-headers` 据 `X-Forwarded-For` 改写 ASGI client 地址，任何据 peer 地址做授权的组件因此受影响。**故 (b) 命中时，纯后端 / 无 UI 改动【不豁免】**——它恰是这类 bug 的藏身处，正是"按任务形触发"曾漏掉真实 HIGH 授权绕过的那一格。

挂 host-config `smoke[]` 声明的 skill。**只有 (a)、(b) 都不命中**才可跳（Auto-Skip Log）；**(b) 命中而以"纯后端"为由跳过 = 门被按任务形误火**，属越界跳（Recipe Invariant Exception）。

> **与 challenge 门共享 (b)**：challenge/红队 subagent 触发的 **(c)** 子句与本节 **(b)** 是**同一条**「框架/服务器运行时默认」判据，二者[交叉引用](#merge-gates--challenge-before-ack--hitl-晋升门)、同增同减，任一处不得单独收紧或放宽。

## 门控矩阵（每个门一个必答时刻）

> 门的语义散在上文各节；此表把它们**收成一张单子**，每行强制回答**「这个门在哪个时刻必须被答复（跑它 or 记 skip），落在哪个机械产物里」**。**没有「必答时刻 + 机械记录」两栏的门，就是上文「通则」判定的装饰门**。执行方 policy 详义见 [`execution-policy.md`](./execution-policy.md) 四级门控。

| 门 | 必答时刻（run-or-skip 在此二选一）| policy | 机械记录（跑/跳都留痕）|
|---|---|---|---|
| trellis-check + 行为自验（双 lens）| 每次实现后 / 进收尾前 | auto | 未过双 lens 不进收尾（收尾起草的前置）|
| security-scan | 依赖变更时 / 建 MR 前 | ask-first | pass = 建 MR 前置；跳一个**有**依赖变更的 = Recipe Invariant Exception |
| 人工 smoke | **(a) 用户可见/外部接口** 或 **(b) 正确性依赖框架/服务器运行时默认**（任一命中）进收尾前 | auto-judge | (a)(b) 都不命中才跳记 Auto-Skip Log；**(b) 命中的纯后端改动不豁免**，以"纯后端"为由跳 = 越界（Recipe Invariant Exception）|
| **代码评审** | **每次 full-lane 收尾 / 进 MR 前**（fast-lane 可判 N-A）| **auto-judge（跑它 or 记 skip，必须择一并留痕；绝不静默略过）** | **landing manifest 的「谁评审」栏**（跑了→填评审者；没跑→显式写 `nobody reviewed this`）**＋** 跳过额外记 Auto-Skip Log／越界跳记 Recipe Invariant Exception |
| **challenge / 红队 subagent** | close-out；触发 **(a) full lane** 或 **(b) authn/authz/secrets/crypto/租户隔离/输入信任边界** 或 **(c) 依赖框架/服务器运行时默认**（同人工 smoke (b)）任一命中，或有晋升候选待 ack | HITL/L4（full-lane 由 L2 收尾起草时派，见 ADR-0004；fast-lane 因 (b)/(c) 触发的由 L4/human 派）| 反调 + 冲突清单落 close-out「待接受包」；候选 ack 与冲突仲裁归 owner |
| HITL 晋升（ADR/spec 落盘）| close-out | HITL（L4/human）| **landing manifest（无条件产出，含为空）** ＋ 前置 Challenge-before-ack |

**代码评审这一行是本矩阵的要点**：评审此前只出现在下面「代码评审」叙述与工具表里，流程里**没有任何一步会强制到达「评审跑了没」这个问题**——于是执行可以既不跑评审、也不记 skip，因为没有一个必答的时刻。补上这一行后，收尾**必然**撞到「跑它 or 记 skip」，而答案就落在同一个 close-out 的 landing manifest 里（评审者姓名，或显式的 `nobody reviewed this`），一眼可审。

## 代码评审（Phase 3）

- 接实例定制层声明的评审命令（如 `<code-review>` / 安全相关 `<security-review>`）+ SP `requesting-code-review`。
- 收到反馈按 SP `receiving-code-review`：**先核实再改，不橡皮图章**（技术上站不住的建议要质疑，不 performative 同意）。
- **run-or-skip 是强制的**（见上「门控矩阵」代码评审行）：full-lane 收尾**必须**要么跑评审、要么在 landing manifest 里把该项的「谁评审」写成 `nobody reviewed this` 并另记 skip；**唯一违规是既不跑也不记、让评审无声消失**。

## Landing manifest（收尾无条件产出 · HITL 晋升门的机械化替代）

HITL 晋升门（下条）本身**只靠执行方记得「落盘前先给人看」**——没有任何东西能察觉它没做（正是「通则」判定的荣誉制门）。**landing manifest 是它的机械产物替代**：不加更强的禁令，而是**把「这次落了什么盘、谁看过」从不可审计翻成一眼可见**。

- **无条件产出**：收尾时执行方**必须**产出一份 landing manifest——**包括本次没落任何盘、manifest 为空时也要显式产出**（写「本次无落盘项」）。**省略 manifest 本身才是违规**。
- **逐条一行**，每条落盘/改盘写四栏：
  1. **哪个文件、哪一节** 被改；
  2. **新增结论 vs 改写既有结论**（改写既有更需第二双眼睛）；
  3. **类别** ∈ `task 本地约定` / `跨模块 spec` / `跨切 guide` / `ADR`（越往右影响面越大、评审要求越硬）；
  4. **谁评审**——**`nobody reviewed this` 是显式允许写出的值**。
- **关键反转**：**写 `nobody reviewed this` 不是违规；省略 manifest 才是。** 这条门不禁止「没人评审就落盘」（那是 owner 看到 manifest 后自己拿捏的取舍），它只强制「有没有人评审」这件事**被写出来、可一眼看到**。把一个不可审计的荣誉制门，换成一个必答的、可被 owner/HITL 扫一眼就发现的落盘物。
- **谁看它**：full-lane 下 landing manifest 是 L2 收尾**「待接受包」**的一部分（见 [`roles-and-tiering.md`](./roles-and-tiering.md) 收尾职责分层）；L4 轻量 accept + HITL 晋升就对着这份 manifest 逐条决定翻不翻 `proposed→accepted`。凡「谁评审 = `nobody reviewed this`」且类别是 `跨切 guide`/`ADR` 的项，天然是 owner 该重点看的。
- 与 [`knowledge-closeout.md`](./knowledge-closeout.md) 的关系：知识收尾门扫「改动**连累**到的改动面外文档」，landing manifest 记「本次**主动落/改**了哪些盘、谁看过」——前者查一致性、后者记归属与评审可见性，收尾时**都产出**。

## Merge Gates + Challenge-before-ack + HITL 晋升门

- **HITL 晋升门**（知识进 `.trellis/spec/` 或 ADR）：finish 时把晋升候选列给用户评审再落盘，不自动写。**其机械产物 = 上「Landing manifest」**（无条件产出、逐条含「谁评审」栏）。
- **Challenge-before-ack（subagent 驱动，close-out 时跑）**：close-out 时由一个**独立 challenge/red-team subagent** 唱反调——既红队**这次改动本身**，又在有晋升候选时于其被 ack **前**审它。**触发钉在风险形，不只看有没有晋升候选、也不只看 Lane——(a)/(b)/(c) 任一命中即必派**（触发钉在 hazard 上的通则见 [「门的触发钉在 hazard 上」](#门的触发钉在-hazard-上通则别拿代理量当开关)）：
    - **(a) full lane**（对齐 ADR-0004：full-lane L2 收尾起草时派独立 challenge 唱反调）；
    - **(b) 变更落在 authn / authz / secrets / crypto / 租户隔离 / 输入信任边界**——**即便满足全部 fast-lane 条件**（自包含、单模块、无依赖变更、无需 ADR、无晋升候选），只要动这些高风险面，challenge 就**不因 fast lane 而豁免**（Lane 定文档集大小，不定风险）；
    - **(c) 正确性依赖框架 / 服务器运行时默认**（ASGI/WSGI scope、proxy headers、超时、连接复用、信号处理、中间件顺序）——**与「人工 smoke gate」的 (b) 是同一条判据**，见 [人工 smoke gate](#人工-smoke-gate)，两门[交叉引用](#人工-smoke-gate)同增同减，防一处收紧另一处漂回任务形。
    另有晋升候选（ADR/spec/mem）待 ack 时，无论上面是否命中都要在 ack **前**跑。**谁派**（对齐 `roles-and-tiering.md` 收尾职责分层 + ADR-0004）：full-lane 由 **L2 收尾起草**时派（对自己交付唱反调）；**fast-lane 因 (b)/(c) 被触发的**、fast-lane-直做的晋升候选、以及**跨任务裁决**由 L4/human 派。**独立性**：subagent 与派方共享先验，靠**对抗立场**补（prompt 明令「尽力反驳、默认候选不成立」）——立场独立优先于上下文独立。subagent **只挑战 + 列冲突**；最终 ack（`proposed→accepted`）与冲突仲裁归 owner（L4/human），不由 subagent 或起草方自裁。**至少**做两件事：
  1. **查重**：把每个晋升候选与既有 `.trellis/spec/` + ADR + methodology + 已有 mem 逐条比对，确认**不存在重复**（重复则删、不晋升）；结构性事实用 codegraph 核（代码可派生的不进 mem）。
  2. **查矛盾**：候选是否与既有 spec/ADR/mem **冲突**（同一主题不同结论、被推翻的旧决策未标 superseded）；**有矛盾则明确列出冲突双方 + 供 user 决定**（保留哪个 / 合并 / 标 superseded），不由子代理或主会话自行裁。
  其余仍查：过度晋升？可逆选择当永久？验收未达标？被否的更强方案？子代理**只挑战**，最终 owner（HITL 时=用户）看着反调 + 冲突清单再拍。
- **顺序**：security-scan（依赖变更时）pass → 进 MR；HITL 晋升在 archive 后（RepoMem.merge 语义）。
- 一个变更未过 trellis-check + 行为自验，不进收尾；依赖变更未过 security-scan，不合 release。

## 已知上游 Trellis 缺口（门存在但无执行者）

把「通则」那条测试（谁、在哪个时刻会注意到没做？）套到几处**写在纸上、但机械执行者在 stock Trellis 里缺席**的门。**这些是上游 Trellis 的执行者缺失，不是 Arborist 会去改的东西**（任务脚本属 stock Trellis，不在本发布层 overlay 内——overlay 只叠 guide/纪律与少量脚本）。此处**登记缺口 + 现有缓解**，并注明若上游补齐可如何机械闭合：

| 门（写在纸上）| 上游执行者缺口 | Arborist 侧缓解（overlay 能给的机械产物）| 上游若补齐 → 机械闭合 |
|---|---|---|---|
| **worktree 隔离**（roles 指引：L2/L3 动代码前先建 worktree）| 任务记录有 `worktree_path` 字段，但**无 setter 子命令**去填、任务激活步也不要求它非空——字段存在却无从被填 = 不是门 | [worktree 步](./roles-and-tiering.md#worktree-步与纪律l2l3-默认在-worktree-工作)：建完 worktree 立刻跑 `scripts/harness_worktree_link.sh`（手动、幂等的 link 脚本），把 harness 目录 symlink 回主树、恢复护栏 | 上游补 `worktree_path` setter + 让激活步在「须隔离的角色」值为空时拒绝/告警 → 隔离从「靠记得」变成激活时必然撞到的一步 |
| **context-manifest 非空**（约定：任务开工前 manifest 至少一条真实条目）| 存在 `validate` 子命令，但**任务激活步从不调用它**——只打印「上下文将注入」，不校验 | landing manifest 纪律（收尾侧的无条件落盘物，见上）＋ 收尾知识一致性门；开工侧目前仍靠执行方自觉 | 上游让激活步真正调用已存在的 `validate` 子命令 → 「manifest 非空」从荣誉制翻成激活即校验 |

> 判读：以上两处目前对「通则」测试**答不出执行者**。overlay 半能做的已就位（手动 link 脚本 + landing manifest 纪律）；**真正的机械闭合在上游**——一旦 stock Trellis 补齐 setter / 让激活调用 `validate`，这两条门即可无声闭合，无需 Arborist 再叠纪律。曾在某 adopting repo 观察到：字段全空、无隔离的直改主树与并发提交混在同一 `git status` 里——正是「字段存在但无 setter」这类装饰门的典型后果。
