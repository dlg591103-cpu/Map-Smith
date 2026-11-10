"""T22 第一段：Streamlit 界面骨架（表单建 spec + 三图种渲染 + PNG/PDF）。

只做控件与状态，所有计算调用 `ui.py`；本段不接 LLM、不接 loop.py。
一句话输入留到第二段。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st

from mapsmith.config import get_settings
from mapsmith.io.models import DataError
from mapsmith.io.uploads import parse_upload
from mapsmith.ui import (
    SUPPORTED_MAP_TYPES,
    SUPPORTED_METHODS,
    aggregate_points_to_admin,
    build_spec,
    compute_breaks,
    resolve_inputs,
    run_render,
)

# 指标字段白名单（与 tools/load_layer.py 的标准字段一致）。
FIELD_OPTIONS = [
    "PM2_5_24h",
    "PM10_24h",
    "NO2_24h",
    "SO2_24h",
    "O3_8h_24h",
    "CO_24h",
    "AQI",
]

# 连续量单色渐变配色（避免彩虹色；spec 层也会拒绝 jet/rainbow 等）。
PALETTE_OPTIONS = [
    "YlOrRd",
    "YlGnBu",
    "OrRd",
    "BuPu",
    "PuBu",
    "Greens",
    "Blues",
    "Reds",
    "Oranges",
    "Purples",
]

st.set_page_config(page_title="MapSmith 专题制图", layout="wide")
st.title("MapSmith 专题制图")

settings = get_settings()


def _data_source_note(uploaded_name: str | None) -> str:
    if uploaded_name:
        return f"数据来源：用户上传文件 {uploaded_name}"
    return "数据来源：全国城市空气质量实时发布平台（quotsoft.net），更新时间 2026-11-01"


def _prepare_uploaded_layer(uploaded) -> object | None:
    """把上传文件解析成 DataLayer；缺 CRS 时用 session_state 完成确认后返回就绪图层。

    返回 ``None`` 表示仍在等待用户确认 CRS。
    """
    # 上传文件内容在 rerun 间保持稳定；只在文件变化时重写临时文件。
    cache_key = f"{uploaded.name}:{uploaded.size}"
    if st.session_state.get("upload_cache_key") != cache_key:
        suffix = Path(uploaded.name).suffix.lower()
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(uploaded.getbuffer())
        tmp.close()
        st.session_state["upload_cache_key"] = cache_key
        st.session_state["upload_tmp_path"] = tmp.name
        st.session_state["upload_name"] = uploaded.name
        st.session_state.pop("confirmed_crs", None)

    tmp_path = st.session_state["upload_tmp_path"]
    layer = parse_upload(tmp_path, crs=st.session_state.get("confirmed_crs"))

    if layer.meta.get("crs_status") == "missing":
        st.warning(
            f"文件「{uploaded.name}」未声明坐标系，需要确认后才能继续。"
            f"建议值：{layer.meta.get('suggested_crs', 'EPSG:4326')}（未确认不生效）。"
        )
        suggested = layer.meta.get("suggested_crs") or "EPSG:4326"
        options = [suggested] + [c for c in ("EPSG:4490", "EPSG:4326", "WGS84") if c != suggested]
        confirmed = st.radio("选择坐标系", options, key="crs_choice")
        if st.button("确认坐标系并继续"):
            st.session_state["confirmed_crs"] = confirmed
            st.rerun()
        return None
    return layer


with st.sidebar:
    st.header("制图参数")
    place = st.text_input("区域（默认徐州）", value="徐州")
    date = st.text_input("日期 YYYYMMDD", value="20261101")
    field = st.selectbox("指标字段", FIELD_OPTIONS, index=0)
    map_type = st.selectbox("图种", list(SUPPORTED_MAP_TYPES), index=0)
    st.caption("buffer / overlay 尚未实现，暂不支持（待 SPEC 决策）。")

    method = st.selectbox("分级方法", list(SUPPORTED_METHODS), index=0)
    n = st.slider("级数", min_value=2, max_value=9, value=5)
    palette_scheme = st.selectbox("配色方案", PALETTE_OPTIONS, index=0)
    palette_reverse = st.checkbox("配色反转", value=False)

    uploaded = st.file_uploader(
        "上传数据（CSV / GeoJSON / Shapefile zip）",
        type=["csv", "geojson", "json", "zip"],
    )
    if uploaded is not None:
        st.caption("上传数据将替代 demo_data；缺 CRS 时需在下方确认后才会继续。")


st.markdown("### 出图")

if st.button("生成地图", type="primary"):
    try:
        uploaded_layer = None
        if uploaded is not None:
            uploaded_layer = _prepare_uploaded_layer(uploaded)
            if uploaded_layer is None:
                st.stop()

        # --- 准备数据图层 ---
        admin_gdf = None
        point_gdf = None
        source_note = _data_source_note(None)

        if uploaded_layer is not None:
            if uploaded_layer.kind == "point":
                point_gdf = uploaded_layer.gdf
            elif uploaded_layer.kind == "admin":
                admin_gdf = uploaded_layer.gdf
            source_note = _data_source_note(uploaded_layer.name)
            bbox = uploaded_layer.bbox_wgs84()
            # choropleth 需要面；只上传了点时，从 demo_data 补边界用于聚合。
            if map_type == "choropleth" and admin_gdf is None:
                admin_layer, _ = resolve_inputs(place, date, field)
                admin_gdf = admin_layer.gdf
                bbox = admin_layer.bbox_wgs84()
        else:
            admin_layer, point_layer = resolve_inputs(place, date, field)
            admin_gdf = admin_layer.gdf
            point_gdf = point_layer.gdf
            bbox = admin_layer.bbox_wgs84()

        if bbox is None:
            st.error("无法取得研究区范围，无法出图")
            st.stop()

        # --- 按图种选数据图层 ---
        if map_type == "choropleth":
            if admin_gdf is not None and field in admin_gdf.columns:
                data_gdf = admin_gdf
            elif point_gdf is not None and admin_gdf is not None:
                data_gdf = aggregate_points_to_admin(admin_gdf, point_gdf, field)
            else:
                st.error("choropleth 需要面数据：请上传带数值字段的面图层，或确保能载入边界与站点")
                st.stop()
        else:
            if point_gdf is None:
                st.error(f"{map_type} 需要点数据：请上传点位数据或确保 demo_data 站点可载入")
                st.stop()
            data_gdf = point_gdf

        # --- 计算断点并构造 spec ---
        values = list(data_gdf[field].dropna())
        if not values:
            st.error(f"字段 {field} 没有有效数值，无法分级")
            st.stop()
        try:
            breaks = compute_breaks(values, method, n)
        except DataError as exc:
            st.error(str(exc))
            st.stop()

        title = f"{place} {field} 分布图（{date}）"
        spec = build_spec(
            {
                "title": title,
                "map_type": map_type,
                "adcode": None,
                "bbox": bbox,
                "field": field,
                "method": method,
                "n": n,
                "breaks": breaks,
                "palette_scheme": palette_scheme,
                "palette_reverse": palette_reverse,
                "label_field": None,
                "show_label": False,
                "data_source_note": source_note,
                "crs": "EPSG:4490",
                "notes": [],
            }
        )

        out_dir = settings.output_dir
        result = run_render(spec, data_gdf, out_dir, name=map_type)

        st.success(f"出图完成：{result.report.summary}")
        if result.png_path and result.png_path.exists():
            st.image(str(result.png_path), caption="地图预览")
            st.download_button(
                "下载 PNG",
                data=result.png_path.read_bytes(),
                file_name=result.png_path.name,
                mime="image/png",
            )
        if result.pdf_path and result.pdf_path.exists():
            st.download_button(
                "下载 PDF",
                data=result.pdf_path.read_bytes(),
                file_name=result.pdf_path.name,
                mime="application/pdf",
            )
    except DataError as exc:
        st.error(str(exc))
    except Exception as exc:  # 兜底：任何未预期错误都给中文提示，不抛裸 traceback
        st.error(f"出图失败：{type(exc).__name__}：{exc}")