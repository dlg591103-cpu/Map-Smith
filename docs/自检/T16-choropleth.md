# T16 自检记录：choropleth 渲染

| 项目 | 内容 |
| --- | --- |
| 任务 | T16 choropleth 渲染：分级设色 + 分级断点图例 |
| SPEC | [../Spec/V0.1-专题制图智能体.md](../Spec/V0.1-专题制图智能体.md)（第 6 节 T16 行、第 7 节验收） |
| 事实依据 | [../facts/07-制图规范与审查.md](../facts/07-制图规范与审查.md) 第 2、6、8、10 条；[../facts/05-MapSpec与工具契约.md](../facts/05-MapSpec与工具契约.md) 工具 5（`render(spec) -> {png, pdf}`） |
| 分支 | `feat/cartographer` |
| 基线 | `main` @ `6e96f6b`（含 T01–T11），叠在 T15 提交 `2d803e2` 之上 |
| 执行者 | CodeArts（AI 会话）。开发与自检为同一执行者；独立验收、Git 合并尚未进行 |
| 日期 | 2026-11-09 |

## 1. 交付物

- `src/mapsmith/render/choropleth.py`：choropleth 渲染。`class_index` 分级归并、`assign_colors` 设色、`render_choropleth` 出图并组合 T15 版式要素。
- `src/tests/test_choropleth.py`：16 个用例。
- `src/mapsmith/render/layout.py`：`draw_legend` / `apply_layout` 增加可选的 `legend_anchor`（默认行为不变，仍为右下角），供主体占满图幅时把图例放到图框外。

## 2. 完成判定核对

| 判定 | 结果 | 证据 |
| --- | --- | --- |
| 分级设色 | 通过 | `assign_colors` 按 `spec.classification.breaks` 归并到 0..n-1 级，取 `palette_colors(spec, n)` 对应颜色；`test_assign_colors_follows_palette_order`、`test_render_colors_each_polygon_by_its_class` 逐面核对填充色 |
| 分级断点图例 | 通过 | 图例标签与设色共用 `legend_labels` / `palette_colors`，同一份断点生成的文字与色块逐级对应；`test_render_legend_breaks_match_classification` 同时核对标签文本、数量与色块颜色 |
| 分级口径一致 | 通过 | 区间按「≤ 上界」判定（`40` 归第一级、`40.1` 归第二级），与图例 `≤ 40 / 40–50` 的写法同一口径；`test_class_index_uses_inclusive_upper_bound` |
| 缺失值 | 通过 | 数值缺失的面用中性灰 `#d9d9d9` 填充、不占用配色方案，并计入 `missing_count` 与 `summary`；`test_assign_colors_marks_missing_grey`、`test_render_marks_missing_polygon_and_counts_it`。说明文字仍只读 `spec.notes`，渲染层不代填 |
| 按 `spec.crs` 出图 | 通过 | 图层 CRS 与 `spec.crs` 不同则 `to_crs` 重投影，范围由 `spec.extent.bbox` 变换得到；`test_render_reprojects_layer_to_spec_crs` 用 `EPSG:4548` 验证坐标量级从度变为米 |
| 版式要素组合 | 通过 | 直接复用 T15 `apply_layout`（图名/图例/比例尺/指北针/四类注记），`report.layout.drawn` 记录实际画出项 |
| 单测 | 通过 | `test_choropleth.py` 16 passed；全量 `164 passed, 2 warnings in 7.17s` |

## 3. 关键设计

- **渲染层不聚合数据**：面要素与「逐面数值」由调用方准备，站点→面的归属与聚合属于 T14 `analyze` 的 join。`render_choropleth` 只接受已带数值列的 GeoDataFrame，`field` 缺省取 `kind="choropleth"` 图层的 `field`。
- **设色与图例同源**：`assign_colors` 与 `draw_legend` 都走 `palette_colors` / `legend_labels`，不存在两套断点口径；改断点只需改 `spec`。
- **越界值并入末级**：`quantile` / `jenks` 的末级上界即样本最大值，个别超界值并入末级而不是整幅判缺失，避免一张图全灰。
- **宽高比修正**：投影坐标系 `aspect=1`；地理坐标系（默认 `EPSG:4490`）取 `1/cos(中心纬度)`，否则中纬度区域会被横向拉宽约 20%。
- **版式跟随图框**：`ax.set_axis_off()` + `set_aspect` 会让地图在图幅内上下留白，出图前把底部注记挪到图框正下方，并以 `bbox_inches="tight"` 裁掉多余空白。
- **图例外置**：主体占满图幅时图例压在面要素上，故 choropleth 传 `legend_anchor=(1.02, 1.0)` 放到图框右侧；`test_render_keeps_legend_outside_map_body` 按窗口坐标断言图例在图框右侧。

## 4. 已知项与未做

- **示意图数值**：本任务的验收图 `mapsmith_t16_demo.png` 用的是覆盖五个等级 + 1 个缺失的构造数值（面要素取 `demo_data/boundaries/320300_full.json` 的真实边界），用于核对设色与图例；不是真实 PM2.5 观测值。
- **未接 `render(spec)` 总入口**：目前只提供 `render_choropleth(spec, gdf, ...)`，Tool 5 的 `render(spec) -> {png, pdf}` 需要与 T17/T18 的图种分派一起做，PDF 输出未做。
- **未接 `qa_check`**：断点与配色语义的合规判定仍由审图员（T19+）承担。
- **可变字体 weight 警告**：沿用 T15 的 `NotoSansSC.ttf`，`findfont: Failed to find font weight normal ... now using 100` 仍会出现，只影响粗细不影响字形。
- 未合并回 `main`、未执行独立验收。

## 5. 证据

```
$ python -m pytest src/tests/test_choropleth.py -q
................                                          [100%]
16 passed

$ python -m pytest src/tests -q
164 passed, 2 warnings in 7.17s
```

渲染结果：`C:\Users\王仰之\AppData\Local\Temp\mapsmith_t16_demo.png`（本地临时文件，不入库）。目视核对：五个等级颜色与图例逐级对应、缺失面为灰色、比例尺 50 km、指北针在右上、图例外置未遮挡面要素、中文无乱码。
