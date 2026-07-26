<!-- 把本块粘进你项目的 .trellis/workflow.md（紧跟 "## Core Principles" 之后）。
     <占位> 处替换成你项目的实际值。workflow.md 不在 trellis update 的 hash 清单 → 本块 update-safe。

     ⚠️ 注入子集边界（务必读）：SessionStart hook 只注入 workflow.md 的【一个范围】——
     从 `## Phase Index` 标题到 `## Phase 1: Plan`（见 session-start.py `_build_workflow_overview`
     → `_extract_range("Phase Index", "Phase 1: Plan")`）。UserPromptSubmit 的每轮 breadcrumb
     只发 Phase Index 内的 `[workflow-state:*]` 块。**本定制层贴在 Core Principles 之后 → 在两个注入范围之外
     → 没有任何 session 会自动加载它。** 写在这里的规则读着完美、被版本管理、被别的 guide 引用，
     却与「根本不生效的规则」无法区分，直到出事。
     ⇒ 任何【必须到达每个 session】的规则：正文可留本层，但必须在【被注入范围内】(Phase Index 段) 或对应 step 的
        `get_context.py --mode phase --step X.Y` 详情里，留一行 `- [local]` 入口（见文末「注入范围入口」块）。
        放置正确性【别肉眼估】，用文末验证片段（import hook → 打印 overview → grep 关键字断言命中）机械核对。
     原理与判据见 guides/generalization-boundary.md「注入子集边界」。 -->

## <project> 定制层（本地覆盖 · 读 workflow.md 时以本节为准）

> ⚠️ **本段【不被 SessionStart 注入】、也不进每轮 breadcrumb**（它在 `## Phase Index`→`## Phase 1` 注入范围之外）。
> 任何必须到达每个 session 的规则，需在【被注入范围内】(Phase Index 段) 或对应 step 详情里另留一行 `- [local]` 入口——见文末「注入范围入口」。
> 由 Arborist overlay 引入。详规见 `.trellis/spec/guides/`。workflow.md update-safe。

### 术语消歧
- Trellis 的 "spec"（`.trellis/spec/`）= **编码规范/约定**（≈ RepoMem persist/memory），非行为契约。
- 单次变更的**行为契约** = 该 task `prd.md` 验收标准；关键能力的**累积契约摘要**落 `.trellis/spec/<pkg>/`。

### 角色/任务分层 L1–L4（多 session 共享本 harness）
**L4 RootOrche**（与 human 对话、编排整仓、分解、HITL 把关；无强制力）→ **L3 SubOrche**（管一批 L2、派活、集成）→ **L2 Impler**（实现一个 L2、TDD loop、回报）→ **L1 subagent**（auto-spawn 的 implement/check/research）。L3=parent task、L2=child task；与 Lane 正交。级间 sendbox 交办。详见 `guides/roles-and-tiering.md`。
**跨 ATUI 硬边界（别抢活）**：别人 lane 的通报 = FYI，默认「知道了」不接手；只有 `handoff` 信 / human 指派才转移归属。看见别人 lane 的问题 → 只为周知告诉归属方 / human，**别接手，也别包装成问题上传**（两向都是弹飞）。判据 / 范例见 `guides/roles-and-tiering.md`「ATUI 归属边界」。

### Trellis = 骨架，Superpowers = 工具箱
各步"怎么做"调 SP skill（brainstorming / writing-plans / TDD / subagent-driven-development / verification / code-review），产物落 `.work_context/superpowers/`。Trellis 原生 skill 与 SP 重叠时**择一**（见 guides/roles-and-tiering + workflow 里各步标注），别双跑。

### Git / 提交 / 分支 / MR —— defer 你项目的既有约定
走 `<你的 git/MR 规则，如 .claude/rules/* + /commit + /pr>`。硬线：**未经用户明说不提交、不 push**。（示例：功能分支从 main 切、MR 进当期 `release/YYYYMMDD`。）Trellis 不自造 git 流程（Phase 3.4 遵此）。

### Lane 与 TDD 逃生口
Lane 在 task `prd.md` 顶部声明 `Lane: fast|full`（full 若：动依赖 / 跨子树 / 公共契约 / 需 ADR）。TDD 默认开；**fast-lane 琐碎改动可免 red-test-first**，记 skip-log。

### research-first 前置
规划**从 research-first + RepoMem.read 起**（读 ADR/spec），**先于** brainstorm。符号/调用/影响面优先 **codegraph** MCP，grep 兜底。

### 知识收尾门（可选 · Phase 3.4 commit 后、`/finish-work` 前）
交付后按 `guides/knowledge-closeout.md` §1 分级判跑：full lane / milestone 收口跑「改动面外的全仓知识一致性」扫描；fast lane 跳过记 skip-log。**由收尾方自跑**（full lane 即 L2 Impler），不回弹 rootorc。

### 详规指针
角色/分层/交办：`guides/roles-and-tiering.md` · `guides/sendbox.md` · `guides/dashboard.md`；门控：`guides/execution-policy.md`；记忆/边界：`guides/repomem-doc-boundary.md`；验证/门：`guides/verification-and-gates.md`；HS 15-step 落点：`guides/pipeline-mapping.md`；方法论：`guides/methodology/`；注册表：`guides/agenttui-registry.md`（AgentTUI 同伴发现）· `guides/tool-registry.md`（可选能力发现）；知识收尾：`guides/knowledge-closeout.md`（交付后全仓一致性门）。

### 注入范围入口（`[local]` · 【贴进 Phase Index，不要留在本层】）

> 上面各条规则的正文留在本定制层即可（版本化、被 guide 引用），但**本层不被注入**。凡「必须到达每个 session」的规则，
> 需在 workflow.md 的**被注入范围**（`## Phase Index` 段，`## Phase 1: Plan` 之前）留一行 `- [local]` 指针。
> **格式硬约束**：必须是 `- [local] …` 的**列表项**形式。`_strip_breadcrumb_tag_blocks` 会把**行首**的 `[xxx]`
> 当 tag 剥掉——裸行 `[local] …` 的 `[local]` 会被吃掉；`- [local] …`（前缀 `- `）则整行保留。加完用文末验证片段确认命中。

**adopter 动作**：在 `.trellis/workflow.md` 的 Phase Index 段（`### Guardrails` 之后、`### Loading Step Detail` 之前）新增一小节，逐字贴入：

```markdown
### 本地覆盖入口 [local]（每轮 session 需知；正文见定制层 / 对应 guide）
- [local] 跨 ATUI 硬边界（别抢活）：别人 lane 的通报=FYI，默认「知道了」，不接手、也别包装成问题上传；只 `handoff` 信 / human 指派才转移归属。判据/范例见 `guides/roles-and-tiering.md`「ATUI 归属边界」。
- [local] 知识收尾门：交付后（Phase 3.4 commit 后、`/finish-work` 前）按 lane 分级判跑「改动面外全仓知识一致性」扫描，**收尾方自跑**（full lane 即 L2 Impler），不回弹 rootorc。分级/矩阵见 `guides/knowledge-closeout.md`。
```

> 这两条正文分别在本层「角色/任务分层」「知识收尾门」小节；此处只放**注入范围内的一行入口**，使其真能到达每个 session。
> 需给每个 session 加载的新本地规则，都照此再补一行 `- [local]`。

<!-- 另需在 Phase 1 加 1.0b research-first 步、把 [workflow-state:planning]/Active Task Routing 的 Load `trellis-brainstorm` 改指 SP brainstorming、Phase 2.2 加验证拓扑、Phase 3.3 加 ADR 分流+HITL 晋升门、Phase 3.4 defer git、Phase 3.5 加 WIMTB。逐条见 ADOPT.md。 -->

<!-- ── 注入放置验证片段（Option 3）────────────────────────────────────
     加完 `- [local]` 入口后，别肉眼估——跑本片段：import SessionStart hook 模块 →
     打印它实际构建的 overview → grep 关键字断言命中。0 命中 = 没进注入范围，白加了。

python3 - <<'PY'
import importlib.util
from pathlib import Path
REPO = Path(".")  # 你的仓根
spec = importlib.util.spec_from_file_location("sshook", REPO/".claude/hooks/session-start.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
overview = m._build_workflow_overview(REPO/".trellis/workflow.md")
must = ["跨 ATUI", "知识收尾"]        # 换成你要保证到达 session 的关键字
missing = [k for k in must if k not in overview]
print("overview chars:", len(overview))
for k in must:
    print(f"  {k!r:12} 命中? {k in overview}")
assert not missing, f"未注入（不在 Phase Index 范围）: {missing} —— 把 `- [local]` 入口贴进 Phase Index 段"
print("OK: 全部关键字都在被注入范围内")
PY
   ──────────────────────────────────────────────────────────────── -->
