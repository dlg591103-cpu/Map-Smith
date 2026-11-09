"""T12 classify：分级断点计算。

规则来源：
- docs/facts/05-MapSpec与工具契约.md 工具 4：`classify(values, method, n) -> {breaks, labels}`。
- docs/Spec/V0.1-专题制图智能体.md 第 1 节：分级由 mapclassify 计算，LLM 只做决策、不做计算。
- docs/facts/07-制图规范与审查.md 第 6 条：分级方法注明（自然断点 / 分位数 / 等间距 + 级数）。

四种方法：
- `quantile`（分位数）、`jenks`（自然断点）、`equal_interval`（等间距）：交给 mapclassify 计算各级上界。
- `custom`（自定义固定断点，如 AQI 国标六级）：由调用方给断点，不做计算；末项可为 None 表示无上界。

返回 `breaks`（各级上界，长度 = n）与 `labels`（分级标签），外加自然语言 `summary` 回灌 LLM
（docs/facts/05「返回契约」）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal, Sequence

import mapclassify
import numpy as np

from ..io.models import DataError

Method = Literal["quantile", "jenks", "equal_interval", "custom"]

METHOD_LABELS = {
    "quantile": "分位数",
    "jenks": "自然断点",
    "equal_interval": "等间距",
    "custom": "自定义",
}

# 与 spec.Classification 的 n 约束保持一致（2–9）。
MIN_CLASSES = 2
MAX_CLASSES = 9

_CLASSIFIERS = {
    "quantile": mapclassify.Quantiles,
    "jenks": mapclassify.FisherJenks,
    "equal_interval": mapclassify.EqualInterval,
}


@dataclass(frozen=True)
class ClassificationResult:
    """一次分级结果；`breaks` 为各级上界（末项可为 None），`labels` 与之等长。"""

    method: Method
    n: int
    breaks: tuple[float | None, ...]
    labels: tuple[str, ...]
    counts: tuple[int, ...]
    summary: str

    def to_dict(self) -> dict[str, object]:
        return {
            "method": self.method,
            "n": self.n,
            "breaks": list(self.breaks),
            "labels": list(self.labels),
            "counts": list(self.counts),
            "summary": self.summary,
        }


def _fmt(value: float) -> str:
    if float(value) == int(value):
        return str(int(value))
    return f"{value:g}"


def _clean(values: Iterable[float]) -> np.ndarray:
    try:
        arr = np.asarray(list(values), dtype=float)
    except (TypeError, ValueError) as exc:
        raise DataError(f"分级值必须全部为数值：{exc}") from exc
    arr = arr[~np.isnan(arr)]
    if arr.size == 0:
        raise DataError("分级需要至少一个有效数值，当前全为空")
    return arr


def _make_labels(breaks: Sequence[float | None], vmin: float) -> tuple[str, ...]:
    labels: list[str] = []
    lower = vmin
    for upper in breaks:
        if upper is None:
            labels.append(f">{_fmt(lower)}")
        else:
            labels.append(f"{_fmt(lower)}–{_fmt(upper)}")
            lower = upper
    return tuple(labels)


def _counts_for_breaks(arr: np.ndarray, breaks: Sequence[float | None]) -> tuple[int, ...]:
    counts: list[int] = []
    lower = -np.inf
    for upper in breaks:
        hi = np.inf if upper is None else float(upper)
        counts.append(int(np.sum((arr > lower) & (arr <= hi))))
        lower = hi
    return tuple(counts)


def _validate_custom(breaks: Sequence[float | None], n: int) -> tuple[float | None, ...]:
    if len(breaks) != n:
        raise DataError(f"custom 断点数量必须等于 n={n}，实际为 {len(breaks)}")
    result = [None if item is None else float(item) for item in breaks]
    if any(item is None for item in result[:-1]):
        raise DataError("custom 断点只允许最后一项为 None（表示无上界）")
    numeric = [item for item in result if item is not None]
    if any(a >= b for a, b in zip(numeric, numeric[1:])):
        raise DataError("custom 断点必须严格递增")
    return tuple(result)


def _summary(
    method: Method,
    n: int,
    breaks: Sequence[float | None],
    counts: Sequence[int],
    vmin: float,
    vmax: float,
) -> str:
    breaks_text = "、".join("∞" if item is None else _fmt(item) for item in breaks)
    counts_text = "、".join(str(count) for count in counts)
    return (
        f"{METHOD_LABELS[method]}分级（{n} 级）：断点 {breaks_text}；"
        f"各级数量 {counts_text}；数值范围 {_fmt(vmin)}–{_fmt(vmax)}。"
    )


def classify(
    values: Iterable[float],
    method: Method,
    n: int,
    *,
    custom_breaks: Sequence[float | None] | None = None,
) -> ClassificationResult:
    """对一组数值做分级，返回断点、标签与 summary。

    - `quantile` / `jenks` / `equal_interval`：`n` 为级数（2–9），由 mapclassify 计算各级上界。
    - `custom`：必须给 `custom_breaks`（长度 = n，末项可为 None 表示无上界），不做计算。
    """
    if method not in METHOD_LABELS:
        raise DataError(f"未知分级方法 {method!r}；可用：{'、'.join(METHOD_LABELS)}")
    if not (MIN_CLASSES <= n <= MAX_CLASSES):
        raise DataError(f"分级数 n 必须在 {MIN_CLASSES}–{MAX_CLASSES} 之间，实际为 {n}")

    arr = _clean(values)
    vmin, vmax = float(arr.min()), float(arr.max())

    if method == "custom":
        if custom_breaks is None:
            raise DataError("custom 分级必须提供 custom_breaks")
        breaks = _validate_custom(custom_breaks, n)
        counts = _counts_for_breaks(arr, breaks)
    else:
        classifier_cls = _CLASSIFIERS[method]
        try:
            classifier = classifier_cls(arr, k=n)
        except Exception as exc:  # mapclassify 在数据不足时会抛各类异常
            raise DataError(
                f"{METHOD_LABELS[method]}分级在 n={n} 时失败（数据可能不足以分这么多级）：{exc}"
            ) from exc
        raw_breaks = tuple(float(item) for item in classifier.bins)
        if len(raw_breaks) != n:
            raise DataError(
                f"{METHOD_LABELS[method]}分级返回 {len(raw_breaks)} 个断点，预期 {n} 个；"
                "数据可能不足以分这么多级"
            )
        if any(a >= b for a, b in zip(raw_breaks, raw_breaks[1:])):
            raise DataError(
                f"数据不足以分成 {n} 级（{METHOD_LABELS[method]}断点非严格递增）：{raw_breaks}"
            )
        breaks = tuple(raw_breaks)
        counts = tuple(int(count) for count in classifier.counts)

    labels = _make_labels(breaks, vmin)
    summary = _summary(method, n, breaks, counts, vmin, vmax)
    return ClassificationResult(
        method=method,
        n=n,
        breaks=breaks,
        labels=labels,
        counts=counts,
        summary=summary,
    )