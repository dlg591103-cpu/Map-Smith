# T12 自检记录：classify 分级断点

| 项目 | 内容 |
| --- | --- |
| 任务 | T12 `classify`：四种分级方法（自然断点 / 分位数 / 等间距 / 自定义） |
| SPEC | [../Spec/V0.1-专题制图智能体.md](../Spec/V0.1-专题制图智能体.md)（第 6 节 T12、第 7 节验收） |
| 事实依据 | [../facts/05-MapSpec与工具契约.md](../facts/05-MapSpec与工具契约.md) 工具 4；[../facts/07-制图规范与审查.md](../facts/07-制图规范与审查.md) 第 6、8 条 |
| 分支 | `feat/cartographer` |
| 基线 | `main` @ `6e96f6b` |
| 执行者 | CodeArts（AI 会话）。开发与自检为同一执行者；独立验收、Git 合并尚未进行 |
| 日期 | 2026-11-09 |

## 1. 交付物

- `src/mapsmith/tools/classify.py`：`classify(values, method, n, *, custom_breaks=None) -> ClassificationResult`，覆盖 `quantile` / `jenks` / `equal_interval` / `custom`。
- `src/tests/test_classify.py`：17 个用例。

## 2. 完成判定核对

| 判定 | 结果 | 证据 |
| --- | --- | --- |
| 四种方法均返回 breaks 与 labels | 通过 | 每种方法 `len(breaks)=len(labels)=n`，断点严格递增、末项为最大值 |
| 自定义（AQI 国标六级） | 通过 | `custom_breaks=[50,100,150,200,300,None]` → 6 级，末级标签 `>300` |
| 非法输入被拒绝 | 通过 | 未知方法、`n` 越界、断点非递增、数据不足分级、空值/非数值均抛 `DataError` |
| 结果可填 MapSpec | 通过 | `Classification(method="quantile", n=4, breaks=...)` 校验通过 |
| 单测 | 通过 | `test_classify.py` 17 passed；全量 `113 passed in 6.33s` |

## 3. 关键设计

- 契约签名来自 facts/05 工具 4；返回值额外带 `counts` 与 `summary`（facts/05「返回契约」要求回灌 LLM）。
- `quantile` / `jenks` / `equal_interval` 交给 `mapclassify`（`Quantiles` / `FisherJenks` / `EqualInterval`）计算各级上界。
  - 注：mapclassify 2.11 无 `Jenks` 类，自然断点对应 `FisherJenks`。
- `custom` 由调用方给固定断点，不做计算；末项 `None` 表示无上界（AQI「>300」）。
- `n` 限定 2–9，与 `spec.Classification` 一致；断点必须严格递增。
- 数据不足以分 N 级（重复断点或 mapclassify 内部降 k）时报 `DataError` 并说明原因，不静默产出错误分级。

## 4. 未做

- 未接入 Agent 提示词、渲染层与 `loop.py`。
- 未做配色映射（配色由渲染层按 `palette.scheme` 处理，见 T15–T18）。
- 未推送分支、未合并回 `main`、未执行独立验收。