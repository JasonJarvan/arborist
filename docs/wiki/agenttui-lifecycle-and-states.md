# AgentTUI 生命周期与状态机(阐释页)

> 规范原文(canonical):[`overlay/spec/guides/agenttui-registry.md`](../../overlay/spec/guides/agenttui-registry.md) §3–§4。本页是**阐释层**:按生命周期时间线走一遍状态如何流转,便于理解;字段与规则以规范原文为准。

## 状态集一览

| 类别 | 值 | 谁产生 |
|---|---|---|
| **声明态**(写进 `runtime.json.state`) | `active` / `stopped` | agent 自写,仅在「确定为真」的可信触点 |
| **保留枚举** | `idle` | MVP 无人写;为未来平台 hook 机械写入预留 |
| **有效态**(不落盘,读表时现算) | active / idle(推定)/ stopped·stale(推定) | 读表方按派生规则计算 |

核心原则:**声明态不说谎**——agent 只在确定时写(启动确实 active、干净收尾确实 stopped);一切「它可能死了」的判断推给读者按探针现算,且明文标注为**推定**。

## 生命周期时间线

```
 启动           工作中          空闲           干净收尾        崩溃/关终端
  │               │              │                │               │
  ▼               ▼              ▼                ▼               ▼
自登记整条leaf   心跳刷        (无任何写入,      自写            (永远没有写入)
state=active    last_seen     agent不在运行)   state=stopped
generation=1     │              │                │               │
  │               │              │                │               │
读者视角:      active         mtime>15min      stopped         mtime>24h
 active        (mtime新鲜)    → idle(推定)     (确知)          → stopped/stale(推定)
                                                                → gardener 保守GC条目
        ┌────────────────────────────────────────────┐
        │ 同名重启:runtime.json 换新 session_id/     │
        │ session_file,generation+1,state回active;  │
        │ spec.json 不动                              │
        └────────────────────────────────────────────┘
```

## 逐节点说明

| 生命周期节点 | agent 写什么 | 读表方看到的有效态 | 备注 |
|---|---|---|---|
| **启动** | 自建整条 leaf:`spec.json` + `runtime.json`(`state:"active"`, `generation:1`) | active | 自登记为主路径,覆盖无 handoff 的角色(rootorc/gardener);handoff 信只供 role/task/description 素材,派活方物理上写不了 session_id |
| **工作中** | 可信触点(每轮收尾/阶段切换)顺带刷 `last_seen`;state 不动 | active | 探针(`session_file` mtime)逐轮前进,比 last_seen 更细 |
| **空闲** | **什么都写不了**(agent 不在运行,结构性事实) | mtime 超 idle 阈值(建议 15min)→ **idle(推定)** | `idle` 由读者派生,不是声明 |
| **干净收尾** | 自写 `state:"stopped"` | stopped | 唯一**非推定**的负状态 |
| **崩溃/关终端** | 永远没有写入 | mtime 超 stale 阈值(建议 24h)→ **stopped/stale(推定)** | 探针局限:落盘是 open-append-close,空闲无进程持 fd ⇒「idle 但终端开着」与「已关终端」不可区分,故一律推定 |
| **同名重启** | 更新 `runtime.json`(新 session_id / session_file,`generation`+1,state 回 active);`spec.json` 不动 | active | generation 区分代际,防把旧代探针当新代 |
| **条目回收** | gardener GC 超 stale 阈值的**条目**(非会话) | (条目消失) | 保守原则:条目可由本人随时重建,误删无害;但只 GC 超阈值者,避免把活同伴抹出发现视野 |

## 有效态派生规则(读表方按序判定)

1. 声明 `stopped` → **stopped**
2. `session_file` mtime 距今 < idle 阈值 → **active**
3. ≥ idle 阈值 且 < stale 阈值 → **idle(推定)**
4. ≥ stale 阈值,或 `session_file` 不存在 → **stopped/stale(推定,GC 候选)**

阈值均为建议默认值,按项目节奏可调;`session_file` 不可读时退用 `last_seen`(较粗:只反映可信触点)。

## 为什么这样设计(一段话)

无守护进程是本注册表的硬边界:没有常驻观测者,状态就不可能被「维护」,只能被「派生」。于是把 CCB 式的 desired/reconcile 对账退化为「声明 + 读时现算」:写侧只写不会说谎的两个时刻,读侧承担全部不确定性并明示推定。代价是 idle/stopped 边界模糊;收益是零运行时依赖、崩溃自愈(重启 generation+1 即覆盖)、误删无害。
