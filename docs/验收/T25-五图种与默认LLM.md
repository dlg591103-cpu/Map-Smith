# T25 独立验收记录

| 项目 | 内容 |
| --- | --- |
| 验收对象 | `feat/t25-five-map-types` @ `e095ff9`（`e095ff960910c02366fc8de0b6007a63e7339b6f`，分支最新提交） |
| 验收范围 | T25 全部交付：五图种（choropleth / point / idw / buffer / overlay）、IDW 通过样例、默认 Ollama 与未启动提示、T14 统计表 join 缺口 |
| 验收依据 | [T25 SPEC](../Spec/T25-五图种与默认LLM.md) 第 3、5 节；[facts/02](../facts/02-范围与边界.md)、[facts/05](../facts/05-MapSpec与工具契约.md)、[facts/07](../facts/07-制图规范与审查.md)、[facts/08](../facts/08-交付形态.md)；[工程规则](../工程规则.md) 第 2–6、9 条 |
| 开发自检 | [T25 自检](../自检/T25-五图种与默认LLM.md)（仅作线索，不作为验收结论） |
| 基线 | `main` @ `812fdbb` |
| 环境 | Windows 11 + PowerShell 5.1；Python 3.12（`E:\Map Smith\.venv`）；本机 Ollama 端口在验收会话沙箱内不可达（见第 5 节） |
| 日期 | 2026-11-16 |
| 执行者 | CodeArts（独立验收会话）。开发与自检为另一执行过程；本次验收由用户指定本会话执行，合并与推送需另行授权 |

## 1. 验收方法

1. `git rev-parse HEAD` 固定为 `e095ff9`，验收期间不更换提交。
2. 核对工作区、基线与改动范围，检查是否越出 SPEC 第 2 节。
3. 表单五图种逐案实跑，读取 `status`、`MapSpec` 校验结果、渲染报告、审查结论与 PNG。
4. buffer 距离、分级均值、IDW 覆盖度独立复算，不直接引用自检数值。
5. overlay 用验收侧新建的徐州境内面文件复跑 `clip`，另跑 `intersection` 表单与「主体在境外」失败分支。
6. T14 缺口按「无坐标 CSV → `DataLayer.table` → `join_table` → choropleth PNG」重新执行。
7. Ollama 未启动提示按「指向未监听端口」实测；真实模型链路与 `.env` 外部 API 切换在本次环境无法执行，如实列为未验证。
8. 全量 pytest 在验收会话沙箱被执行，失败用例单独定位原因；不把环境失败当作代码通过或失败。

## 2. 提交与范围核对

| 检查 | 结果 |
| --- | --- |
| `HEAD` | `e095ff960910c02366fc8de0b6007a63e7339b6f` |
| 分支相对 `origin/main` | `git rev-list --count HEAD..origin/main` = 0 |
| 工作区 | 仅未跟踪 `mapsmith-v0.1.0.zip`（自检已注明，不纳入本次交付） |
| 基线至交付 | `812fdbb..e095ff9`，11 个提交，38 个文件，`+1316 / -87` |
| 改动范围 | `src/mapsmith/`（flow、render、config、llm、io、tools、demo_data）、`src/tests/`、`web/src/`、`web/dist/`、`web/e2e/`、`docs/自检/`、`docs/Spec/`，与 SPEC 第 2 节一致 |
| 越界检查 | 未发现 `docs/facts/` 改动；未发现无关功能改动 |
| 自检记录的交付提交 | 仅写「见 `feat/t25-five-map-types` 最新提交」，未写提交 hash；本次以用户指定的 `e095ff9` 固定 |

## 3. 逐项结果（SPEC 第 5 节）

| # | 验收条件 | 判定 | 证据 |
| --- | --- | --- | --- |
| 1 | 五种图种在表单与一句话模式各跑通一次，`MapSpec` 校验通过 | **部分通过** | 表单 5/5 `rendered`，`MapSpec(**spec)` 均通过（第 4.1 节）；一句话模式需真实 Ollama，本次环境不可达，未复现 |
| 2 | 五图种出图中文标题/图例/注记无乱码，版式要素齐全 | **部分通过** | 已逐张查看 point / choropleth / idw / buffer / overlay 五张 PNG：标题、图例、比例尺、指北针、底部注记齐全，`μg/m³`、`≤`、`≥` 正常；但 overlay 局部主体图幅异常、buffer 与 choropleth 注记与实际图种矛盾（第 6.2、6.3 节） |
| 3 | buffer 距离与投影坐标一致（与已知距离比对） | 通过 | `EPSG:4548`，10 个缓冲面等效半径均 `4.996 km`，相对 5 km 偏差 `0.08%`，与自检一致 |
| 4 | buffer 分级值为缓冲区内站点指标均值，图例注明半径与参与站点数 | 通过 | 10 个缓冲面、9 个含站点；逐面 `within` 复算 `mismatches=[]`；图例三行「分位数分级，4 级 / 缓冲距离 5 km / 9/10 面含站点」；渲染报告「9 个面已分级设色，缺失 1 个」 |
| 5 | overlay/clip 结果可渲染，图层数正确，沿用主体字段分级 | 通过 | clip 10→10、intersection 10→34 且 `buffer_value` 保留；表单 clip 2→2 `rendered`；intersection 表单 10 面 `rendered`，字段 `PM2_5_24h`，分级 3 级；主体在境外时报「裁剪后为空：与 徐州市行政边界 无交集」 |
| 6 | IDW 样例满足 `n ≥ 10`、`cover ≥ 50%`，断网可演示 | 通过 | 独立复算：有效站 20/21；凸包 4255.2 km²，研究区 7400.0 km²，覆盖度 **53.4%**；全程 `online=False`，出图 `rendered` |
| 7 | 无 key 时默认 Ollama 可用；Ollama 未启动提示明确；`.env` 填 key 可切换外部 API | **不通过** | 未启动提示已实测，文案正确（第 4.4 节）；默认 Ollama「可用」需真实模型调用，本次环境不可达，未复现；`.env` 外部 API 切换自检即标注「尚未实测」，本次亦未验证 |
| 8 | T14 缺口：上传统计表 → join → choropleth 端到端跑通 | 通过 | 无坐标 CSV 10 行 → `DataLayer.table` 保留 → `join_table` 10 面全部匹配（值 45–60）→ choropleth PNG `314,836 B`，与自检字节数一致 |
| 9 | 全量 pytest 通过（新增用例覆盖上述分支） | 通过（拆分验证） | 沙箱全量：`309 passed, 12 failed`，12 项全部为 `test_server.py`；单独执行该文件 `12 passed`，其余 `309 passed`，合计 321 个用例全部通过；失败原因见第 5 节 |

## 4. 关键实测数据

### 4.1 表单五图种

| 图种 | 状态 | `map_type` | 字段 | PNG 字节 | 渲染报告 | 审查 fail |
| --- | --- | --- | --- | --- | --- | --- |
| point | rendered | point | `PM2_5_24h` | 295,785 | 5 个站点映射气泡面积 | 0 |
| choropleth | rendered | choropleth | `PM2_5_24h` | 330,937 | 4 个面已分级设色，缺失 6 个 | 0 |
| idw | rendered | idw | `PM2_5_24h` | 177,830 | 20 个有效站点，凸包 4213.3 km² | 0 |
| buffer | rendered | buffer | `buffer_value` | 175,792 | 9 个面已分级设色，缺失 1 个 | 0 |
| overlay（clip） | rendered | overlay | `PM2_5_24h` | 140,148 | 2 个面已分级设色 | 0 |
| overlay（intersection） | rendered | overlay | `PM2_5_24h` | 337,754 | 10 个面已分级设色 | 0 |

五案 `MapSpec(**spec)` 均校验通过。审查只出现 R09/R10 `warn`，无 `fail`。

### 4.2 buffer

```text
measurement_crs      EPSG:4548
radius_km_min/max    4.996 / 4.996
distance_requested   5.0 km
max_deviation        0.08%
buffer_count         10
buffers_with_sites   9
mismatches           []
render               9 个面已分级设色，缺失 1 个
```

### 4.3 overlay / IDW / T14

```text
clip           10 → 10（crs EPSG:4326，kind admin）
intersection   10 → 34（buffer_value 保留）
outside        failed：裁剪后为空：与 徐州市行政边界 无交集
IDW            n=20/21，hull 4255.2 km²，study 7400.0 km²，cover 53.4%
T14            10 行 table → 10/10 匹配 → PNG 314,836 B
```

### 4.4 Ollama 未启动提示

将 `MAPSMITH_LLM_BASE_URL` 指向未监听的 `127.0.0.1:11435/ollama/v1`，调用 `chat_json`，返回：

```text
本地模型未启动：请确认 Ollama 正在运行（命令行执行 ollama serve，或启动 Ollama 应用），
默认模型 qwen2.5:3b；也可在项目根 `.env` 配置 MAPSMITH_LLM_BASE_URL /
MAPSMITH_LLM_API_KEY / MAPSMITH_LLM_MODEL 接入外部 API。
```

文案符合 SPEC 第 3 节第 5 条。验收会话的沙箱拦截本机连接，实际错误为 `OSError: [WinError 10051]`，与真实「端口未监听」路径同为 `requests.RequestException`，提示分支一致；真实 Ollama 可用性未验证。

## 5. 测试结果与环境说明

| 运行方式 | 结果 |
| --- | --- |
| 验收会话（沙箱）全量 | `12 failed, 309 passed, 6 warnings in 31.10s` |
| 仅 `test_server.py` | `12 passed, 1 warning in 4.67s` |
| 全量排除 `test_server.py` | `309 passed, 3 warnings in 29.12s` |

失败抛出点在 CPython `socket._fallback_socketpair` 的 `connect`，用例 stderr 含 `Sandbox Network Error: hit restricted [127.0.0.1:23635]`；单独运行同一文件全部通过，判定为验收沙箱拦截本机临时端口，与被测代码无关（与 T23 验收记录第 8 节同源）。因此本次未在用户本机终端复跑全量 321 项，该数字为拆分执行结果，记录在此不作推定。

## 6. 发现的问题

### 6.1 `.env` 外部 API 切换未实测（阻塞）

SPEC 第 5 节第 7 条包含「`.env` 填 key 可切换到外部 API」，自检第 2 节自评「部分通过」并在第 4 节注明「仍未实测」。按工程规则第 6 条，未验证项不得推定通过，该项构成验收阻塞。

### 6.2 overlay 局部主体图幅只覆盖主体自身（缺陷）

`flow._bbox_for()` 对非 choropleth 图种取 `loaded["admin"]` 的 bbox。overlay 上传局部主体时，`admin` 是上传面，第二图层在 `loaded["overlay_base"]`，图幅因此收缩到主体小面：

- 验收输入的 2 个约 5 km × 5 km 主体面，出图比例尺为 **2 km**（正常应为徐州全域约 50 km）；
- 徐州市行政边界（第二图层）落在图幅外，叠加关系不可见；
- 指北针落在右上角面色块内，版式不合格。

影响 SPEC 第 3 节第 2 条「提供第二图层，按 intersection / clip 出图」的可读性，以及第 5 节第 2 条「版式要素齐全」。建议 `overlay` 取第二图层 bbox，或取主体与第二图层的并集。

### 6.3 buffer / choropleth 底部注记与实际图种矛盾（缺陷）

表单 `buffer`、`choropleth` 的 `notes` 无条件并入数据体检结论「降级为点图 / 气泡图 + 城市面底色，不做插值」，但实际渲染报告分别为「9 个面已分级设色，缺失 1 个」「4 个面已分级设色，缺失 6 个」，图中也是面状分级设色，并非点图。用户显式选择图种时该注记误导，审查 R01–R10 未捕获。建议仅在 `decision` 真正决定渲染图种时写入该结论，或改写为数据体检结论而非渲染结论。

### 6.4 自检证据内部不一致（文档）

自检第 2 节第 9 条写 `321 passed, 4 warnings in 29.90s`，第 5.1 节证据写 `318 passed, 4 warnings in 29.10s`。本次实际用例总数为 321（309 + 12），第 5.1 节证据应为旧结果未同步。

### 6.5 交付提交未固定（文档）

自检表「交付提交」只写「见 `feat/t25-five-map-types` 最新提交」，未写 hash；分支后续若再提交，自检与验收对象无法对应。本次按用户指定的 `e095ff9` 固定。

## 7. 未验证范围

1. 一句话模式五图种的真实链路（需本机 Ollama，验收沙箱不可达）。
2. 默认 Ollama「无 key 可用」的正向路径。
3. `.env` 外部 API 切换。
4. 用户本机终端的全量 pytest（本次为沙箱拆分执行）。

以上四项均未推定通过。

## 8. 结论

**验收不通过。** 表单五图种、buffer 距离与均值、IDW 覆盖、T14 join、overlay 数据处理与渲染、Ollama 未启动提示均已实测并符合 SPEC；但 SPEC 第 5 节第 7 条的 `.env` 外部 API 切换未完成，第 1 条的一句话模式未能在本次环境复现，且存在 overlay 图幅范围与 buffer/choropleth 注记两处用户可见缺陷。按工程规则第 3、4 条，需由开发方修复并产生新提交、重新记录自检后再次验收；验收期间未更换提交，`e095ff9` 保持为本次固定对象。

建议修复顺序：

1. `flow._bbox_for()` 的 overlay 分支改用第二图层/区域边界。
2. `flow` 组装 `notes` 时，图种已由用户显式指定则不再并入「降级为点图」结论。
3. 补测 `.env` 外部 API 切换与真实 Ollama 一句话五图种，回填自检证据。
4. 统一自检中的 pytest 数字并写明交付提交 hash。

## 9. 证据与清理

- 验收脚本：`out/verify/t25_independent_acceptance_check.py`、`out/verify/t25_overlay_intersection_check.py`（临时文件，不入库）。
- 出图证据：`out/verify/accept/web/` 下六个请求目录的 PNG。
- 失败证据：`out/verify/tb.txt`（沙箱下 `test_server.py` 失败堆栈，含 `Sandbox Network Error`）。
- 本次未产生仓库代码改动；验收记录为本文件。