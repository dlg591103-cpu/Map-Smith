"""T15 版式要素的用例：比例尺取整、图例标签、配色解析、要素补齐与中文字体。"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import pytest  # noqa: E402

from mapsmith.io.models import DataError  # noqa: E402
from mapsmith.render.layout import (  # noqa: E402
    apply_layout,
    classification_note,
    format_distance,
    legend_labels,
    nice_number,
    palette_colors,
    scale_bar_length_m,
)
from mapsmith.spec import (  # noqa: E402
    Classification,
    Extent,
    Layer,
    Layout,
    MapSpec,
    Palette,
)


def make_spec(**overrides) -> MapSpec:
    data = dict(
        title="徐州市 PM2.5 24 小时均值分布图（2026-11-01）",
        map_type="choropleth",
        extent=Extent(adcode="320300", bbox=(116.2, 34.1, 118.6, 34.9)),
        layers=[
            Layer(id="data", kind="choropleth", field="PM2_5_24h", source="quotsoft_20261101")
        ],
        classification=Classification(method="quantile", n=5, breaks=[40, 50, 60, 70, 90]),
        palette=Palette(scheme="YlOrRd", reverse=False),
        layout=Layout(),
        data_source_note="数据来源：全国城市空气质量实时发布平台（quotsoft.net），更新时间 2026-11-01",
        crs="EPSG:4490",
        notes=["2 个站点缺测，已按空间邻近插补"],
    )
    data.update(overrides)
    return MapSpec(**data)


def _figure():
    fig, ax = plt.subplots(figsize=(5, 4))
    return fig, ax


# --- 比例尺 ---


def test_nice_number_rounds_to_125_steps() -> None:
    assert nice_number(23) == 20
    assert nice_number(80) == 100
    assert nice_number(1) == 1
    assert nice_number(0.03) == 0.02
    assert nice_number(7600) == 10000


def test_nice_number_rejects_nonpositive() -> None:
    with pytest.raises(DataError, match="正数"):
        nice_number(0)


def test_format_distance_switches_km() -> None:
    assert format_distance(500) == "500 m"
    assert format_distance(2000) == "2 km"


def test_scale_bar_length_is_nice_fraction() -> None:
    length, label = scale_bar_length_m(100_000)
    assert length == 20_000
    assert label == "20 km"


# --- 图例与配色 ---


def test_legend_labels_with_null_upper() -> None:
    assert legend_labels([50, 100, 150, 200, 300, None]) == [
        "≤ 50",
        "50–100",
        "100–150",
        "150–200",
        "200–300",
        "> 300",
    ]


def test_classification_note_mentions_method_and_n() -> None:
    assert classification_note(make_spec()) == "分位数分级，5 级"


def test_palette_colors_count_and_reverse() -> None:
    colors = palette_colors(make_spec(), 5)
    assert len(colors) == 5
    assert all(c.startswith("#") for c in colors)

    reversed_spec = make_spec(palette=Palette(scheme="YlOrRd", reverse=True))
    assert palette_colors(reversed_spec, 5) == list(reversed(colors))


def test_palette_unknown_scheme_rejected() -> None:
    with pytest.raises(DataError, match="未知配色方案"):
        palette_colors(make_spec(palette=Palette(scheme="no_such_scheme")), 5)


# --- 补齐版式要素 ---


def test_apply_layout_reads_spec_crs_not_hardcoded() -> None:
    fig, ax = _figure()
    spec = make_spec(crs="EPSG:4548")
    apply_layout(fig, ax, spec)
    body = "\n".join(t.get_text() for t in fig.texts)
    assert "坐标系：EPSG:4548" in body
    assert "EPSG:4490" not in body
    plt.close(fig)


def test_apply_layout_draws_all_elements_and_font() -> None:
    fig, ax = _figure()
    report = apply_layout(fig, ax, make_spec())

    assert report.font and "Noto" in report.font
    assert report.scale_bar_label is not None
    assert "图名" in report.drawn
    assert "图例" in report.drawn
    assert "比例尺" in report.drawn
    assert "指北针" in report.drawn

    legend = ax.get_legend()
    assert legend is not None and len(legend.get_texts()) == 5
    assert any(t.get_text() == "N" for t in ax.texts)
    plt.close(fig)


def test_north_arrow_sits_clear_of_legend() -> None:
    """指北针不得与右下角图例重叠（T15 修订：原实现两者同占右下角，产物上箭头被压住）。

    只看 ``report.drawn`` 里有没有「指北针」拦不住这类缺陷，这里按窗口坐标做几何检查。
    """
    fig, ax = _figure()
    apply_layout(fig, ax, make_spec())
    renderer = fig.canvas.get_renderer()

    legend = ax.get_legend()
    assert legend is not None
    n_text = next(t for t in ax.texts if t.get_text() == "N")

    n_box = n_text.get_window_extent(renderer)
    assert not n_box.overlaps(legend.get_window_extent(renderer))

    ax_box = ax.get_window_extent(renderer)
    assert n_box.y0 > ax_box.y0 + ax_box.height / 2, "指北针应位于图幅上半部"
    plt.close(fig)


def test_apply_layout_notes_include_source_crs_method_missing() -> None:
    fig, ax = _figure()
    apply_layout(fig, ax, make_spec())
    body = "\n".join(t.get_text() for t in fig.texts)
    assert "数据来源" in body
    assert "坐标系：EPSG:4490" in body
    assert "分位数分级" in body
    assert "缺失值说明" in body
    plt.close(fig)


def test_layout_flags_disable_elements() -> None:
    fig, ax = _figure()
    spec = make_spec(layout=Layout(legend=False, scale_bar=False, north_arrow=False))
    apply_layout(fig, ax, spec)
    assert ax.get_legend() is None
    assert not any(t.get_text() == "N" for t in ax.texts)
    plt.close(fig)


def test_render_png_nonempty(tmp_path) -> None:
    fig, ax = _figure()
    apply_layout(fig, ax, make_spec())
    out = tmp_path / "t15.png"
    fig.savefig(out, dpi=100)
    plt.close(fig)
    assert out.exists() and out.stat().st_size > 0