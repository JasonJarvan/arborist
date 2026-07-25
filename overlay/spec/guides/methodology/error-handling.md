# T7 · 错误处理与可观测

> 源：`broad-except-in-init-conflates-failure-modes`（剥离具体传输/wire 细节；对 Go error wrapping 同样成立）。

## 核心

- **别把失败模式压成一个**：init / 外部连接路径用 `except Exception`（Go: 裸 `if err != nil` 单一兜底）+ 单一 fallback，会把"签名漂移 / 配置改名 / 依赖缺失 / 真外部不可达"压成同一错误码，误导排障。
- **正解**：窄异常元组 → typed re-raise（Go: `errors.Is`/`errors.As` + `fmt.Errorf("...: %w", err)` 分类包装）；兜底 except 也必须打**可区分的 `reason`**，让 observability 分得清哪类失败。

## 落点
`.trellis/spec/guides` 错误处理规范 / `.trellis/spec/backend`（Go error wrapping）。
