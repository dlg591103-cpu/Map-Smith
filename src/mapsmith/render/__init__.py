"""确定性渲染与版式要素（T15–T18）。"""
from __future__ import annotations

from typing import Any

from ..spec import MapSpec


def render(spec: MapSpec, gdf: Any, **kwargs: Any) -> Any:
    """Tool 5 渲染总入口：按 `spec.map_type` 分派到对应图种渲染器。

    - ``choropleth`` → `render_choropleth`
    - ``point`` → `render_point`

    未实现的图种抛 `NotImplementedError`，不静默降级。
    """
    if spec.map_type == "choropleth":
        from .choropleth import render_choropleth

        kwargs.pop("background_gdf", None)
        return render_choropleth(spec, gdf, **kwargs)
    if spec.map_type == "point":
        from .point import render_point

        return render_point(spec, gdf, **kwargs)
    if spec.map_type == "idw":
        from .idw import render_idw

        kwargs.pop("background_gdf", None)
        return render_idw(spec, gdf, **kwargs)
    raise NotImplementedError(
        f"图种 {spec.map_type!r} 的渲染尚未实现（当前支持 choropleth / point / idw）"
    )


__all__ = ["render"]