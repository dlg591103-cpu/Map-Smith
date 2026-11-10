"""取景范围：根据内容实际分布决定画多大范围，避免点图站点挤成一团。

规则来源：
- docs/facts/07 第 5 条：渲染层可补齐来源/坐标注记；取景范围属同类渲染层可补齐项。
- docs/facts/02：内部量算在度量投影下进行；本模块只做坐标范围运算，不做投影变换。

契约：``content_bounds`` 与返回值都必须是 ``spec.crs`` 下的坐标（调用方负责把内容
重投影到 spec.crs）。取景范围永远受 ``spec.extent.bbox`` 约束，不得画出图幅之外。
"""

from __future__ import annotations

from ..spec import MapSpec
from .choropleth import _transformed_extent


def drawing_extent(
    spec: MapSpec,
    *,
    content_bounds: tuple[float, float, float, float] | None = None,
    pad: float = 0.10,
    min_ratio: float = 0.05,
) -> tuple[float, float, float, float]:
    """返回 spec.crs 下的取景范围 ``(minx, miny, maxx, maxy)``。

    - ``content_bounds`` 为 None：直接返回 ``spec.extent.bbox`` 对应的取景范围（现状）。
    - ``content_bounds`` 给定时：取内容外接框向外扩 ``pad`` 比例，并与 extent 求交，
      保证不越出图幅。
    - 内容退化（零面积，或宽高都相对 extent 小于 ``min_ratio``）时回退到 extent，
      不崩、不发散成无穷大。
    """
    extent = _transformed_extent(spec)
    if content_bounds is None:
        return extent

    eminx, eminy, emaxx, emaxy = extent
    ew = emaxx - eminx
    eh = emaxy - eminy
    if ew <= 0 or eh <= 0:
        return extent

    cminx, cminy, cmaxx, cmaxy = content_bounds
    cw = cmaxx - cminx
    ch = cmaxy - cminy
    # 零面积（单点 / 共线点）回退。
    if cw <= 0 or ch <= 0:
        return extent
    # 内容相对 extent 过小（近退化），回退避免取景范围发散。
    if cw / ew < min_ratio and ch / eh < min_ratio:
        return extent

    padx = cw * pad
    pady = ch * pad
    dminx = max(cminx - padx, eminx)
    dmaxx = min(cmaxx + padx, emaxx)
    dminy = max(cminy - pady, eminy)
    dmaxy = min(cmaxy + pady, emaxy)

    if dmaxx <= dminx or dmaxy <= dminy:
        return extent
    return (dminx, dminy, dmaxx, dmaxy)