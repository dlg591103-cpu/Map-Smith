"""GeoTIFF 离线底图读取（仅显示）。

规则来源：docs/facts/02-范围与边界.md「输入数据格式」与「明确不做」：
- GeoTIFF 只作离线底图显示，不做栅格分析、不重投影、不自动配准。
- CRS 与出图坐标系不一致时明确提示，不静默叠加。

依赖只有 Pillow（随 matplotlib 安装），不引入 rasterio / GDAL：本任务只需要
地理参考与像素数组，复杂栅格能力不在范围内。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from ..projection import plan_transform
from .models import DataError

TAG_PIXEL_SCALE = 33550
TAG_TIEPOINT = 33922
TAG_GEOKEY_DIRECTORY = 34735

KEY_GT_MODEL_TYPE = 1024
KEY_GEOGRAPHIC_TYPE = 2048
KEY_PROJECTED_CS = 3072

# GeoKey 3072 的 32767 表示“用户自定义”，没有可用的 EPSG 编码。
USER_DEFINED_CS = 32767


@dataclass
class RasterUnderlay:
    """一张可交给渲染层 `imshow` 的底图。

    `extent` 为 `(left, right, bottom, top)`，与 matplotlib 的 `imshow(extent=...)`
    一致；数值是影像自身坐标系的坐标，不是经纬度。
    """

    path: Path
    array: np.ndarray
    extent: tuple[float, float, float, float]
    crs: str | None
    width: int
    height: int
    summary: str
    meta: dict[str, Any] = field(default_factory=dict)

    def check_crs(self, target_crs: str) -> tuple[bool, str]:
        """判断能否直接叠加。返回 (可叠加, 说明)；不做任何重投影。"""
        if self.crs is None:
            return (
                False,
                "底图没有可识别的坐标系，无法判断与出图坐标系是否一致，不能静默叠加",
            )
        try:
            step = plan_transform(self.crs, target_crs)
        except Exception as exc:  # pyproj 无法建立变换时也要给出明确提示
            return (False, f"无法比较底图坐标系与出图坐标系：{exc}")
        if self.crs == target_crs:
            return (True, f"底图坐标系与出图坐标系一致（{self.crs}），可直接叠加显示")
        message = (
            f"底图坐标系为 {self.crs}，出图坐标系为 {target_crs}；"
            "按范围约定不做自动配准与重投影，请用户确认后再决定是否叠加"
        )
        if step.datum_change:
            message += "（两者还涉及基准转换）"
        return (False, message)


def _tag_value(image: Image.Image, tag: int) -> Any:
    tags = getattr(image, "tag_v2", None)
    if tags is None or tag not in tags:
        return None
    return tags[tag]


def _read_geokeys(directory: Any) -> dict[int, int]:
    """解析 GeoKeyDirectoryTag，只保留本任务关心的键。"""
    if directory is None:
        return {}
    values = list(directory)
    if len(values) < 4:
        return {}
    count = int(values[3])
    result: dict[int, int] = {}
    for index in range(count):
        offset = 4 + index * 4
        if offset + 3 >= len(values):
            break
        key_id, location, _, value = (int(values[offset + i]) for i in range(4))
        # location 非 0 表示值在另一个 TIFF tag 里，本任务不展开，按未知处理。
        if location == 0:
            result[key_id] = value
    return result


def _crs_from_geokeys(geokeys: dict[int, int]) -> str | None:
    model_type = geokeys.get(KEY_GT_MODEL_TYPE)
    geographic = geokeys.get(KEY_GEOGRAPHIC_TYPE)
    projected = geokeys.get(KEY_PROJECTED_CS)

    if projected not in (None, 0, USER_DEFINED_CS) and model_type != 2:
        return f"EPSG:{projected}"
    if geographic not in (None, 0, USER_DEFINED_CS):
        return f"EPSG:{geographic}"
    return None


def _extent_from_tags(image: Image.Image, width: int, height: int) -> tuple[float, float, float, float] | None:
    scale = _tag_value(image, TAG_PIXEL_SCALE)
    tiepoint = _tag_value(image, TAG_TIEPOINT)
    if not scale or not tiepoint or len(scale) < 2 or len(tiepoint) < 6:
        return None
    scale_x, scale_y = float(scale[0]), float(scale[1])
    i, j = float(tiepoint[0]), float(tiepoint[1])
    x, y = float(tiepoint[3]), float(tiepoint[4])

    left = x - i * scale_x
    top = y + j * scale_y
    right = left + width * scale_x
    bottom = top - height * scale_y
    return (left, right, bottom, top)


def load_geotiff(path: str | Path) -> RasterUnderlay:
    """读取 GeoTIFF 作为离线底图。

    只读取像素与地理参考；不做重采样、裁剪或投影变换。
    """
    file_path = Path(path)
    if not file_path.exists():
        raise DataError(f"文件不存在：{file_path}")
    if file_path.suffix.lower() not in (".tif", ".tiff"):
        raise DataError(f"{file_path.name} 不是 GeoTIFF")

    try:
        image = Image.open(file_path)
    except Exception as exc:  # Pillow 的错误类型较多，统一转为可读错误
        raise DataError(f"无法打开 GeoTIFF：{exc}") from exc

    with image:
        width, height = image.size
        extent = _extent_from_tags(image, width, height)
        geokeys = _read_geokeys(_tag_value(image, TAG_GEOKEY_DIRECTORY))
        crs = _crs_from_geokeys(geokeys)
        pixel_scale = _tag_value(image, TAG_PIXEL_SCALE)
        array = np.asarray(image)
        mode = image.mode

    if extent is None:
        raise DataError(
            f"{file_path.name} 缺少 GeoTIFF 地理参考（ModelPixelScale / ModelTiepoint），"
            "无法作为离线底图叠加；普通 TIFF 不在支持范围"
        )

    band_note = "单波段灰度" if array.ndim == 2 else f"{array.shape[2]} 波段"
    crs_note = f"坐标系 {crs}" if crs else "未识别到 EPSG 坐标系（可能为用户自定义）"
    summary = (
        f"GeoTIFF 底图 {file_path.name}：{width}×{height} 像素，{band_note}，"
        f"{crs_note}。按约定仅作显示，不做栅格分析与重投影。"
    )
    return RasterUnderlay(
        path=file_path,
        array=array,
        extent=extent,
        crs=crs,
        width=width,
        height=height,
        summary=summary,
        meta={
            "pixel_scale": None if pixel_scale is None else list(pixel_scale),
            "geokeys": geokeys,
            "mode": mode,
        },
    )