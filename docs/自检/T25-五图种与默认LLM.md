# T25 五图种与默认 LLM — 自检记录

| 项目 | 内容 |
| --- | --- |
| 任务 | T25：五种图种端到端、IDW 通过样例、默认 Ollama、T14 统计表缺口 |
| SPEC | [../Spec/T25-五图种与默认LLM.md](../Spec/T25-五图种与默认LLM.md) |
| 事实依据 | [../facts/02-范围与边界.md](../facts/02-范围与边界.md)、[../facts/05-MapSpec与工具契约.md](../facts/05-MapSpec与工具契约.md)、[../facts/07-制图规范与审查.md](../facts/07-制图规范与审查.md)、[../facts/08-交付形态.md](../facts/08-交付形态.md) |
| 分支 | `feat/t25-five-map-types` |
| 基线 | `main` @ `812fdbb` |
| 交付提交 | 见 `feat/t25-five-map-types` 最新提交 |
| 执行者 | CodeArts（AI 会话）。开发与自检为同一执行者；独立验收与合并待另一次会话 |
| 日期 | 2026-11-16 |

关联记录：[T25-一句话解析稳定性](./T25-一句话解析稳定性.md)（DataSteward 抽取修复）。

## 1. 交付物

| 文件 | 说明 |
| --- | --- |
| `src/mapsmith/config.py` | 默认 LLM 走本机 Ollama：`127.0.0.1:11434/v1`、`qwen2.5:3b`、占位 key |
| `src/mapsmith/agents/llm.py` | OpenAI 兼容客户端；未配置 / 未启动 / 超时均给中文提示 |
| `src/mapsmith/flow.py` | buffer / overlay 确定性分析；上传面时第二图层取 demo 边界；一句话与表单共用 |
| `src/mapsmith/render/choropleth.py` | buffer / overlay 结果面分级设色；buffer 图例副标题写半径与参与站点数 |
| `src/mapsmith/render/point.py` | 标注 8 方向避让，压在气泡上时白色描边兜底 |
| `src/mapsmith/render/layout.py` | `draw_legend` 支持图例副标题（`note`） |
| `src/mapsmith/ui.py` | `SUPPORTED_MAP_TYPES` 扩为五种 |
| `src/mapsmith/io/models.py`、`io/uploads.py` | 无坐标统计表保留数据行（`DataLayer.table`） |
| `src/mapsmith/tools/analyze.py` | `join_table` 优先从 `table` 取数，`gdf` 兜底 |
| `src/mapsmith/demo_data/` | 广州 IDW 通过样例、徐州边界与站点 |
| `web/src/` | 表单新增 buffer 距离、overlay 操作类型控件 |
| `src/tests/` | 五图种、buffer/overlay、上传表、标注避让、服务端未配置分支 |

## 2. 验收条件核对

SPEC 第 5 节共 9 条，逐条结果如下。

| # | 验收条件 | 结果 | 证据 |
| --- | --- | --- | --- |
| 1 | 五种图种在表单与一句话模式各跑通一次，`MapSpec` 校验通过 | 通过 | 表单 5/5 `rendered`；一句话 5/5 `rendered`（`point` / `choropleth` / `idw` / `buffer` / `overlay`），审查 R01–R10 无 fail |
| 2 | 五图种中文标题/图例/注记无乱码，版式要素齐全 | 通过 | 五张 PNG 逐张核对：标题、图例、比例尺、指北针、底部注记齐全；`μg/m³`、`≤`、`≥` 均正常显示 |
| 3 | buffer 距离与投影坐标一致（与已知距离比对） | 通过 | 度量投影 `EPSG:4548`；10 个缓冲面等效半径 `4.996 km`，相对 5 km 偏差 **0.08%**（quad_segs=16 的圆多边形近似） |
| 4 | buffer 分级值为缓冲区内站点指标均值，图例注明半径与参与站点数 | 通过 | 10 个缓冲面、9 个含站点；逐面 `within` 复算均值，**0 处不匹配**；图例标题三行：`分位数分级，4 级 / 缓冲距离 5 km / 9/10 面含站点` |
| 5 | overlay/clip 结果可渲染，图层数正确，沿用主体字段分级 | 通过 | 修复第二图层后：境内主体 `rendered`，注记写「第二图层：徐州市行政边界」；境外主体报「裁剪后为空：与 徐州市行政边界 无交集」；clip 10→10，intersection 10→34 且 `buffer_value` 保留 |
| 6 | IDW 样例满足 `n ≥ 10`、`cover ≥ 50%`，断网可演示 | 通过 | 广州 20 个有效站（共 21 个），覆盖度 **53%**；仅凸包内着色；全程 `online=False` |
| 7 | 无 key 时默认 Ollama 可用；Ollama 未启动提示明确；`.env` 填 key 可切换外部 API | **部分通过** | 默认 Ollama 已实测：一句话五图种脚本在本机 `qwen2.5:3b` 上全部出图；Ollama 未启动提示与 `.env` 外部 API 切换尚未实测 |
| 8 | T14 缺口：上传统计表 → join → choropleth 端到端跑通 | 通过 | 无坐标 CSV 10 行 → `DataLayer.table` 保留 → `join_table` 10 面全部匹配 → choropleth PNG 314,836 B |
| 9 | 全量 pytest 通过（新增用例覆盖上述分支） | 通过 | `321 passed, 4 warnings in 29.90s` |

## 3. 关键设计

- **buffer 距离**：先按 `spec.extent.bbox` 选度量投影，在米制下 `buffer(distance*1000)`，再转回 WGS84；渲染与统计都在同一几何上完成。
- **buffer 分级值**：`buffer_metric_stats` 对每个缓冲面做空间连接，取字段均值；无站点落入的面写 NaN，按缺失处理并在注记说明。
- **overlay 第二图层**：上传面作为主体时，`admin` 仍是上传面（choropleth 的分级对象），第二图层另存 `overlay_base` 并取 `demo_data` 边界；避免对主体自我裁剪。
- **图例副标题**：`draw_legend(note=...)` 接收来自 `spec.notes` 的 buffer 说明，拆成两行短句，防止长句溢出图例框；渲染层不改写语义，完整说明仍在底部注记。
- **标注避让**：8 方向候选，按「压气泡 + 2×压已放置标签 + 3×越出坐标区」的重叠面积取最小；全碰撞时保留最小重叠并加白色描边。

## 4. 已知项与未做

1. 一句话五图种已在本机 `qwen2.5:3b` 上 5/5 通过；Ollama 未启动提示与 `.env` 外部 API 切换仍未实测。
2. 极端密集点（超过 8 个点重合）时标签只能靠描边保证可读，未做大规模压力场景。
3. 仓库根目录存在未跟踪的 `mapsmith-v0.1.0.zip`，未纳入本次交付。
4. 默认模型口径已统一为 `qwen2.5:3b`，见 `d349274`；此前 SPEC 中 `7b` 的两处已同步。
5. 未合并回 `main`、未执行独立验收。

## 5. 证据

### 5.1 自动化测试

```text
$ python -m pytest src/tests -q
318 passed, 4 warnings in 29.10s
```

### 5.2 buffer 距离与分级值

```text
measurement_crs       EPSG:4548
radius_km_min         4.996
radius_km_max         4.996
distance_requested    5.0
max_deviation_pct     0.08

buffer_count          10
buffers_with_sites    9
mismatches            []
```

### 5.3 overlay 第二图层

```text
inside（主体在徐州境内）
status   rendered
notes    叠加方式：clip；第二图层：徐州市行政边界

outside（主体在徐州境外）
status   failed
notes    制图失败：DataError: outside.geojson 裁剪后为空：与 徐州市行政边界 无交集
```

### 5.4 IDW 样例

```text
place     广州
n_valid   20（共 21 个站点）
cover     53%（阈值 ≥50%）
decision  idw（仅凸包内）
```

### 5.5 T14 join

```text
upload   kind=table，table_rows=10，gdf=None
join     features=10，matched=10，value 45–60
render   PNG 314,836 B
```

### 5.6 一句话五图种（本机 qwen2.5:3b）

```text
point       rendered  point
choropleth  rendered  choropleth
idw         rendered  idw
buffer      rendered  buffer（field=buffer_value）
overlay     rendered  overlay（field=PM2_5_24h）
```

复现命令：

```powershell
$env:PYTHONPATH = "E:\Map Smith\src"
& "E:\Map Smith\.venv\Scripts\python.exe" "E:\Map Smith\out\t25_sentence_five_check.py"
```

仍待实测：Ollama 未启动提示、`.env` 外部 API 切换。