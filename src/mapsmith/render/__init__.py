"""确定性渲染与版式要素（T15–T18）。"""
from __future__ import annotations

from typing import Any

from ..spec import MapSpec


def render(spec: MapSpec, gdf: Any, **kwargs: Any) -> Any:
    """Tool 5 渲染总入口：按 `spec.map_type` 分派到对应图种渲染器。

    - ``choropleth`` → `render_choropleth`
    - ``buffer`` / ``overlay`` → `render_choropleth`（结果面图层按分级设色，T25）
    - ``point`` → `render_point`
    - ``idw`` → `render_idw`

    未实现的图种抛 `NotImplementedError`，不静默降级。
    """
    if spec.map_type in {"choropleth", "buffer", "overlay"}:
        from .choropleth import render_choropleth

        kwargs.pop("background_gdf", None)
        if spec.map_type != "choropleth":
            # buffer / overlay 的结果面图层由分析产生，复用 choropleth 分级设色，
            # 字段来自 spec 的第一个图层（T25）。
            kwargs.setdefault("field", spec.layers[0].field)
        return render_choropleth(spec, gdf, **kwargs)
    if spec.map_type == "point":
        from .point import render_point

        return render_point(spec, gdf, **kwargs)
    if spec.map_type == "idw":
        from .idw import render_idw

        # 行政面交给 idw 做「凸包 ∩ 行政界」裁剪与浅灰底图；丢掉它会得到一块
        # 与行政区形状无关的倾斜色块（站点凸包只在站点密集区）。
        return render_idw(spec, gdf, **kwargs)
    raise NotImplementedError(
        f"图种 {spec.map_type!r} 的渲染尚未实现（当前支持 choropleth / point / idw / buffer / overlay）"
    )


__all__ = ["render"]