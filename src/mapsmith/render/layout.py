"""T15 版式要素：图名、图例、比例尺、指北针、来源/坐标/分级/缺失注记与中文字体。

规则来源：docs/facts/07-制图规范与审查.md 的十条规范清单。
- 渲染层可补齐：图例分组、比例尺、指北针、来源注记、坐标注记。
- 渲染层不得代填：图名要素、分级方法与级数、配色语义、缺失值说明——这些只从 MapSpec 读取。

本模块只画版式要素，不画地图主体；地图主体在 T16–T18 各自渲染。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import matplotlib
from matplotlib.axes import Axes
from matplotlib.colors import to_hex
from matplotlib.figure import Figure
from matplotlib.patches import Patch, Rectangle

from ..io.models import DataError
from ..projection import choose_measurement_crs
from ..spec import MapSpec
from .fonts import load_chinese_font

# 分级方法中文名（与 tools/classify.py 保持一致），用于图例标题与分级方法注记。
METHOD_LABELS = {
    "quantile": "分位数",
    "jenks": "自然断点",
    "equal_interval": "等间距",
    "custom": "自定义",
}

_NICE_STEPS = (1.0, 2.0, 5.0)


def _fmt(value: float) -> str:
    if float(value) == int(value):
        return str(int(value))
    return f"{value:g}"


def nice_number(target: float) -> float:
    """返回与 target 最接近的 1/2/5 × 10^k 整数，用于比例尺取整。"""
    target = float(target)
    if target <= 0:
        raise DataError(f"比例尺目标长度必须为正数，实际为 {target}")
    exponent = math.floor(math.log10(target))
    base = 10.0**exponent
    fraction = target / base
    if fraction < 1.5:
        step = 1.0
    elif fraction < 3.5:
        step = 2.0
    elif fraction < 7.5:
        step = 5.0
    else:
        step = 10.0
    return step * base


def format_distance(meters: float) -> str:
    """把米数格式成可读的距离注记；≥1000 m 用公里。"""
    meters = float(meters)
    if meters >= 1000.0:
        return f"{meters / 1000.0:g} km"
    return f"{meters:g} m"


def scale_bar_length_m(extent_width_m: float, *, target_frac: float = 0.25) -> tuple[float, str]:
    """根据图幅实际宽度（米）选一个「整数」比例尺长度，返回 (长度米, 注记)。"""
    if extent_width_m <= 0:
        raise DataError(f"图幅宽度必须为正数（米），实际为 {extent_width_m}")
    if not 0.0 < target_frac < 1.0:
        raise DataError(f"比例尺目标占比须在 (0,1) 之间，实际为 {target_frac}")
    length = nice_number(extent_width_m * target_frac)
    return length, format_distance(length)


def metric_extent(
    bbox: tuple[float, float, float, float],
    *,
    source_crs: str,
) -> tuple[float, float, float, float]:
    """把地理 bbox（经纬度）转成米制度量范围，供比例尺按真实距离计算。

    `source_crs` 是 `bbox` 自身的坐标系（输入侧），与输出坐标系 `MapSpec.crs` 无关；
    度量投影由 `choose_measurement_crs` 自动选带（见 docs/facts/02 内部量算）。
    """
    from pyproj import Transformer

    measurement = choose_measurement_crs(bbox).crs
    transformer = Transformer.from_crs(source_crs, measurement, always_xy=True)
    minx, miny = transformer.transform(bbox[0], bbox[1])
    maxx, maxy = transformer.transform(bbox[2], bbox[3])
    return (float(minx), float(miny), float(maxx), float(maxy))


def legend_labels(breaks: list[float | None]) -> list[str]:
    """由分级断点生成图例标签；末项 None 表示无上界（如 AQI「>300」）。"""
    labels: list[str] = []
    lower: float | None = None
    for upper in breaks:
        if upper is None:
            labels.append(f"> {_fmt(lower)}")  # type: ignore[arg-type]
        elif lower is None:
            labels.append(f"≤ {_fmt(upper)}")
        else:
            labels.append(f"{_fmt(lower)}–{_fmt(upper)}")
        if upper is not None:
            lower = upper
    return labels


def classification_note(spec: MapSpec) -> str:
    """分级方法注记（第 6 条）：方法 + 级数，只读取 MapSpec，不代填。"""
    classification = spec.classification
    if classification is None:
        return ""
    return f"{METHOD_LABELS.get(classification.method, classification.method)}分级，{classification.n} 级"


def palette_colors(spec: MapSpec, n: int) -> list[str]:
    """把 MapSpec 的配色方案解析成 n 个十六进制颜色，供图例与设色使用。

    配色语义由 spec.palette 决定（第 8 条）；本函数只做「方案名 → 颜色」的确定性映射，
    不代填配色。未知方案报 `DataError`，不静默回退到默认色阶。
    """
    scheme = spec.palette.scheme
    try:
        cmap = matplotlib.colormaps[scheme]
    except KeyError:
        raise DataError(f"未知配色方案 {scheme!r}")
    if n == 1:
        indices: list[float] = [0.5]
    else:
        indices = [i / (n - 1) for i in range(n)]
    colors = [to_hex(cmap(i)) for i in indices]
    if spec.palette.reverse:
        colors = list(reversed(colors))
    return colors


def draw_title(ax: Axes, spec: MapSpec) -> None:
    """图名（第 1 条：区域 + 指标 + 时间），直接取 spec.title。"""
    ax.set_title(spec.title)


def draw_legend(
    ax: Axes,
    spec: MapSpec,
    *,
    unit: str | None = None,
    anchor: tuple[float, float] | None = None,
) -> None:
    """图例（第 2 条：分级断点与单位；第 6 条：分级方法注明）。

    ``anchor`` 给出时用 `bbox_to_anchor` 把图例放到坐标轴外（choropleth 的主体占满图幅，
    图例放进去会压住面要素），缺省仍留在右下角。
    """
    classification = spec.classification
    if classification is None:
        return
    labels = legend_labels(classification.breaks)
    colors = palette_colors(spec, classification.n)
    patches = [
        Patch(facecolor=color, edgecolor="#333333", label=label)
        for color, label in zip(colors, labels)
    ]
    title = classification_note(spec)
    if unit:
        title += f"（单位：{unit}）"
    if anchor is not None:
        ax.legend(handles=patches, loc="upper left", bbox_to_anchor=anchor, title=title)
        return
    ax.legend(handles=patches, loc="lower right", title=title)


_LABEL_OFFSET_CANDIDATES: list[tuple[float, float]] = [
    (5, 5),
    (5, -12),
    (-5, 5),
    (-5, -12),
    (10, 5),
    (10, -12),
    (-10, 5),
    (-10, -12),
    (15, 5),
    (15, -12),
    (-15, 5),
    (-15, -12),
    (0, 12),
    (0, -15),
    (20, 5),
    (20, -12),
    (-20, 5),
    (-20, -12),
    (25, 5),
    (25, -12),
    (-25, 5),
    (-25, -12),
    (30, 5),
    (30, -12),
    (-30, 5),
    (-30, -12),
]


def _place_labels_avoiding_overlap(
    ax: Axes,
    coords: list[tuple[float, float]],
    texts: list[str],
    *,
    candidates: list[tuple[float, float]] | None = None,
    fontsize: int = 8,
) -> list:
    """贪心策略放置标注，避免 bbox 重叠。

    按约束程度排序：离最近邻居越近的标注越受限，优先放置以获得最多偏移选择。
    依次为每个标注尝试候选偏移位置，选第一个不与已放置标注 bbox 相交的。
    全部候选都相交时沿用最后一个候选（尽力而为）。
    """
    if candidates is None:
        candidates = _LABEL_OFFSET_CANDIDATES
    if not coords:
        return []

    n = len(coords)
    if n > 1:
        min_dists: list[float] = []
        for i in range(n):
            min_dist = float("inf")
            for j in range(n):
                if i != j:
                    dx = coords[i][0] - coords[j][0]
                    dy = coords[i][1] - coords[j][1]
                    dist = dx * dx + dy * dy
                    if dist < min_dist:
                        min_dist = dist
            min_dists.append(min_dist)
        order = sorted(range(n), key=lambda i: min_dists[i])
    else:
        order = list(range(n))

    fig = ax.figure
    placed_anns: list = [None] * n  # type: ignore[list-item]
    placed_boxes: list = []

    for idx in order:
        xi, yi = coords[idx]
        text = texts[idx]
        chosen_ann = None
        for dx, dy in candidates:
            ann = ax.annotate(
                str(text),
                (xi, yi),
                textcoords="offset points",
                xytext=(dx, dy),
                fontsize=fontsize,
            )
            fig.canvas.draw()
            renderer = fig.canvas.get_renderer()
            box = ann.get_window_extent(renderer)
            overlaps = False
            for pb in placed_boxes:
                if box.overlaps(pb):
                    overlaps = True
                    break
            if not overlaps:
                chosen_ann = ann
                placed_boxes.append(box)
                break
            ann.remove()

        if chosen_ann is None:
            dx, dy = candidates[-1]
            ann = ax.annotate(
                str(text),
                (xi, yi),
                textcoords="offset points",
                xytext=(dx, dy),
                fontsize=fontsize,
            )
            fig.canvas.draw()
            renderer = fig.canvas.get_renderer()
            placed_boxes.append(ann.get_window_extent(renderer))
            chosen_ann = ann

        placed_anns[idx] = chosen_ann

    return placed_anns


_SCALE_BAR_Y_CANDIDATES = [0.04, 0.10, 0.16, 0.22]


def draw_scale_bar(
    ax: Axes,
    extent_m: tuple[float, float, float, float],
    *,
    target_frac: float = 0.25,
) -> tuple[float, str]:
    """比例尺（第 3 条）：按图幅真实宽度（米）选整数长度，画在左下角。

    若比例尺文字与图内标注 bbox 相交，依次上移到 0.10/0.16/0.22（axes fraction），
    避免压住站名标注。全部位置都相交时保留最高位置（0.22），不再静默重叠。
    """
    width_m = extent_m[2] - extent_m[0]
    length_m, label = scale_bar_length_m(width_m, target_frac=target_frac)
    frac = length_m / width_m
    height = 0.012
    x0 = 0.05

    fig = ax.figure
    bar = Rectangle(
        (x0, _SCALE_BAR_Y_CANDIDATES[0]),
        frac,
        height,
        transform=ax.transAxes,
        facecolor="black",
        edgecolor="black",
    )
    ax.add_patch(bar)
    bar_text = ax.text(
        x0 + frac / 2.0,
        _SCALE_BAR_Y_CANDIDATES[0] + height + 0.008,
        label,
        transform=ax.transAxes,
        ha="center",
        va="bottom",
        fontsize=8,
    )

    for y0 in _SCALE_BAR_Y_CANDIDATES:
        bar.set_xy((x0, y0))
        bar_text.set_y(y0 + height + 0.008)

        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        text_box = bar_text.get_window_extent(renderer)
        overlaps = False
        for t in ax.texts:
            if t is bar_text:
                continue
            if text_box.overlaps(t.get_window_extent(renderer)):
                overlaps = True
                break
        if not overlaps:
            return length_m, label

    return length_m, label


_DEFAULT_NORTH_ARROW_CANDIDATES: list[tuple[float, float, float, float, float]] = [
    (0.94, 0.76, 0.86, 0.94, 0.875),
]

_POINT_NORTH_ARROW_CANDIDATES: list[tuple[float, float, float, float, float]] = [
    (0.94, 0.76, 0.86, 0.94, 0.875),
    (0.06, 0.76, 0.86, 0.06, 0.875),
    (1.02, 0.76, 0.86, 1.02, 0.875),
]


def draw_north_arrow(
    ax: Axes,
    *,
    candidates: list[tuple[float, float, float, float, float]] | None = None,
) -> None:
    """指北针（第 4 条）：画在右上角，箭头朝上，「N」标在箭头之上。

    ``candidates`` 是候选位置列表，每项为 ``(x, y_bot, y_top, text_x, text_y)``
    （axes fraction）。按优先级依次尝试，用像素 bbox 检测「N」是否与图内已有
    text 重叠；第一个不重叠的位置即采用。全部重叠时沿用最后一个候选（通常是
    框外位置），保证指北针始终可见。

    图例固定占右下角（``draw_legend`` 的 ``loc="lower right"``），指北针因此放在右上角，
    并抬到 ``zorder=6``，避免被图例底框或地图主体压住。
    """
    if candidates is None:
        candidates = _DEFAULT_NORTH_ARROW_CANDIDATES

    fig = ax.figure
    for x, y_bot, y_top, text_x, text_y in candidates:
        arrow = ax.annotate(
            "",
            xy=(x, y_top),
            xytext=(x, y_bot),
            xycoords="axes fraction",
            textcoords="axes fraction",
            arrowprops=dict(arrowstyle="-|>", color="black", lw=1.5),
            zorder=6,
        )
        n_text = ax.text(
            text_x,
            text_y,
            "N",
            transform=ax.transAxes,
            ha="center",
            va="bottom",
            fontsize=12,
            zorder=6,
        )

        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        n_box = n_text.get_window_extent(renderer)
        overlaps = False
        for t in ax.texts:
            if t is n_text:
                continue
            if n_box.overlaps(t.get_window_extent(renderer)):
                overlaps = True
                break
        if not overlaps:
            return

        arrow.remove()
        n_text.remove()

    last = candidates[-1]
    ax.annotate(
        "",
        xy=(last[0], last[2]),
        xytext=(last[0], last[1]),
        xycoords="axes fraction",
        textcoords="axes fraction",
        arrowprops=dict(arrowstyle="-|>", color="black", lw=1.5),
        zorder=6,
    )
    ax.text(
        last[3],
        last[4],
        "N",
        transform=ax.transAxes,
        ha="center",
        va="bottom",
        fontsize=12,
        zorder=6,
    )


def draw_notes(fig: Figure, spec: MapSpec, *, extra_note: str | None = None) -> None:
    """底部注记：数据来源与更新时间（第 5 条）、坐标系（第 7 条）、
    分级方法（第 6 条）、缺失值说明（第 10 条）。均只读取 MapSpec。

    ``extra_note`` 是渲染层补齐的说明（如「站点仅覆盖图幅局部」），追加在 spec 注记
    之后；只做说明，不改变 spec.notes 的语义。
    """
    lines: list[str] = []
    if spec.layout.source_note:
        lines.append(spec.data_source_note)
    if spec.layout.crs_note:
        lines.append(f"坐标系：{spec.crs}")
    if spec.classification is not None:
        lines.append(f"分级方法：{classification_note(spec)}")
    if spec.notes:
        lines.append("缺失值说明：" + "；".join(spec.notes))
    if extra_note:
        lines.append(extra_note)
    if lines:
        fig.text(0.01, 0.01, "\n".join(lines), ha="left", va="bottom", fontsize=7, linespacing=1.5)


@dataclass
class LayoutReport:
    """一次版式补齐的结果，供回显与测试核对。"""

    drawn: list[str] = field(default_factory=list)
    scale_bar_length_m: float | None = None
    scale_bar_label: str | None = None
    font: str | None = None
    summary: str = ""


def apply_layout(
    fig: Figure,
    ax: Axes,
    spec: MapSpec,
    *,
    extent_m: tuple[float, float, float, float] | None = None,
    unit: str | None = None,
    legend_anchor: tuple[float, float] | None = None,
    extra_note: str | None = None,
    north_arrow_candidates: list[tuple[float, float, float, float, float]] | None = None,
) -> LayoutReport:
    """按 spec.layout 的标志补齐版式要素，并加载中文字体。

    - 图名、分级方法、配色、缺失值说明只读取 MapSpec，不代填。
    - 比例尺 / 指北针 / 来源注记 / 坐标注记由渲染层补齐。
    - `extent_m` 未给时按 spec.extent.bbox 自动换算米制范围。
    - `extra_note` 是渲染层补充说明，追加进底部注记，不改变 spec.notes 语义。
    - `north_arrow_candidates` 透传给 ``draw_north_arrow``，控制指北针候选位置与避让。
    """
    font = load_chinese_font()
    report = LayoutReport(font=font)

    draw_title(ax, spec)
    report.drawn.append("图名")

    if spec.layout.legend and spec.classification is not None:
        draw_legend(ax, spec, unit=unit, anchor=legend_anchor)
        report.drawn.append("图例")

    if spec.layout.scale_bar:
        if extent_m is None:
            # extent.bbox 遵循 GeoJSON 约定（WGS84 经纬度，见 spec.Extent 注释），
            # 比例尺按经纬度→自动选带度量投影换算；与输出坐标系 spec.crs 无关。
            extent_m = metric_extent(spec.extent.bbox, source_crs="EPSG:4326")
        length_m, label = draw_scale_bar(ax, extent_m)
        report.scale_bar_length_m = length_m
        report.scale_bar_label = label
        report.drawn.append("比例尺")

    if spec.layout.north_arrow:
        draw_north_arrow(ax, candidates=north_arrow_candidates)
        report.drawn.append("指北针")

    draw_notes(fig, spec, extra_note=extra_note)
    report.drawn.append("注记")

    report.summary = "版式要素已补齐：" + "、".join(report.drawn) + f"；中文字体 {font}。"
    return report