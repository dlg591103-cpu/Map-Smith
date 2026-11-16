# PR：版式要素避让与版式判据（T15–T22 修复补充）

> 本文件是 `feat/cartographer` → `main` 的合并说明，供开 PR 时正文使用。
> 只做记录，不改变任何规则；规则正文仍在 [docs/工程规则.md](工程规则.md)。

## 1. 这个 PR 实际包含什么

**不是新功能，是修复。** T12–T18 与 T22 的代码已经通过 PR #14、#17 等以 squash 方式合入 `main`，
本次分支与 `main` 的差异只剩版式修复：

| 文件 | 变化 | 作用 |
| --- | --- | --- |
| `src/mapsmith/render/checks.py` | +105（新增） | 三个像素级版式判据：`frame_content_ratio`、`labels_overlap`、`element_overlaps_content` |
| `src/tests/test_checks.py` | +140（新增） | 判据单元测试 |
| `src/mapsmith/render/layout.py` | +229/−20 | 指北针候选位置避让、比例尺上移避让、标签贪心避让 |
| `src/mapsmith/render/point.py` | +17 | 标注放置改用避让函数，指北针用点图候选位置 |
| `src/mapsmith/render/idw.py` | +6 | 标注放置改用避让函数 |
| `src/mapsmith/render/extent.py` | +30 | 取景范围 aspect-aware 修正 |
| `docs/自检/T22-界面-第一段.md` | +38 | 三轮判据演进的修订记录 |

合计 **7 个文件，+545 / −20**。

## 2. 为什么需要这个 PR

`main` 当前版本的版式问题（已逐张打开出图核实）：

| 图种 | 问题 | 根因 |
| --- | --- | --- |
| 点图 | 站点挤在图中央一小团，标注糊成一片 | 取景沿用行政区 bbox，未考虑内容分布 |
| 点图 | 指北针压在气泡上 | 指北针固定右上角，点图图例在框外时落入图内 |
| 点图 / IDW | 比例尺与站名重叠 | 版式要素无避让，各自按固定位置绘制 |

抽查 `main` 的 `layout.py`：避让相关代码 **0 处**；本分支 **22 处**。

## 3. 验证证据

```
$ python -m pytest src/tests -q
268 passed, 10 warnings in 35.50s

$ python -m pytest src/tests/test_checks.py src/tests/test_layout.py src/tests/test_point.py -q
47 passed, 8 warnings in 6.43s
```

出图对比（徐州 PM2.5 点图，本地 `out/point_demo.png`）：

| 项 | 修复前 | 修复后 |
| --- | --- | --- |
| 站点外接框 / 取景宽 | 13.38% | 83.33% |
| 标注两两重叠 | 有 | 无 |
| 指北针压气泡 | 有 | 无 |
| 比例尺压站名 | 有 | 无 |

## 4. 已知局限（不影响合并，需要知悉）

1. **点图不适用 `frame_content_ratio`**：点图的气泡像素占比天然很低（实测 0.0157），
   该判据面向面图（choropleth / IDW）。点图应改用「站点外接框占图幅对应方向的比例」，
   待后续任务调整判据口径。
2. **IDW 取景仍偏宽**：`frame_content_ratio` = 0.2544 < 0.45，已确认取景过宽，
   但改动会牵动栅格裁剪与凸包掩码，未在本 PR 内处理。
3. **choropleth 取景值** 0.3869，同样低于 0.45，待评估是否与图例外置占位有关。
4. 可变字体 `NotoSansSC.ttf` 会触发 `findfont ... weight normal` 警告，只影响粗细，
   不影响字形与中文显示（T15 已记录）。

## 5. 合入说明

- 分支已与 `main` 同步：`git merge origin/main` 完成于 `b5a1889`，
  合并时 5 处 add/add 冲突统一取分支版，已核对分支版为 `main` 版的严格超集，
  **相对 `main` 零删除**（`loop.py`、`qa_check.py`、`agents/reviewer.py`、`kb/`、三份 prompt 均存活）。
- 合并后全量 `268 passed`，无 skip / xfail 掩盖。
- 未改动共享文件：`spec.py`、`projection.py`、`loop.py`、`requirements*` 均未触碰。
