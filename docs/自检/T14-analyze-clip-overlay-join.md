# T14 自检记录：analyze 裁剪 / 叠加 / 属性关联

| 项目 | 内容 |
| --- | --- |
| 任务 | T14 `analyze`：clip / overlay / join，裁剪与叠加结果可渲染 |
| SPEC | [../Spec/V0.1-专题制图智能体.md](../Spec/V0.1-专题制图智能体.md)（第 6 节 T14、第 7 节验收） |
| 事实依据 | [../facts/05-MapSpec与工具契约.md](../facts/05-MapSpec与工具契约.md) 工具 3（buffer / clip / overlay / join）；[../facts/02-范围与边界.md](../facts/02-范围与边界.md) 图种 4 |
| 分支 | `feat/cartographer` |
| 基线 | `main` @ `6e96f6b`（含 T01–T11） |
| 执行者 | CodeArts（AI 会话）。开发与自检为同一执行者；独立验收、Git 合并尚未进行 |
| 日期 | 2026-11-09 |

## 1. 交付物

- `src/mapsmith/tools/analyze.py`：在 T13 `buffer` 基础上补齐 `clip_layer` / `overlay_layer` / `join_table`，并扩展 `analyze(layer, op, params)` 分发。
- `src/tests/test_analyze.py`：由 8 个用例扩到 21 个用例。
- `docs/自检/T14-契约缺口报告.md`：`io/models.py` 的 `table` 图层缺数据行问题（发团队）。

## 2. 完成判定核对

| 判定 | 结果 | 证据 |
| --- | --- | --- |
| clip 结果可渲染 | 通过 | `gpd.clip` 裁剪后保留边界内要素，转回 `EPSG:4326`，`kind` 按几何判定（点→point） |
| overlay 结果可渲染 | 通过 | `gpd.overlay` 支持 5 种 how，结果转回 `EPSG:4326`，`kind` 按几何判定 |
| join 关联结果可渲染 | 通过 | 统计表按 key 关联边界，产出带统计字段的面图层（kind=admin），坐标系 WGS84 |
| 第二图层经 params 传 DataLayer | 通过 | `clip` 的 `by`、`overlay` 的 `other`、`join` 的 `to` 均为 DataLayer，非 DataLayer 明确报错 |
| 非法输入被拒绝 | 通过 | 缺参数、未知 op、未知 how、缺关联键列、无数据行、无交集均抛 `DataError` |
| 单测 | 通过 | `test_analyze.py` 21 passed；全量 `134 passed in 7.74s` |

## 3. 关键设计

- 签名保持 T13 的 `analyze(layer, op, params)`，第一参数始终是被操作图层；第二图层经 params 传入，
  避免改动已定型的 `buffer` 调用与已有测试。
- `clip` / `overlay` 均为拓扑运算，不涉及米制距离单位，因此直接在统一 WGS84 下做，不引入度量投影
  （`buffer` 才需要 `choose_measurement_crs`，见 T13）。两图层先对齐到 WGS84 再运算。
- `join` 第一参数是统计表，数据行须保存在 `gdf` 字段（正确契约前提）；`to` 是边界，`key` 支持
  字符串（同名列）或 `(表键, 边界键)` 二元组（不同名列）。
  - 左连接保留全部边界要素，未匹配的统计字段为 `NaN`，`meta` 记 `matched_count` / `unmatched_count`。
  - 关联键之外的所有列视为统计字段，写入 `meta["value_fields"]`，供分级设色取用。
- 输出 `kind` 统一按输出几何判定（`_kind_from_geometry`），与 `io/uploads.py` 约定一致；
  `join` 固定输出面（`admin`）。

## 4. 未做

- 未实现 `join` 的空值补全策略（未匹配边界留 `NaN`，由渲染层按 `notes` 说明）。
- 未接入 Agent、渲染层与 `loop.py`。
- 未修改 `io/`（归数据管家）：`table` 图层缺数据行的契约缺口另见
  [T14-契约缺口报告.md](T14-契约缺口报告.md)。
- 未推送分支、未合并回 `main`、未执行独立验收。