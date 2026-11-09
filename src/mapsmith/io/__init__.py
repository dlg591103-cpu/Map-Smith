"""数据加载与上传解析的公共入口。

- 矢量上传解析：见 `uploads.py`
- GeoTIFF 离线底图：见 `raster.py`
- 数据层结构与异常：见 `models.py`
"""

from .gcj02 import gcj02_to_wgs84, transform_geodataframe, wgs84_to_gcj02
from .models import (
    AmbiguousPlace,
    CrsNotDeclared,
    DataError,
    DataLayer,
    FieldMissing,
    PlaceNotFound,
)
from .raster import RasterUnderlay, load_geotiff
from .uploads import ensure_crs, parse_upload

__all__ = [
    "AmbiguousPlace",
    "CrsNotDeclared",
    "DataError",
    "DataLayer",
    "FieldMissing",
    "PlaceNotFound",
    "RasterUnderlay",
    "ensure_crs",
    "gcj02_to_wgs84",
    "load_geotiff",
    "parse_upload",
    "transform_geodataframe",
    "wgs84_to_gcj02",
]