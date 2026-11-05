# MapSpec 与工具契约

> 状态：已确认（2026-11-05）。本文件负责决策产物与工具接口；字段命名在 SPEC 阶段定稿。

## MapSpec：唯一的决策产物

```json
{
  "title": "徐州市 PM2.5 24 小时均值分布图（2026-11-01）",
  "map_type": "idw | choropleth | point | buffer | overlay",
  "extent": { "adcode": "320300", "bbox": [116.2, 34.1, 118.6, 34.9] },
  "layers": [
    { "id": "base", "kind": "admin",
      "style": { "fill": "#f7f7f7", "edge": "#999999" } },
    { "id": "data", "kind": "idw", "field": "PM2_5_24h",
      "source": "quotsoft_20261101" }
  ],
  "classification": {
    "method": "quantile",
    "n": 5,
    "breaks": [35, 55, 75, 115, 150]
  },
  "palette": { "scheme": "YlOrRd", "reverse": false },
  "annotation": { "label_field": "站点名", "show": true },
  "layout": {
    "size": [10, 8],
    "dpi": 300,
    "legend": true,
    "scale_bar": true,
    "north_arrow": true,
    "source_note": true,
    "crs_note": true
  },
  "data_source_note": "数据来源：全国城市空气质量实时发布平台（quotsoft.net）",
  "crs": "EPSG:4490",
  "notes": ["2 个站点缺测，已按空间邻近插补"]
}
```

要点：

- spec 是 LLM 与渲染层之间唯一的接口。
- 用户说「图例改中文」「标题加日期」「配色深一点」，都只是改 spec 字段后重渲染。
- spec 也是答辩证据：可以指着它说明哪部分是模型决策、哪部分是确定性代码。
- 坐标与投影按 [02-范围与边界.md](02-范围与边界.md) 的投影边界处理：输出默认 CGCS2000；度量由内部自动选带，选带结果需回显并记入元数据。

## 六个工具

| 编号 | 工具名 | 签名 | 作用 |
| --- | --- | --- | --- |
| 1 | `resolve_place` | `(name) -> {adcode, bbox}` | 地名 → 编码 + 范围 |
| 2 | `load_layer` | `(kind, place, time?) -> Layer` | 加载数据 |
| 3 | `analyze` | `(op, params) -> Layer` | buffer / clip / overlay / join |
| 4 | `classify` | `(values, method, n) -> {breaks, labels}` | 分级断点 |
| 5 | `render` | `(spec) -> {png, pdf}` | 出图 |
| 6 | `qa_check` | `(spec, png) -> {passed, issues[]}` | 规范自检 |

## 返回契约

每个工具都必须返回自然语言 `summary` 回灌给 LLM，而不只是返回数据对象。

示例——`load_layer` 的返回：

```
count: 9
summary: "徐州共 9 个国控站点，PM2.5_24h 有效值 9 个，最高 118、最低 32，
          数据完整度 100%。站点数偏少，不建议插值成面。"
```

原因：LLM 读不懂 GeoDataFrame。没有 summary，Agent 既无法判断数据够不够用，也无法在返工时说明理由。

## 相关文档

- Agent 如何使用这些工具：[04-三Agent与协作协议.md](04-三Agent与协作协议.md)
- 审查规则：[07-制图规范与审查.md](07-制图规范与审查.md)