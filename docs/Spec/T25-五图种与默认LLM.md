# T25 SPEC — 五图种补齐、IDW 样例与默认 LLM

> 状态：**已确认（2026-11-16）**。本 SPEC 只写本次要做什么，不复制产品设定；关键口径已在会话中逐项确认，按 [../工程规则.md](../工程规则.md) 从 `main` 固定提交建任务分支开发。
> 基线：`main` @ `812fdbb`（V0.1 已合并 T01–T23；Release `v0.1.0`）。
> 背景：T24 端到端验收前置缺口——SPEC V0.1 第 7 节「五个图种各跑通一次」在界面只覆盖 3 种；`demo_data/` 无 IDW 通过样例（T05–T11 验收遗留）；一句话模式无 LLM 配置（`llm_configured=False`）。

## 1. 目标

1. 让 facts/02 定义的五类图种在界面与一句话模式**端到端可跑**：`choropleth`、`point`（含气泡）、`idw`、`buffer`、`overlay/clip`。
2. 补一份 **IDW 通过分支**的真实站点样例（`n ≥ 10` 且凸包覆盖率 `≥ 50%`），并注明来源与日期。
3. 默认 LLM 走本机 **Ollama**（`qwen2.5:7b`），同时支持 `.env` 接入 DeepSeek / OpenAI 等外部 API。
4. 顺带修复 T14 契约缺口：无坐标统计表的数据行不再丢弃，`analyze.join` 可由真实上传链路跑通。

## 2. 修改范围

| 文件/目录 | 改动 |
| --- | --- |
| `src/mapsmith/spec.py` | 已含 `MapType = Literal[..., "buffer", "overlay"]`，预计不改；若渲染需要的字段（如 `buffer_km`、`analysis_op`）缺失，最小新增并补校验 |
| `src/mapsmith/ui.py` | `SUPPORTED_MAP_TYPES` 扩为五种；`build_spec` 支持 buffer/overlay 字段；`render_frame` 增加两种图种分派 |
| `src/mapsmith/flow.py` | 表单与一句话组装：buffer 需 `buffer_km`；overlay 需第二图层；Agent 决策 `analyze=buffer/overlay` 时不再被忽略 |
| `src/mapsmith/render/` | 新增 buffer/overlay 渲染：结果面图层按分级设色（分级依据见第 3 节），复用 T15 版式要素 |
| `src/mapsmith/io/models.py`、`io/uploads.py` | T14 缺口：`DataLayer` 增加表格数据字段，无坐标 CSV 保存数据行 |
| `src/mapsmith/tools/analyze.py` | `join_table` 优先从新字段取数，`gdf` 兜底 |
| `src/mapsmith/config.py` | LLM 默认值：`llm_base_url=http://127.0.0.1:11434/v1`、`llm_model=qwen2.5:7b`、`llm_api_key="ollama"`（占位，Ollama 不校验） |
| `src/mapsmith/agents/llm.py` | 回落顺序：环境变量/`.env` → 预置默认（Ollama）→ 中文「未配置」提示；探测 `127.0.0.1:11434` 是否可用 |
| `web/src/` | 表单新增：图种选项 `buffer` / `overlay`，缓冲距离输入，第二图层上传/选择；文案去掉「buffer / overlay 尚未实现」 |
| `src/mapsmith/demo_data/` | 新增 IDW 通过样例（区域与字段依实测阈值确定），`README` 注明来源、日期、站数、覆盖率 |
| `src/tests/` | 新增 buffer/overlay 组装与渲染、table 数据行、LLM 默认回落用例 |

不改动：`docs/facts/` 已确认设定（如需修订另议）；T22 的 SSE/上传契约保持不变。

## 3. 预期行为

1. 表单选 `buffer`：输入缓冲距离（km，默认 5），基于点图层或 demo 站点生成缓冲区面，按缓冲区内站点指标的统计值分级设色，图例注明半径、参与站点数与分级方法。
2. 表单选 `overlay`：提供第二图层（上传或 `demo_data` 边界，二选一），按 `intersection` / `clip` 出图，沿用主体图层字段分级设色，图例注明操作类型与字段。
3. 一句话模式：Agent 决策 `analyze=buffer|overlay` 时按对应动作出图；缺参数时反问，不猜默认值（沿用 V0.1 第 4 节第 1 条）。
4. 五种图种的 `MapSpec` 均通过校验；非法组合返回中文错误，不返回空白页。
5. 无 `.env` key 时默认调用本机 Ollama；Ollama 未运行时给出中文提示「本地模型未启动」，并提示可填 `.env` 接入外部 API。
6. 上传无坐标 CSV 后，`analyze.join` 能真实跑通，可产出用于 choropleth 的面图层。
7. IDW 样例在断网环境下可完成 `n ≥ 10`、`cover ≥ 50%` 的通过分支演示。

### 3.1 buffer 分级依据（已确认 2026-11-16）

每个缓冲区取**落在该缓冲区内站点的指标均值**（如 PM2.5 浓度均值），按分位数 / 自然断点分级；图例注明缓冲半径、参与站点数与分级方法。缓冲区内无站点时该缓冲区不参与分级，并在 `notes` 与审查报告说明。选定后在 `MapSpec` 的 buffer 图层写入该字段与分级结果，渲染走 choropleth 同一套分级与图例逻辑。

## 4. 依赖

- 本机 Ollama（安装在 **E 盘**：程序 `E:\Ollama`，模型目录 `OLLAMA_MODELS=E:\ollama\models`）与 `qwen2.5:3b` 模型（约 1.9 GB）；外部 API 为可选项。
- 真实站点数据（quotsoft `china_sites_YYYYMMDD.csv` + 站点列表）由用户下载后提供；行政区边界可由 `resolve_place` 在线获取，或使用 `demo_data` 边界。
- 不引入新的 Python 依赖（Ollama 走 OpenAI 兼容 HTTP）。

## 5. 验收条件

- [ ] 五种图种在表单与一句话模式各跑通一次，`MapSpec` 校验通过
- [ ] 五种图种出图中文标题/图例/注记无乱码，版式要素齐全
- [ ] buffer 距离与投影坐标一致（与已知距离比对）
- [ ] buffer 分级值为缓冲区内站点指标均值，图例注明半径与参与站点数
- [ ] overlay/clip 结果可渲染，图层数正确，沿用主体字段分级
- [ ] IDW 样例满足 `n ≥ 10`、`cover ≥ 50%`，断网可演示
- [ ] 无 key 时默认 Ollama 可用；Ollama 未启动时提示明确；`.env` 填 key 可切换到外部 API
- [ ] T14 缺口：上传统计表 → join → choropleth 端到端跑通
- [ ] 全量 pytest 通过（新增用例覆盖上述分支）

## 6. 风险与未决

| 项 | 说明 |
| --- | --- |
| 覆盖阈值 | 真实国控站点集中于城区，徐州凸包覆盖约 2%；样例区域需按实测选择（北京/江苏/全国），本 SPEC 不预设区域 |
| buffer 分级依据 | 已定：缓冲区内站点指标均值（第 3.1 节） |
| Ollama 安装位置 | 已定：程序装在 `E:\Ollama`，模型目录 `OLLAMA_MODELS=E:\ollama\models`，模型 `qwen2.5:3b` |
| 任务命名 | 本 SPEC 编号 `T25`，是否纳入 V0.1 任务表需用户确认 |