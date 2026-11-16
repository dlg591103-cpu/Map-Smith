"""像素级版式判据：用渲染产物（像素/bbox）代替字符串列表判断版式质量。

三个判据函数：
- ``frame_content_ratio``：坐标轴区域内非白像素占比，衡量内容是否充分利用图幅。
- ``labels_overlap``：图内所有 text artist 两两像素 bbox 相交检测，返回重叠对。
- ``element_overlaps_content``：版式要素（指北针 N、比例尺文字）与标注/气泡 bbox
  是否相交，返回与内容重叠的版式要素文字列表。

设计理由：前三轮交付中，断言只查 ``report.drawn`` 列表或外接框宽度比例，导致
指北针压气泡、比例尺压站名等问题无法被测试发现。判据必须落在像素层面才能真正
捕获视觉重叠。
"""

from __future__ import annotations

import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure


def frame_content_ratio(fig: Figure, *, white_threshold: float = 0.99) -> float:
    """统计坐标轴区域内非白像素占比。

    白色判定：RGB 三通道均 ≥ ``white_threshold``（默认 0.99，对应 252/255）。
    返回 [0, 1] 区间的浮点数；0 表示空白图，1 表示全填满。

    只统计第一个 axes（地图主体），忽略图例等副 axes。
    """
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    ax = fig.axes[0]
    bbox = ax.get_window_extent(renderer)
    x0 = int(bbox.x0)
    y0 = int(bbox.y0)
    x1 = int(bbox.x1)
    y1 = int(bbox.y1)
    w = x1 - x0
    h = y1 - y0
    if w <= 0 or h <= 0:
        return 0.0

    buf = fig.canvas.buffer_rgba()
    arr = np.frombuffer(buf, dtype=np.uint8).reshape(
        fig.canvas.get_width_height()[1],
        fig.canvas.get_width_height()[0],
        4,
    )
    region = arr[y0:y1, x0:x1, :3].astype(float) / 255.0
    non_white = ~np.all(region >= white_threshold, axis=2)
    return float(non_white.sum()) / float(w * h)


def labels_overlap(ax: Axes) -> list[tuple[str, str]]:
    """检测图内所有 text artist 两两像素 bbox 是否相交。

    返回重叠对列表，每项为 ``(text_a, text_b)``。空列表表示无重叠。
    只检测 ax.texts 中的文本（不含 fig.texts 底部注记）。
    """
    fig = ax.figure
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    texts = list(ax.texts)
    boxes = [t.get_window_extent(renderer) for t in texts]
    overlaps: list[tuple[str, str]] = []
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            if boxes[i].overlaps(boxes[j]):
                overlaps.append((texts[i].get_text(), texts[j].get_text()))
    return overlaps


def element_overlaps_content(
    ax: Axes,
    element_texts: list[str],
) -> list[str]:
    """检测版式要素（指北针 N、比例尺文字）与标注/气泡 bbox 是否相交。

    ``element_texts`` 是版式要素的文字列表（如 ``["N", "5 km"]``）。
    返回与内容重叠的版式要素文字列表；空列表表示无重叠。

    判定逻辑：先按文字内容匹配版式要素的 text artist，剩余 text artist 视为内容；
    然后检查每个版式要素 bbox 是否与任何内容 bbox 相交。
    """
    fig = ax.figure
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()

    all_texts = list(ax.texts)
    element_set = set(element_texts)
    elements = [t for t in all_texts if t.get_text() in element_set]
    contents = [t for t in all_texts if t.get_text() not in element_set]

    if not elements or not contents:
        return []

    element_boxes = [t.get_window_extent(renderer) for t in elements]
    content_boxes = [t.get_window_extent(renderer) for t in contents]

    overlapped: list[str] = []
    for elem_text, elem_box in zip(elements, element_boxes):
        for content_box in content_boxes:
            if elem_box.overlaps(content_box):
                overlapped.append(elem_text.get_text())
                break
    return overlapped