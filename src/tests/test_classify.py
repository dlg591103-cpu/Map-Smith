"""T12 classify 的用例；四种方法均需返回 breaks 与 labels。"""

from __future__ import annotations

import pytest

from mapsmith.io.models import DataError
from mapsmith.spec import Classification
from mapsmith.tools.classify import ClassificationResult, classify

PM_VALUES = [32.0, 45.0, 58.0, 66.0, 75.0, 88.0, 96.0, 118.0, 52.0]


@pytest.mark.parametrize("method", ["quantile", "jenks", "equal_interval"])
def test_three_methods_return_breaks_and_labels(method: str) -> None:
    result = classify(PM_VALUES, method, 4)  # type: ignore[arg-type]

    assert isinstance(result, ClassificationResult)
    assert result.n == 4
    assert len(result.breaks) == 4
    assert len(result.labels) == 4
    assert all(a < b for a, b in zip(result.breaks, result.breaks[1:]))
    assert result.breaks[-1] == pytest.approx(max(PM_VALUES))
    assert sum(result.counts) == len(PM_VALUES)


def test_equal_interval_expected_breaks() -> None:
    result = classify(list(range(11)), "equal_interval", 5)

    assert [round(b, 6) for b in result.breaks] == [2, 4, 6, 8, 10]
    assert result.counts == (3, 2, 2, 2, 2)
    assert result.labels[0] == "0–2"
    assert result.labels[-1] == "8–10"


def test_custom_aqi_six_classes() -> None:
    values = [20, 45, 80, 120, 180, 250, 320]

    result = classify(values, "custom", 6, custom_breaks=[50, 100, 150, 200, 300, None])

    assert result.n == 6
    assert list(result.breaks) == [50, 100, 150, 200, 300, None]
    assert len(result.labels) == 6
    assert result.labels[-1] == ">300"
    assert result.counts == (2, 1, 1, 1, 1, 1)


def test_result_breaks_fit_spec_classification() -> None:
    """分级结果应能直接填进 MapSpec 的 classification 字段。"""
    result = classify(PM_VALUES, "quantile", 4)

    model = Classification(method="quantile", n=4, breaks=list(result.breaks))

    assert len(model.breaks) == 4


def test_summary_mentions_method_and_range() -> None:
    result = classify(PM_VALUES, "quantile", 4)

    assert "分位数" in result.summary
    assert "32" in result.summary and "118" in result.summary


def test_unknown_method_rejected() -> None:
    with pytest.raises(DataError, match="未知分级方法"):
        classify(PM_VALUES, "no_such", 4)  # type: ignore[arg-type]


@pytest.mark.parametrize("n", [1, 10])
def test_n_out_of_range_rejected(n: int) -> None:
    with pytest.raises(DataError, match="分级数"):
        classify(PM_VALUES, "quantile", n)


def test_insufficient_distinct_values_rejected() -> None:
    with pytest.raises(DataError, match="不足以分"):
        classify([5, 5, 5, 5], "quantile", 3)


def test_custom_length_must_equal_n() -> None:
    with pytest.raises(DataError, match="custom 断点数量"):
        classify([1, 2, 3], "custom", 3, custom_breaks=[1, 2])


def test_custom_must_increase() -> None:
    with pytest.raises(DataError, match="严格递增"):
        classify([1, 2, 3], "custom", 3, custom_breaks=[3, 2, 4])


def test_custom_null_only_last() -> None:
    with pytest.raises(DataError, match="最后一项"):
        classify([1, 2, 3], "custom", 3, custom_breaks=[1, None, 3])


def test_custom_requires_breaks() -> None:
    with pytest.raises(DataError, match="必须提供 custom_breaks"):
        classify([1, 2, 3], "custom", 3)


def test_empty_values_rejected() -> None:
    with pytest.raises(DataError, match="至少一个有效数值"):
        classify([], "quantile", 3)


def test_non_numeric_values_rejected() -> None:
    with pytest.raises(DataError, match="必须全部为数值"):
        classify([1, "a", 3], "quantile", 2)  # type: ignore[list-item]