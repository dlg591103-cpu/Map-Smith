# T03 自检记录：MapSpec 模型与校验

| 项目 | 内容 |
| --- | --- |
| 任务 | T03 `spec.py`：MapSpec 模型 + pydantic 校验 |
| SPEC | [../Spec/V0.1-专题制图智能体.md](../Spec/V0.1-专题制图智能体.md)（第 3、6 节） |
| 事实依据 | [../facts/05-MapSpec与工具契约.md](../facts/05-MapSpec与工具契约.md)、[../facts/02-范围与边界.md](../facts/02-范围与边界.md)、[../facts/07-制图规范与审查.md](../facts/07-制图规范与审查.md) |
| 分支 | `feat/core` |
| 基线 | `main` @ `15af002`；本任务开始时 `feat/core` @ `c93bd9a` |
| 执行者 | CodeArts（AI 会话）。开发与自检为同一执行者；独立验收、Git 合并尚未进行 |
| 日期 | 2026-11-07 |

## 1. 交付物

- `src/mapsmith/spec.py`：`MapSpec`、`Extent`、`LayerStyle`、`Layer`、`Classification`、`Palette`、`Annotation`、`Layout`，以及 `from_json` / `to_json`。
- `src/tests/test_spec.py`：27 个用例（含参数化展开）。

## 2. 完成判定核对

| 判定 | 结果 | 证据 |
| --- | --- | --- |
| 非法 spec 被拒绝 | 通过 | 缺必填字段、`map_type` 非法、`bbox` 顺序错误、`adcode` 非 6 位、空 `layers`、重复 id、`idw/choropleth` 缺 `field`、图种与图层不匹配、`breaks` 数量不等于 `n`、`breaks` 非递增、`custom` 中间项为 null、非 `custom` 出现 null、`n` 越界、`dpi<=0`、`size<=0`、`crs` 非法、彩虹色阶、多余字段，均抛 `ValidationError` |
| 单测通过 | 通过 | `34 passed in 1.39s`（含 T02 的 7 个用例） |

## 3. 关键设计

- `model_config = ConfigDict(extra="forbid", frozen=True)`：拒绝 LLM 自行添加字段，spec 不可原地修改，修改即重新校验。
- `classification.n` 允许 2–9；上界 9 是实现约束，不是产品事实，T12 实现分级时如与 `mapclassify` 冲突可调整。
- `classification.breaks` 数量必须等于 `n`；`custom` 的末项允许为 `null`，表示 AQI「>300」这类无上界，其余项必须严格递增。
- `method` 白名单：`quantile` / `jenks` / `equal_interval` / `custom`。第四种 `custom` 经用户 2026-11-07 确认，用于 AQI 国标六级等固定断点；不自动改写断点，全部落在第一级时如实出图并记录说明。
- `crs` 用 pyproj 校验合法性；输出白名单（CGCS2000 / 3°GK / WGS84 UTM / Web Mercator）留待 T04 `projection.py`。
- `map_type` 必须存在对应 kind 的数据图层；`idw`、`choropleth` 图层必须提供 `field`。
- 明显彩虹色阶（`jet`、`rainbow`、`hsv`、`gist_rainbow`、`nipy_spectral`）在模型层直接拒绝，依据 `facts/07` 第 8 条；其余配色语义仍由审图员判定。
- 图名是否包含「区域 + 指标 + 时间」属自然语言判定，本模型不解析，留给审图员第 1 条。

## 4. 未做

- 未实现 T04 的投影白名单与自动选带。
- 未实现 T12 的 `classify` 计算，本任务只定义 `breaks` 的结构契约。
- 未接入 Agent 提示词与渲染层。
- 未推送分支、未合并回 `main`、未执行独立验收。