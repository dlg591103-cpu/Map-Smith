"""T22 第二段：一句话 / 表单到 `loop.run` 的装配层。

只负责把界面输入整理成 `loop.run` 需要的四个注入函数，并做确定性补齐：
- 解析：DataSteward prompt → `place / time / metric`。
- 加载：demo_data 或上传文件 → `DataProfile` + 图层。
- 制图：Cartographer prompt 只产出决策；bbox、breaks、来源注记由本地计算。
- 渲染：按图种选图层，交给 `ui.run_render`。
- 审查：`agents.reviewer.review` 的确定性规则。

契约见 `docs/Spec/T22-一句话入口与loop接入.md`。
"""

from __future__ import annotations

import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

import matplotlib

matplotlib.use("Agg")

import pandas as pd

from .agents.llm import LLMError, default_llm_callable
from .agents.reviewer import review
from .config import Settings, get_settings
from .io.models import DataError, DataLayer, FieldMissing
from .io.uploads import ensure_crs, parse_upload
from .loop import FIELD_QUESTIONS, LoopResult, NeedsConfirmation
from .loop import run as loop_run
from .spec import MapSpec
from .tools.analyze import buffer_layer, buffer_metric_stats, clip_layer, overlay_layer
from .tools.inspect import DataProfile, profile_points
from .tools.load_layer import (
    FIELD_ALIASES,
    load_admin,
    load_preset_stats,
    preset_stat_key,
)
from .ui import (
    SUPPORTED_METHODS,
    aggregate_points_to_admin,
    build_spec,
    compute_breaks,
    resolve_inputs,
    run_render,
)

PROMPT_DIR = Path(__file__).resolve().parent / "agents" / "prompts"
MAX_QUESTIONS = 2
FORBIDDEN_SCHEMES = {"jet", "rainbow", "hsv", "gist_rainbow", "nipy_spectral", "gist_ncar", "turbo"}

METRIC_LABELS: dict[str, str] = {
    "PM2_5_24h": "PM2.5",
    "PM10_24h": "PM10",
    "NO2_24h": "NO2",
    "SO2_24h": "SO2",
    "O3_8h_24h": "O3",
    "CO_24h": "CO",
    "AQI": "AQI",
}

METRIC_UNITS: dict[str, str] = {
    "PM2_5_24h": "μg/m³",
    "PM10_24h": "μg/m³",
    "NO2_24h": "μg/m³",
    "SO2_24h": "μg/m³",
    "O3_8h_24h": "μg/m³",
    "CO_24h": "mg/m³",
    "AQI": "",
}

# AQI 是国标强制项：固定六级断点与国标色阶，不接受模型或表单改级数。
AQI_BREAKS: list[float | None] = [50.0, 100.0, 150.0, 200.0, 300.0, None]
AQI_SCHEME = "AQI6"
AQI_UNIT = "无量纲"
AQI_SCHEMES = {"aqi6", "aqi", "cn_aqi", "china_aqi", "national_aqi"}

# 统一按「去掉点、下划线、空格、连字符」后的小写做键，PM2.5 / pm2_5 / PM2_5_24h 都能命中。
_METRIC_ALIASES: dict[str, str] = {
    "pm25": "PM2_5_24h",
    "pm2524h": "PM2_5_24h",
    "pm10": "PM10_24h",
    "pm1024h": "PM10_24h",
    "no2": "NO2_24h",
    "no224h": "NO2_24h",
    "so2": "SO2_24h",
    "so224h": "SO2_24h",
    "o3": "O3_8h_24h",
    "o38h": "O3_8h_24h",
    "o38h24h": "O3_8h_24h",
    "co": "CO_24h",
    "co24h": "CO_24h",
    "aqi": "AQI",
}

_TIME_PATTERNS = (
    re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$"),
    re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})$"),
    re.compile(r"^(\d{4})\.(\d{1,2})\.(\d{1,2})$"),
    re.compile(r"^(\d{4})(\d{2})(\d{2})$"),
    re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日"),
)

# 缺年份的日期写法（「11月1日」「11/1」「11-01」）。用户口语里极常见，
# 早先只认 4 位年份，导致「11月1日」永远解析为空、反复追问同一天。
_PARTIAL_TIME_PATTERNS = (
    re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]"),
    re.compile(r"(\d{1,2})\s*[/-]\s*(\d{1,2})(?!\d)"),
)

# 统计类指标的年度 / 季度写法（「2025」「2025年」「2025Q3」「2025年第三季度」）。
_QUARTER_PATTERN = re.compile(r"(\d{4})\s*[年\-]?\s*(?:第?([一二三四])\s*季度|[Qq]([1-4]))")
_YEAR_ONLY_PATTERN = re.compile(r"^\s*(\d{4})\s*年?\s*$")


def _allow_online() -> bool:
    """是否允许联网取数。**默认开启**，语义是「离线优先」：

    - 本地 ``demo_data/`` 有该日期/边界 → 直接用本地，绝不联网；
    - 本地没有 → 才回落到 quotsoft / DataV 在线下载（下载成功会落盘缓存）；
    - 联网失败 → 抛明确错误，不伪造数据。

    现场断网演示时设 ``MAPSMITH_OFFLINE=1`` 可强制离线，省去每次等待下载超时
    （quotsoft 实测约 12 KB/s，1.5 MB 单日文件要两分钟左右，建议改用
    ``warmup_data.py`` 提前预热）。
    """
    raw = os.environ.get("MAPSMITH_OFFLINE", "").strip().lower()
    return raw not in {"1", "true", "yes", "on"}


def _allow_online_stats_search() -> bool:
    """是否允许「联网搜索统计数据」。默认关闭。

    实测：免费搜索通道不可靠——Bing HTML 结果页只返回百科/政府首页，搜狗与百度
    直连返回验证页，抓不到具体数据表。因此这条链路只作为实验性兜底，需要显式设
    ``MAPSMITH_SEARCH_ONLINE=1`` 才启用；即使启用也做了地区名校验，抽不到可信
    数据会明确报错而不是编数字。
    """
    raw = os.environ.get("MAPSMITH_SEARCH_ONLINE", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class RequestParse:
    """一次一句话解析的结果；`questions` 非空即先反问，不进入 loop。"""

    request: dict[str, str]
    questions: list[str] = field(default_factory=list)
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class SurfaceProfile:
    """面图层体检结果；字段与 `DataProfile` 保持同名，方便统一序列化。"""

    n_valid: int
    total: int
    completeness: float
    decision: str
    reason_lines: tuple[str, str, str]
    summary: str
    value_min: float | None = None
    value_max: float | None = None
    value_mean: float | None = None


@dataclass
class UploadRecord:
    """一次上传在服务进程内的记录；重启后失效，符合本段范围。"""

    upload_id: str
    path: Path
    name: str
    kind: str = ""
    crs_status: str = ""
    suggested_crs: str | None = None
    confirmed_crs: str | None = None


@dataclass
class FlowRun:
    """一次界面请求的完整结果，供 SSE / JSON 回包。"""

    parse: RequestParse
    result: LoopResult
    render_result: Any = None


def load_prompt(name: str) -> str:
    """读取 `agents/prompts/<name>.md`；缺文件时给出中文错误。"""
    path = PROMPT_DIR / f"{name}.md"
    if not path.exists():
        raise DataError(f"缺少 prompt 文件：{path.name}")
    return path.read_text(encoding="utf-8")


def _clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"none", "null", "nan", "未知", "不详", "无"}:
        return ""
    return text


def normalize_time(value: Any) -> str:
    """把常见日期写法归一为 `YYYY-MM-DD`；无法识别返回空串。

    缺年份的写法（「11月1日」「11/1」）补「今天所在年」——用户口语里几乎不会
    带年份，早先只认 4 位年份会让这个字段永远解析失败、系统反复追问同一天。
    """
    text = _clean(value)
    if not text:
        return ""
    for pattern in _TIME_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        year, month, day = (int(part) for part in match.groups())
        try:
            return datetime(year, month, day).date().isoformat()
        except ValueError:
            return ""
    for pattern in _PARTIAL_TIME_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        month, day = (int(part) for part in match.groups())
        try:
            return datetime(datetime.now().year, month, day).date().isoformat()
        except ValueError:
            return ""
    # 统计类指标常用「年度 / 季度」口径：保留成 2025 或 2025Q3，不硬造具体日期。
    quarter = _QUARTER_PATTERN.search(text)
    if quarter:
        year, raw_quarter = quarter.group(1), quarter.group(2) or quarter.group(3)
        digits = {"一": "1", "二": "2", "三": "3", "四": "4"}
        return f"{year}Q{digits.get(raw_quarter, raw_quarter)}"
    year_only = _YEAR_ONLY_PATTERN.search(text)
    if year_only:
        return year_only.group(1)
    return ""


def _metric_key(value: Any) -> str:
    return re.sub(r"[._\-\s]", "", str(value or "")).lower()


def map_metric(value: Any) -> str:
    """把用户/模型给的指标名映射到标准字段；无法映射时保留原文。"""
    text = _clean(value)
    if not text:
        return ""
    return _METRIC_ALIASES.get(_metric_key(text), text)


def normalize_parse(raw: Mapping[str, Any] | None) -> RequestParse:
    """把模型输出整理成 `RequestParse`；本地不补默认值。"""
    data = dict(raw or {})
    request = {
        "place": _clean(data.get("place")),
        "time": normalize_time(data.get("time")),
        "metric": map_metric(data.get("metric")),
    }
    missing = [name for name in ("place", "time", "metric") if not request[name]]
    # 社会经济统计类指标（GDP / 人均GDP / 人口 / 财政收入 …）本身就是年度或季度口径，
    # 数据源只提供最新一期，不该要求用户给出「精确到某一天」。否则「山东各市人均GDP」
    # 会被反复追问「要哪一天的数据」，而这个问题对统计口径没有意义。
    if request["metric"] and not _is_air_quality_metric(request["metric"]):
        missing = [name for name in missing if name != "time"]

    model_questions = [_clean(item) for item in (data.get("questions") or []) if _clean(item)]
    if not missing:
        # 三项齐全时不再反问：模型偶尔会额外返回 questions，若照搬会阻断出图（T25 实测修复）。
        return RequestParse(request=request, questions=[], raw=data or None)

    questions = model_questions[:MAX_QUESTIONS]
    needed = min(len(missing), MAX_QUESTIONS)
    if len(questions) < needed:
        defaults = [FIELD_QUESTIONS[name] for name in missing if FIELD_QUESTIONS[name] not in questions]
        questions = (questions + defaults)[:MAX_QUESTIONS]

    return RequestParse(request=request, questions=questions[:MAX_QUESTIONS], raw=data or None)


def parse_request(
    text: str,
    llm_callable: Callable[[str, Mapping[str, Any]], Any],
    history: list[str] | None = None,
) -> RequestParse:
    """一句话 → DataSteward prompt → `RequestParse`。

    ``history`` 是同一话题下此前几轮用户说的原话（追问场景）。把它拼进
    ``user_text`` 交给模型统一抽取，避免每轮只看到当前半句、把前面已经说过的
    区域/时间/指标重新问一遍（多轮死循环）。
    """
    if not _clean(text):
        return RequestParse(
            request={"place": "", "time": "", "metric": ""},
            questions=["请说一下区域、时间和指标，例如：徐州 2026-11-01 的 PM2.5。"],
        )
    turns = [str(item).strip() for item in (history or []) if _clean(item)]
    user_text = "\n".join([*turns, str(text).strip()]) if turns else str(text).strip()
    payload = {
        "user_text": user_text,
        "multi_turn": bool(turns),
        "known_fields": {"place": "", "time": "", "metric": ""},
        "output_schema": {
            "place": "区域名称，缺项填空字符串",
            "time": (
                "日期或年份。空气质量类指标要 YYYY-MM-DD；社会经济统计类指标"
                "（GDP / 人均GDP / 人口 / 财政收入 / 城镇化率等）只给年份也可以，"
                "如 2025 或 2025年，照原文保留；完全没提时间才填空字符串"
            ),
            "metric": (
                "指标名，照抄原文。可以是空气质量指标（PM2.5 / PM10 / NO2 / SO2 / O3 / "
                "CO / AQI），也可以是社会经济统计指标（GDP / 人均GDP / 人口 / 财政收入 / "
                "城镇化率 / CPI / 进出口总额 / 医院床位数 等）。**不要因为不是空气质量指标"
                "就留空**"
            ),
            "questions": ["仅当字段缺失时填写，最多两条；三项齐全时必须为 []"],
        },
        "format_instruction": "只返回一个 JSON 对象，不要 Markdown 表格、代码围栏或解释文字。",
    }
    raw = llm_callable(load_prompt("data_steward"), payload)
    if not isinstance(raw, Mapping):
        raise LLMError("数据管家返回的不是 JSON 对象")
    return normalize_parse(raw)


def _numeric_columns(layer: DataLayer) -> list[str]:
    if layer.gdf is None:
        return []
    return [
        str(column)
        for column in layer.gdf.columns
        if column != layer.gdf.geometry.name and pd.api.types.is_numeric_dtype(layer.gdf[column])
    ]


def _is_air_quality_metric(name: str) -> bool:
    """判断指标是否是 quotsoft 能供的空气质量指标（PM2.5 / PM10 / AQI …）。

    用于把「统计类指标」和「空气质量指标」分开：前者走统计数据源，
    后者走 quotsoft 站点数据，不能互相抢路径。
    """
    mapped = map_metric(name)
    return mapped in set(FIELD_ALIASES.values())


def _require_field(layer: DataLayer, field_name: str) -> None:

    if layer.gdf is not None and field_name in layer.gdf.columns:
        return
    raise FieldMissing(field_name, _numeric_columns(layer))


# 上传统计表时，用来猜「哪一列是行政区名」的列名线索。
_TABLE_KEY_HINTS = (
    "district",
    "county",
    "region",
    "area",
    "区县",
    "地区",
    "行政区",
    "城市",
    "名称",
    "name",
    "city",
)
# 猜「哪一列是数值」的列名线索（仅在多个数值列时用来消歧）。
_TABLE_VALUE_HINTS = ("gdp", "人口", "population", "总量", "产值", "数值", "value", "指标")
# 行政区名后缀：不同数据源常一边带、一边不带（「杭州市」↔「杭州」）。
_ADMIN_SUFFIXES = ("特别行政区", "自治州", "地区", "省", "市", "盟", "区", "县")


def _base_admin_name(name: Any) -> str:
    """去掉行政区类型后缀，用于跨数据源的宽松名称匹配。"""
    text = str(name or "").strip()
    for suffix in _ADMIN_SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)]
    return text


def _pick_table_key(stats: pd.DataFrame, boundary: Any) -> str | None:
    """挑出统计表里能与边界 ``name`` 对上的行政区名列；匹配率需 ≥ 50%。

    精确匹配优先；同时用去后缀的宽松匹配兜底（数据源常给「杭州」而边界是
    「杭州市」），两种取较高者。
    """
    names: set[str] = set()
    if boundary is not None and "name" in getattr(boundary, "columns", []):
        names = {str(v).strip() for v in boundary["name"].dropna()}
    if not names:
        return None
    names_base = {_base_admin_name(name) for name in names}

    best_col: str | None = None
    best_rate = 0.0
    for column in stats.columns:
        series = stats[column]
        if pd.api.types.is_numeric_dtype(series):
            continue
        values = {str(v).strip() for v in series.dropna()}
        if not values:
            continue
        rate = len(values & names) / len(values)
        rate_base = len({_base_admin_name(v) for v in values} & names_base) / len(values)
        rate = max(rate, rate_base)
        # 同分时优先列名含线索词的列
        hinted = any(hint in str(column).lower() for hint in _TABLE_KEY_HINTS)
        if rate > best_rate or (rate == best_rate and hinted and best_col is not None):
            best_col, best_rate = str(column), rate
    return best_col if best_rate >= 0.5 else None


def _pick_table_value(
    stats: pd.DataFrame, table_key: str, preferred: str
) -> str | None:
    """挑出统计表里的数值列：优先用户选的 ``preferred``，其次唯一的数值列，再按线索词。"""
    numeric = [
        str(c)
        for c in stats.columns
        if c != table_key and pd.api.types.is_numeric_dtype(stats[c])
    ]
    if not numeric:
        return None
    if preferred in numeric:
        return preferred
    if len(numeric) == 1:
        return numeric[0]
    for column in numeric:
        if any(hint in column.lower() for hint in _TABLE_VALUE_HINTS):
            return column
    return numeric[0]


def _join_upload_table(
    layer: DataLayer, admin: DataLayer, preferred_field: str
) -> tuple[DataLayer, str]:
    """把上传的无几何统计表关联到行政区边界，返回 (面图层, 实际字段名)。

    用于「上传一份区县 GDP / 人口 / 任何统计值 → 直接出分级设色图」。关联键与
    数值列都自动识别并在摘要里写明；识别不出匹配率的行政区名列时明确报错，
    不静默生成一张空图。
    """
    from .tools.analyze import join_table

    stats = layer.table if layer.table is not None else layer.gdf
    if stats is None or len(stats) == 0:
        raise DataError(f"{layer.name} 没有可用的数据行，无法关联行政区")
    boundary = admin.gdf
    if boundary is None or "name" not in boundary.columns:
        raise DataError(f"{admin.name} 缺少行政区名称列，无法关联统计表")

    table_key = _pick_table_key(stats, boundary)
    if table_key is None:
        raise DataError(
            f"{layer.name} 里找不到能对上行政区名称的列（需与边界的 name 列匹配 ≥50%）；"
            f"可用列：{list(map(str, stats.columns))}"
        )
    value_col = _pick_table_value(stats, table_key, preferred_field)
    if value_col is None:
        raise DataError(
            f"{layer.name} 除关联键 {table_key!r} 外没有数值列，无法分级设色；"
            f"可用列：{list(map(str, stats.columns))}"
        )

    # 关联前把统计表的地区名规范化成边界里的标准写法：
    # 数据源常给「广州」而边界是「广州市」，直接 merge 会一个都对不上。
    base_to_admin = {_base_admin_name(name): str(name).strip() for name in boundary["name"]}
    normalized = stats.copy()
    join_key = "__mapsmith_join_key__"
    normalized[join_key] = normalized[table_key].map(
        lambda value: base_to_admin.get(_base_admin_name(value))
    )
    table_layer = DataLayer(
        kind="table",
        name=layer.name,
        source=layer.source,
        summary=layer.summary,
        table=normalized,
    )

    joined = join_table(table_layer, admin, key=(join_key, "name"))
    if joined.gdf is None:
        raise DataError(f"{layer.name} 关联行政区后没有产生面图层")
    if value_col not in joined.gdf.columns:
        raise FieldMissing(value_col, _numeric_columns(joined))

    matched = int(joined.gdf[value_col].notna().sum())
    if matched == 0:
        raise DataError(
            f"{layer.name} 的 {table_key!r} 列与行政区名称没有任何匹配；"
            f"边界名称示例：{sorted(set(map(str, boundary['name'])))[:5]}"
        )
    joined.summary = (
        f"{joined.summary}自动关联：{table_key!r} ↔ 边界 name，数值列 {value_col!r}"
        f"（匹配 {matched} 个面）。"
    )
    return joined, value_col


def _cache_stats_frame(
    frame: pd.DataFrame, adcode: str, stat_key: str
) -> str:
    """把联网取到的统计数据落盘到 demo_data/stats/，返回文件名。"""
    stamp = time.strftime("%Y%m%d")
    filename = f"{adcode}_{stat_key}_{stamp}.csv"
    try:
        target = get_settings().demo_data_dir / "stats" / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(target, index=False, encoding="utf-8-sig")
    except OSError:
        pass
    return filename


def _load_stats_from_api(
    place: str,
    field_name: str,
    stat_key: str,
    adcode: str,
    admin_layer: DataLayer,
    *,
    metric_label: str = "",
) -> tuple[pd.DataFrame, str] | None:
    """用聚汇数据开放 API 的免费榜单取「某地区下辖各市/区县」的指标值。

    ``stat_key`` 是榜单 slug 前缀（gdp / renkou / yshouru / chengzhen …）。
    需要 ``MAPSMITH_STATS_API_KEY``；未配置或没匹配到榜单时返回 None。
    只用免费的 ``/ranking`` 接口，不调用扣积分的 ``/data/{id}``。
    """
    from .tools.stats_api import fetch_region_stats, stats_api_key

    if not stats_api_key():
        return None
    boundary = admin_layer.gdf
    if boundary is None or "name" not in boundary.columns:
        return None
    names = {str(v).strip() for v in boundary["name"].dropna()}
    if not names:
        return None
    try:
        level = str(admin_layer.meta.get("level") or "")
        got = fetch_region_stats(stat_key, level, names, metric_label=metric_label)
    except Exception:  # noqa: BLE001 - 外部接口异常退化为「没取到」
        return None
    if got is None:
        return None
    frame, source = got
    frame = frame.rename(columns={"value": stat_key})
    filename = _cache_stats_frame(frame, adcode, stat_key)
    return frame, f"{source}（已缓存 {filename}）"


def _load_county_stats(
    place: str,
    field_name: str,
    admin_layer: DataLayer,
    *,
    confirm: bool = False,
) -> tuple[pd.DataFrame, str] | None:
    """市级：取「该市下辖各区县」的某项指标。

    聚汇的免费榜单只到地级市，区县级数据只能走「搜索指标 → 按 id 取数」，而取数
    按「买断限期访问权限」计费（1 积分/指标 365 天）。因此行为分三种：

    - 有积分且 ``confirm=True``：正常返回 ``(DataFrame, 来源说明)``；
    - 需要用户确认（``confirm=False`` 或余额不足）：抛 `NeedsConfirmation`，
      由编排层转成追问，把「要花几分、余额多少」告诉用户；
    - 搜不到该指标：返回 None，由上层继续尝试其它路径。
    """
    from .tools.stats_api import fetch_county_stats, stats_api_key

    if not stats_api_key():
        return None
    boundary = admin_layer.gdf
    if boundary is None or "name" not in boundary.columns:
        return None
    county_names = [str(value).strip() for value in boundary["name"].dropna() if str(value).strip()]
    if not county_names:
        return None
    try:
        result = fetch_county_stats(
            place, field_name, county_names, metric_label=field_name, confirm=confirm
        )
    except Exception:  # noqa: BLE001 - 外部接口异常退化为「没取到」
        return None
    if isinstance(result, dict):
        # 报价：首次取数或余额不足时聚汇返回 need_authorization
        quote = str(result.get("message") or "").strip()
        cost = result.get("points_cost")
        balance = result.get("points_balance")
        kind = "余额不足" if isinstance(balance, int) and isinstance(cost, int) and balance < cost else "需确认"
        raise NeedsConfirmation(
            [
                f"画「{place}各区县{field_name}」需要 {cost} 积分（{kind}，当前余额 {balance}）。"
                "确认购买并继续吗？",
            ],
            summary=f"需要 {cost} 积分确认",
            detail=quote or "聚汇数据返回需授权",
        )
    return result


def _search_online_stats(
    place: str,
    field_name: str,
    stat_key: str,
    adcode: str,
    admin_layer: DataLayer,
) -> tuple[pd.DataFrame, str] | None:
    """联网搜索统计数据（实验性，需 MAPSMITH_SEARCH_ONLINE=1）。

    成功时把结果缓存到 ``demo_data/stats/``，之后同一地区走预置路径、不再联网。
    失败返回 None，由调用方给出「没找到可信数据」的提示——不编数字。
    """
    from .tools.web_stats import fetch_online_stats

    boundary = admin_layer.gdf
    if boundary is None or "name" not in boundary.columns:
        return None
    names = {str(v).strip() for v in boundary["name"].dropna()}
    if not names:
        return None
    try:
        caller = default_llm_callable(settings=get_settings())
        got = fetch_online_stats(place, stat_key, field_name, names, caller=caller)
    except Exception:  # noqa: BLE001 - 实验性链路，任何异常都退化为「没搜到」
        return None
    if got is None:
        return None
    frame, source = got
    frame = frame.rename(columns={"value": stat_key})
    filename = _cache_stats_frame(frame, adcode, stat_key)
    return frame, f"{source}（已缓存 {filename}）"


def _surface_profile(layer: DataLayer, field_name: str) -> SurfaceProfile:
    if layer.gdf is None:
        raise DataError(f"{layer.name} 没有几何，无法做面图层体检")
    _require_field(layer, field_name)
    values = pd.to_numeric(layer.gdf[field_name], errors="coerce")
    total = int(len(layer.gdf))
    valid = values.dropna()
    n_valid = int(len(valid))
    completeness = n_valid / total if total else 0.0
    vmin = float(valid.min()) if n_valid else None
    vmax = float(valid.max()) if n_valid else None
    vmean = float(valid.mean()) if n_valid else None

    reasons = (
        f"面数：{total} 个",
        f"有效面：{n_valid} 个（完整度 {completeness:.0%}）",
        "结论：按面图层分级设色，不做插值",
    )
    if n_valid:
        summary = (
            f"{layer.name}：{field_name} 有效面 {n_valid} 个（共 {total} 个），"
            f"最高 {vmax:.1f}、最低 {vmin:.1f}。按面图层分级设色。"
        )
    else:
        summary = f"{layer.name}：{field_name} 全部缺测（{total} 个面）。"
    return SurfaceProfile(
        n_valid=n_valid,
        total=total,
        completeness=completeness,
        decision="choropleth",
        reason_lines=reasons,
        summary=summary,
        value_min=vmin,
        value_max=vmax,
        value_mean=vmean,
    )


def _load_overlay_base(place: str) -> DataLayer | None:
    """overlay 的第二图层：所选区域的 demo_data 边界；无边界时返回 None。

    上传面作为主体时 `admin` 必须是上传面本身（choropleth 的分级对象），
    不能同时充当第二图层，否则 clip / intersection 会变成对主体自我运算。
    """
    if not _clean(place):
        return None
    try:
        return load_admin(place, online=_allow_online())
    except DataError:
        return None


def _load_layers(
    request: Mapping[str, str],
    upload: UploadRecord | None,
    *,
    confirm_cost: bool = False,
) -> dict[str, Any]:
    place = request["place"]
    date = request["time"]
    field_name = request["metric"]

    if upload is not None:
        layer = parse_upload(upload.path, crs=upload.confirmed_crs)
        layer = ensure_crs(layer, confirmed_crs=upload.confirmed_crs)
        if layer.kind == "point":
            admin = load_admin(place, online=_allow_online())
            profile = profile_points(layer, field_name=field_name, study_area=admin)
            return {
                "summary": profile.summary,
                "decision": profile.decision,
                "reason_lines": list(profile.reason_lines),
                "profile": profile,
                "admin": admin,
                "points": layer,
                "layer": layer,
                "field": field_name,
                "date": date,
                "place": place,
            }
        if layer.kind == "admin":
            _require_field(layer, field_name)
            profile = _surface_profile(layer, field_name)
            return {
                "summary": profile.summary,
                "decision": profile.decision,
                "reason_lines": list(profile.reason_lines),
                "profile": profile,
                "admin": layer,
                "overlay_base": _load_overlay_base(place),
                "points": None,
                "layer": layer,
                "field": field_name,
                "date": date,
                "place": place,
            }
        if layer.kind == "table":
            # 上传一份「区县名 + 数值」的统计表（GDP / 人口 / 任何指标）→ 自动关联
            # 行政区边界后出分级设色图，不需要用户先自己转成面图层。
            admin = load_admin(place, online=_allow_online())
            joined, actual_field = _join_upload_table(layer, admin, field_name)
            profile = _surface_profile(joined, actual_field)
            return {
                "summary": profile.summary,
                "decision": profile.decision,
                "reason_lines": list(profile.reason_lines),
                "profile": profile,
                "admin": joined,
                "overlay_base": _load_overlay_base(place),
                "points": None,
                "layer": joined,
                "field": actual_field,
                "date": date,
                "place": place,
            }
        raise DataError("统计表需要关联行政区后才能成图；请先转成点位或面图层再上传")

    # --- 社会经济统计指标（GDP / 人口 / 财政收入 / 城镇化率 …）---
    # 1) 先看内置映射（gdp / population）；
    # 2) 若不是空气质量指标且配了聚汇 API Key，把任意指标名解析成榜单 slug 前缀。
    stat_slug = preset_stat_key(field_name)
    if stat_slug is None and not _is_air_quality_metric(field_name):
        from .tools.stats_api import resolve_metric_slug, stats_api_key

        if stats_api_key():
            try:
                stat_slug = resolve_metric_slug(field_name)
            except Exception:  # noqa: BLE001 - 解析失败按「不是统计指标」处理
                stat_slug = None

    if stat_slug is not None:
        admin_layer = load_admin(place, online=_allow_online())
        level = str(admin_layer.meta.get("level") or "")
        adcode = str(admin_layer.meta.get("adcode") or "")
        preset = load_preset_stats(adcode, stat_slug)
        if preset is None and level == "city":
            # 市级边界下辖的是「区县」，而聚汇没有区县级榜单，只能走
            # 「搜索指标 → 按 id 取数」；取数要 1 积分/指标（买断 365 天）。
            preset = _load_county_stats(place, field_name, admin_layer, confirm=confirm_cost)
        if preset is None and level != "city":
            # 没有预置数据：配了聚汇数据 API Key 就用它（榜单接口免费），
            # 命中后缓存到 demo_data/stats/，下次直接走预置路径。
            preset = _load_stats_from_api(
                place, field_name, stat_slug, adcode, admin_layer, metric_label=field_name
            )
        if preset is None and _allow_online_stats_search():
            # 实验性兜底：显式开启 MAPSMITH_SEARCH_ONLINE=1 时才联网检索。
            preset = _search_online_stats(place, field_name, stat_slug, adcode, admin_layer)
        if preset is not None:
            stats_df, stats_name = preset
            table_layer = DataLayer(
                kind="table",
                name=stats_name,
                # source 直接沿用带期次的说明（如「聚汇数据开放API…2025 年数据」或
                # 「320000_gdp_2025q3.csv」），审查规则 R05 要求来源里带时间标记。
                source=stats_name,
                summary=f"{stats_name}：{len(stats_df)} 行统计值",
                table=stats_df,
            )
            joined, actual_field = _join_upload_table(table_layer, admin_layer, field_name)
            profile = _surface_profile(joined, actual_field)
            return {
                "summary": profile.summary,
                "decision": profile.decision,
                "reason_lines": list(profile.reason_lines),
                "profile": profile,
                "admin": joined,
                "overlay_base": None,
                "points": None,
                "layer": joined,
                "field": actual_field,
                "date": date,
                "place": place,
            }
        raise DataError(
            f"{place} 没有可用的 {field_name} 统计数据（demo_data/stats/ 下没有预置文件，"
            "聚汇数据 API 也没取到匹配榜单）。可以改为上传一份「行政区名 + 数值」的 CSV，"
            "或先用其它指标（如 PM2.5）。"
        )

    # 走到这里说明指标既不是空气质量、也没解析出统计榜单。不能落到空气质量路径
    # 上——那样会在加载后报「字段 X 不存在」这种看不懂的错误（用户实测过：
    # 「小学生数量」没匹配到榜单，最后报的是可用字段是 AQI/CO/PM2.5）。
    if field_name and not _is_air_quality_metric(field_name):
        raise DataError(
            f"「{field_name}」不是空气质量指标，也没有匹配到统计数据榜单。"
            "可以改为上传一份「行政区名 + 数值」的 CSV，或换用空气质量指标（PM2.5 / AQI 等）。"
        )

    admin, points = resolve_inputs(place, date, field_name, online=_allow_online())
    profile = profile_points(points, field_name=field_name, study_area=admin)
    return {
        "summary": profile.summary,
        "decision": profile.decision,
        "reason_lines": list(profile.reason_lines),
        "profile": profile,
        "admin": admin,
        "points": points,
        "layer": points,
        "field": field_name,
        "date": date,
        "place": place,
    }


def _profile_payload(profile: Any) -> dict[str, Any]:
    if is_dataclass(profile) and not isinstance(profile, type):
        return asdict(profile)
    if isinstance(profile, Mapping):
        return dict(profile)
    return {"summary": str(profile)}


def _clamp_int(value: Any, *, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _buffer_km(value: Any, *, default: float = 5.0, low: float = 0.1, high: float = 200.0) -> float:
    """解析缓冲距离（km）；缺省用 5，非法或超范围直接报错，不静默截断。"""
    if value is None or str(value).strip() == "":
        return default
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DataError(f"缓冲距离必须是数字（公里），实际为 {value!r}") from exc
    if number <= 0:
        raise DataError(f"缓冲距离必须为正数（公里），实际为 {number:g}")
    if not (low <= number <= high):
        raise DataError(f"缓冲距离需在 {low:g}–{high:g} km 之间，实际为 {number:g}")
    return number


def _region_label(place: str) -> str:
    """图名里的区域要素：审查要求带行政区后缀，缺省时补「市」。"""
    if re.search(r"(省|市|区|县|自治州|自治区|特别行政区|盟|旗)$", place):
        return place
    return place + "市"


def _title_date(request_time: str, loaded: Mapping[str, Any]) -> str:
    """标题用的时间标记：统计指标没有具体日期时，用数据源里的期次代替。

    `run_one_sentence` 给统计指标补的是「最新」占位（数据源只给最新一期），
    但审查规则 R01 要求标题含时间要素。这里从 `layer.source` 里提取年份
    （如「…2025 年数据」「320000_gdp_2025q3.csv」），提到就用它。
    """
    text = _clean(request_time)
    if text and re.search(r"\d{4}", text):
        return text
    layer = loaded.get("layer")
    source = str(getattr(layer, "source", "") or "")
    match = re.search(r"(20\d{2})", source)
    return match.group(1) if match else text


def _local_title(place: str, field_name: str, date: str) -> str:
    label = METRIC_LABELS.get(field_name, field_name)
    unit = METRIC_UNITS.get(field_name)
    suffix = f"，{unit}" if unit else ""
    return f"{_region_label(place)} {label} 分布图（{date}{suffix}）"


def _ensure_title(draft_title: Any, place: str, field_name: str, date: str) -> str:
    title = _clean(draft_title)
    local = _local_title(place, field_name, date)
    if not title:
        return local
    # 区域按 R01 口径要求带行政区后缀（如「徐州市」）；模型只写「徐州」时
    # 审查会判 R01 fail，因此这里与审查规则保持一致，直接回退本地标题。
    required = [_region_label(place), date, METRIC_LABELS.get(field_name, field_name)]
    if not all(part and part in title for part in required):
        return local
    unit = METRIC_UNITS.get(field_name)
    if unit and unit not in title:
        return local
    return title


def _merge_notes(base: Any, extra: Any) -> list[str]:
    merged: list[str] = []
    for source in (base, extra):
        for item in source or []:
            text = _clean(item)
            if text and text not in merged:
                merged.append(text)
    return merged


_CONCLUSION_PREFIX = "结论："


def _reason_notes(loaded: Mapping[str, Any], map_type: str) -> list[str]:
    """数据体检的「结论」行只在它真正决定图种时写入注记。

    ``reason_lines`` 的结论行描述渲染方式（如「降级为点图」）。用户显式选择
    choropleth / buffer / overlay 时，渲染按用户图种执行，继续写入会与实际
    出图矛盾；站数与覆盖度等体检数据仍保留。T25 复验修复。
    """
    decision = _clean(loaded.get("decision"))
    conclusion_applies = (map_type == "point" and decision == "degrade") or (
        map_type == "idw" and decision == "idw"
    )
    lines: list[str] = []
    for item in loaded.get("reason_lines") or []:
        text = _clean(item)
        if not text:
            continue
        if text.startswith(_CONCLUSION_PREFIX) and not conclusion_applies:
            continue
        lines.append(text)
    return lines


def _core_bounds(
    gdf: Any, *, iqr_factor: float = 1.5
) -> tuple[float, float, float, float] | None:
    """取「主体」的外包范围，排除远离主体的离群面。

    典型场景：海南省下辖三沙市，其面覆盖南海诸岛（3.84°N~19.53°N），而海南岛
    主体只占 18.15°N~20.17°N。直接用整体 bbox 会让图幅被拉大约 8 倍，海南岛缩成
    一小块、整幅几乎全是空海域。

    判定用 Tukey 离群点规则：各面中心到「中位中心」的距离超过 ``Q3 + 1.5×IQR``
    才视为离群。这样海南的三沙（距离 8°+）会被剔除，而江苏/广东这种面本来就
    分散的正常省份不会被误伤（距离都在 Q3+1.5IQR 之内）。
    """
    if gdf is None or len(gdf) <= 2:
        return None
    try:
        bounds = gdf.geometry.bounds
    except Exception:  # noqa: BLE001 - 几何异常时退回整体范围
        return None
    if bounds is None or len(bounds) == 0:
        return None
    center_x = (bounds["minx"] + bounds["maxx"]) / 2.0
    center_y = (bounds["miny"] + bounds["maxy"]) / 2.0
    mid_x, mid_y = center_x.median(), center_y.median()
    distance = ((center_x - mid_x) ** 2 + (center_y - mid_y) ** 2) ** 0.5
    q1, q3 = distance.quantile(0.25), distance.quantile(0.75)
    threshold = q3 + iqr_factor * (q3 - q1)
    keep = distance <= threshold
    if int(keep.sum()) < 2 or int(keep.sum()) == len(gdf):
        return None  # 没有离群面，交给调用方用整体范围
    core = gdf[keep]
    minx, miny, maxx, maxy = core.total_bounds
    return (float(minx), float(miny), float(maxx), float(maxy))


def _bbox_for(loaded: Mapping[str, Any], map_type: str) -> tuple[float, float, float, float] | None:
    layer = loaded["layer"]
    if map_type in {"choropleth", "overlay"}:
        # overlay 的主体是上传面、第二图层是区域边界；图幅取区域边界才能同时
        # 看到叠加结果与区域上下文。只用主体 bbox 会把局部主体放大到满幅，
        # 第二图层落到图外，指北针也会压到面色块上（T25 复验）。
        admin = loaded.get("overlay_base") if map_type == "overlay" else loaded.get("admin")
        if admin is not None:
            # 优先用「核心范围」：省域含远海岛礁（海南三沙）时避免图幅被拉散。
            core = _core_bounds(admin.gdf) if admin.gdf is not None else None
            if core is not None:
                return core
            bbox = admin.bbox_wgs84()
            if bbox is not None:
                return bbox
        return layer.bbox_wgs84()
    admin = loaded.get("admin")
    if admin is not None:
        core = _core_bounds(admin.gdf) if admin.gdf is not None else None
        if core is not None:
            return core
        bbox = admin.bbox_wgs84()
        if bbox is not None:
            return bbox
    return layer.bbox_wgs84()


def _breaks_for(gdf: Any, field_name: str, method: str, n: int) -> list[float | None]:
    if gdf is None or field_name not in gdf.columns:
        available = (
            [
                str(column)
                for column in gdf.columns
                if column != gdf.geometry.name and pd.api.types.is_numeric_dtype(gdf[column])
            ]
            if gdf is not None
            else []
        )
        raise FieldMissing(field_name, available)
    values = pd.to_numeric(gdf[field_name], errors="coerce").dropna().tolist()
    if not values:
        raise DataError(f"字段「{field_name}」没有有效数值，无法分级")
    return compute_breaks(values, method, n)


def _palette_from(draft_palette: Any) -> tuple[str, bool, str | None]:
    palette = draft_palette if isinstance(draft_palette, Mapping) else {}
    scheme = _clean(palette.get("scheme")) or "YlOrRd"
    note: str | None = None
    if scheme.lower() in FORBIDDEN_SCHEMES:
        note = f"模型给出的配色 {scheme} 属于禁用彩虹色，已改为 YlOrRd。"
        scheme = "YlOrRd"
    return scheme, bool(palette.get("reverse", False)), note


LABEL_ALIASES = {
    "站点名": "station_name",
    "站点名称": "station_name",
    "名称": "station_name",
    "name": "station_name",
    "站点编码": "station_code",
    "编码": "station_code",
    "code": "station_code",
}


def _annotation_from(draft_annotation: Any, columns: Any) -> tuple[str | None, bool]:
    annotation = draft_annotation if isinstance(draft_annotation, Mapping) else {}
    raw_label = _clean(annotation.get("label_field"))
    label = raw_label or None
    available = {str(column) for column in columns}
    if label is not None and label not in available:
        label = LABEL_ALIASES.get(label.lower(), LABEL_ALIASES.get(label))
        if label not in available:
            label = None
    show = bool(annotation.get("show", False)) and label is not None
    return label, show


# 一句话模式的图种兜底：用户原话明确点名动作时，不把图种决定权交给 3b 模型。
_BUFFER_HINTS = ("缓冲区", "缓冲分析", "缓冲距离", "做缓冲")
_OVERLAY_HINTS = ("叠加", "裁剪", "相交")
_BUFFER_KM_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:公里|千米|km)", re.IGNORECASE)


def _map_type_hint(text: str) -> tuple[str, dict[str, Any]] | None:
    """从用户原话识别明确点名的分析动作；未点名返回 None。

    这是确定性规则：用户说「缓冲区」「裁剪叠加」时，图种不应由模型自由发挥决定。
    距离与操作优先取原话；原话未给距离时交给 `_buffer_km` 的默认值。
    """
    cleaned = _clean(text)
    if not cleaned:
        return None
    lowered = cleaned.lower()
    if any(hint in cleaned for hint in _BUFFER_HINTS) or "buffer" in lowered:
        params: dict[str, Any] = {}
        match = _BUFFER_KM_PATTERN.search(cleaned)
        if match:
            params["buffer_km"] = float(match.group(1))
        return "buffer", params
    if (
        any(hint in cleaned for hint in _OVERLAY_HINTS)
        or "clip" in lowered
        or "overlay" in lowered
        or "intersection" in lowered
    ):
        op = "intersection" if ("intersection" in lowered or "相交" in cleaned) else "clip"
        return "overlay", {"overlay_op": op}
    return None


def _review_evidence(loaded: Mapping[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """给审查规则准备证据：渲染层实际字体（R09）与数据缺失统计（R10）。

    这两项此前没有载体，`qa_check` 读不到只能恒给 WARN「未提供…证据」。字体名取
    渲染层真正会用的那个（`load_chinese_font` 的选择结果），不写死系统字体名。
    """
    render_meta: dict[str, Any] | None = None
    try:
        from .render.fonts import load_chinese_font

        render_meta = {"font_sans_serif": [load_chinese_font()], "unicode_minus": False}
    except Exception:  # noqa: BLE001 - 字体加载失败交给渲染阶段报明确错误
        render_meta = None

    data_health: dict[str, Any] | None = None
    profile = loaded.get("profile") if isinstance(loaded, Mapping) else None
    total = getattr(profile, "total", None)
    n_valid = getattr(profile, "n_valid", None)
    if isinstance(total, int) and isinstance(n_valid, int):
        nan_count = max(0, total - n_valid)
        base = str(getattr(profile, "summary", "") or "").strip()
        # R10 要求 notes/health 里明确说明缺失值处理；只报完整度不够，
        # 补一句「缺失 N 项按缺测处理」让规则有据可依。
        tail = f"缺失 {nan_count} 项按缺测处理" if nan_count else ""
        data_health = {
            "nan_count": nan_count,
            "summary": "；".join(part for part in (base, tail) if part),
        }
    return render_meta, data_health


def _compose_spec(request: Mapping[str, str], loaded: Mapping[str, Any], draft: Mapping[str, Any]) -> MapSpec:
    """把 Cartographer 的决策与本地确定性字段合成合法 MapSpec。"""
    evidence = _review_evidence(loaded)
    place = request["place"]
    date = _title_date(request["time"], loaded)
    # 字段名以「加载后实际拿到的字段」为准：统计指标（人均GDP → renjun）与空气质量
    # （PM2.5 → PM2_5_24h）都会改名，直接用原话的指标名会报「字段不存在」。
    field_name = _clean(str(loaded.get("field") or "")) or request["metric"]
    decision = str(loaded["decision"])
    draft_type = _clean(draft.get("map_type"))

    if draft_type in {"buffer", "overlay"}:
        map_type = draft_type
    elif decision == "idw":
        map_type = "idw"
    elif decision == "choropleth":
        map_type = "choropleth"
    else:
        map_type = "point"

    layer = loaded["layer"]
    gdf = layer.gdf
    if gdf is None:
        raise DataError("图层没有几何，无法制图")

    analysis = None
    spec_field = field_name
    extra_notes: list[str] = []
    if map_type in {"buffer", "overlay"}:
        analysis, spec_field, extra_notes = _analysis_layer_for(
            map_type,
            layer=layer,
            admin=loaded.get("overlay_base") or loaded.get("admin"),
            points=loaded.get("points"),
            field_name=field_name,
            buffer_km=draft.get("buffer_km"),
            overlay_op=draft.get("overlay_op"),
        )
        if isinstance(loaded, dict) and analysis is not None:
            loaded["analysis_layer"] = analysis
    target = analysis.gdf if analysis is not None else gdf

    classification = draft.get("classification") if isinstance(draft.get("classification"), Mapping) else {}
    method = _clean(classification.get("method")) or "quantile"
    if method not in SUPPORTED_METHODS:
        method = "quantile"
    n = _clamp_int(classification.get("n"), default=5, low=2, high=9)
    scheme, reverse, palette_note = _palette_from(draft.get("palette"))
    unit = METRIC_UNITS.get(field_name)

    if field_name == "AQI" and map_type in {"point", "idw", "choropleth"}:
        method, n, breaks = "custom", 6, list(AQI_BREAKS)
        scheme, reverse, palette_note = AQI_SCHEME, False, None
        unit = AQI_UNIT
    elif map_type in {"buffer", "overlay"}:
        n, breaks = _adaptive_breaks(target, spec_field, method, n, extra_notes)
    else:
        breaks = _breaks_for(target, spec_field, method, n)
    label_field, show_label = _annotation_from(draft.get("annotation"), target.columns)
    notes = _merge_notes(
        _reason_notes(loaded, map_type),
        list(draft.get("notes") or []) + ([palette_note] if palette_note else []) + extra_notes,
    )

    return build_spec(
        {
            # 标题用「用户说的指标名」（人均GDP），不用内部字段名（renjun）；
            # 字段名只用于数据绑定（spec_field）。
            "title": _ensure_title(
                draft.get("title"), place, request["metric"] or field_name, date
            ),
            "map_type": map_type,
            "adcode": loaded.get("admin", layer).meta.get("adcode"),
            "bbox": _bbox_for(loaded, map_type),
            "field": spec_field,
            "method": method,
            "n": n,
            "breaks": breaks,
            "unit": unit,
            "palette_scheme": scheme,
            "palette_reverse": reverse,
            "label_field": label_field,
            "show_label": show_label,
            "data_source_note": f"{layer.source}；更新时间：{date}",
            "crs": "EPSG:4490",
            "notes": notes,
            "render_meta": evidence[0],
            "data_health": evidence[1],
        }
    )


def _adaptive_breaks(
    target: Any,
    field: str,
    method: str,
    n: int,
    extra: list[str],
) -> tuple[int, list[float | None]]:
    """buffer / overlay 结果面数有限：级数超过有效面时逐级下调并记录原因。"""
    for attempt in range(n, 1, -1):
        try:
            breaks = _breaks_for(target, field, method, attempt)
        except DataError:
            continue
        if attempt != n:
            extra.append(f"分级数由 {n} 自动降为 {attempt}：有效面数不足以分 {n} 级")
        return attempt, breaks
    raise DataError(f"{field} 的有效面不足 2 个，无法分级；请扩大分析范围或改用其他图种")


def _analysis_layer_for(
    map_type: str,
    *,
    layer: DataLayer,
    admin: DataLayer | None,
    points: DataLayer | None,
    field_name: str,
    buffer_km: Any = None,
    overlay_op: Any = None,
) -> tuple[DataLayer | None, str, list[str]]:
    """buffer / overlay 的确定性分析与字段选择（表单与一句话共用，T25）。

    返回 `(分析结果面图层, spec 使用的字段, 备注)`；非这两种图种返回 `(None, field, [])`。
    """
    extra: list[str] = []
    if map_type == "buffer":
        if points is None or points.gdf is None:
            raise DataError("buffer 需要点数据：请上传点位数据或使用 demo_data 站点")
        distance = _buffer_km(buffer_km)
        analysis = buffer_metric_stats(buffer_layer(points, distance), points, field_name)
        covered = int(analysis.gdf["buffer_value"].notna().sum())
        extra.append(
            f"缓冲距离 {distance:g} km；{covered}/{len(analysis.gdf)} 个缓冲面含站点，"
            "无站点缓冲面按缺失处理"
        )
        return analysis, "buffer_value", extra

    if map_type == "overlay":
        if layer.kind != "admin" or layer.gdf is None:
            raise DataError("overlay 需要上传面图层作为主体；第二图层使用 demo_data 边界")
        if admin is None or admin.gdf is None:
            raise DataError("overlay 需要第二图层：请选择区域以加载 demo_data 边界")
        op = _clean(overlay_op) or "clip"
        if op == "clip":
            analysis = clip_layer(layer, admin)
        elif op in {"intersection", "overlay"}:
            analysis = overlay_layer(layer, admin, how="intersection")
        else:
            raise DataError(f"叠加方式 {op!r} 不受支持；可用 clip / intersection")
        spec_field = (
            field_name
            if field_name in analysis.gdf.columns
            else next(iter(_numeric_columns(analysis)), field_name)
        )
        extra.append(f"叠加方式：{analysis.meta.get('op', op)}；第二图层：{admin.name}")
        return analysis, spec_field, extra

    return None, field_name, extra


def _form_spec(parse: RequestParse, form: Mapping[str, Any], loaded: Mapping[str, Any]) -> MapSpec:
    """表单路径：图种、方法、级数、配色全部由用户指定。

    T25 起支持 buffer / overlay：先做确定性分析，再对结果面图层分级设色。
    """
    evidence = _review_evidence(loaded)
    request = parse.request
    place = request["place"]
    date = request["time"]
    # 字段名以「加载后实际拿到的字段」为准：上传统计表（如区县 GDP）时，关联后
    # 的列名往往不同于表单里选的指标名（PM2_5_24h），用表单值会直接报字段不存在。
    field_name = _clean(str(loaded.get("field") or "")) or request["metric"]
    layer = loaded["layer"]
    gdf = layer.gdf
    if gdf is None:
        raise DataError("图层没有几何，无法制图")

    map_type = _clean(form.get("map_type")) or "point"
    if map_type not in {"choropleth", "point", "idw", "buffer", "overlay"}:
        raise DataError(
            f"图种 {map_type!r} 不受支持；可用 choropleth / point / idw / buffer / overlay"
        )

    analysis = None
    spec_field = field_name
    extra_notes: list[str] = []
    if map_type == "choropleth":
        if loaded.get("admin") is None or loaded["admin"].gdf is None:
            raise DataError("choropleth 需要面数据：请上传面图层或使用 demo_data 边界")
    elif map_type in {"buffer", "overlay"}:
        analysis, spec_field, extra_notes = _analysis_layer_for(
            map_type,
            layer=layer,
            admin=loaded.get("overlay_base") or loaded.get("admin"),
            points=loaded.get("points"),
            field_name=field_name,
            buffer_km=form.get("buffer_km"),
            overlay_op=form.get("overlay_op"),
        )
    else:
        if loaded.get("points") is None:
            raise DataError(f"{map_type} 需要点数据：请上传点位数据或使用 demo_data 站点")

    target = analysis.gdf if analysis is not None else gdf
    if isinstance(loaded, dict) and analysis is not None:
        loaded["analysis_layer"] = analysis

    method = _clean(form.get("method")) or "quantile"
    if method not in SUPPORTED_METHODS:
        raise DataError(f"分级方法 {method!r} 不受支持；可用：{'、'.join(SUPPORTED_METHODS)}")
    n = _clamp_int(form.get("n"), default=5, low=2, high=9)
    scheme = _clean(form.get("palette_scheme")) or "YlOrRd"
    if scheme.lower() in FORBIDDEN_SCHEMES:
        raise DataError(f"配色 {scheme!r} 属于禁用彩虹色；请换用单色渐变")
    unit = METRIC_UNITS.get(field_name)

    if field_name == "AQI" and map_type in {"point", "idw", "choropleth"}:
        method, n, breaks = "custom", 6, list(AQI_BREAKS)
        scheme, unit = AQI_SCHEME, AQI_UNIT
    elif map_type in {"buffer", "overlay"}:
        n, breaks = _adaptive_breaks(target, spec_field, method, n, extra_notes)
    else:
        breaks = _breaks_for(target, spec_field, method, n)

    notes = _merge_notes(_reason_notes(loaded, map_type), extra_notes)
    label_field = _clean(form.get("label_field")) or None
    if label_field is not None and label_field not in target.columns:
        label_field = None
    return build_spec(
        {
            "title": _local_title(place, field_name, date),
            "map_type": map_type,
            "adcode": loaded["admin"].meta.get("adcode") if loaded.get("admin") else None,
            "bbox": _bbox_for(loaded, map_type),
            "field": spec_field,
            "method": method,
            "n": n,
            "breaks": breaks,
            "unit": unit,
            "palette_scheme": scheme,
            "palette_reverse": False if field_name == "AQI" else bool(form.get("palette_reverse", False)),
            "label_field": label_field,
            "show_label": bool(form.get("show_label", False)) and label_field is not None,
            "data_source_note": f"{layer.source}；更新时间：{date}",
            "crs": "EPSG:4490",
            "notes": notes,
            "render_meta": evidence[0],
            "data_health": evidence[1],
        }
    )


STAGE_LABELS: dict[str, str] = {
    "parsing": "解析需求",
    "loading": "加载数据",
    "mapping": "生成制图方案",
    "rendering": "渲染地图",
    "reviewing": "审查地图",
}


def _make_emitter(on_stage: Callable[[str, str], None] | None) -> Callable[[str], None]:
    """每个阶段只通知一次，避免返工轮次把同一个 stage 重复推给前端。"""
    seen: set[str] = set()

    def emit(stage: str) -> None:
        if on_stage is None or stage in seen:
            return
        seen.add(stage)
        on_stage(stage, STAGE_LABELS.get(stage, stage))

    return emit


def _review_with_stage(emit: Callable[[str], None]) -> Callable[..., dict[str, Any]]:
    def review_stage(
        spec: Any,
        *,
        png: Any = None,
        data_summary: Any = None,
        round_no: int = 1,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        emit("reviewing")
        return review(spec, png=png, data_summary=data_summary, round_no=round_no, timeout=timeout)

    return review_stage


def _make_load_fn(
    parse: RequestParse,
    *,
    upload: UploadRecord | None,
    state: dict[str, Any],
    on_stage: Callable[[str], None] | None = None,
    confirm_cost: bool = False,
) -> Callable:
    request = dict(parse.request)
    emit = on_stage or (lambda _stage: None)

    def load(_request: Mapping[str, Any]) -> dict[str, Any]:
        emit("loading")
        loaded = _load_layers(request, upload, confirm_cost=confirm_cost)
        state["loaded"] = loaded
        return loaded

    return load


def _make_llm_map_fn(
    parse: RequestParse,
    *,
    llm_callable: Callable[[str, Mapping[str, Any]], Any],
    on_stage: Callable[[str], None] | None = None,
    user_text: str | None = None,
) -> Callable:
    prompt = load_prompt("cartographer")
    emit = on_stage or (lambda _stage: None)

    def map_(loaded: Mapping[str, Any]) -> MapSpec:
        emit("mapping")
        payload = {
            "user_request": dict(parse.request),
            "data_profile": _profile_payload(loaded["profile"]),
            "decision": loaded["decision"],
            "layer_kind": loaded["layer"].kind,
            "output_schema": {
                "map_type": "仅当用户原话点名「缓冲区/缓冲分析」或「叠加/裁剪」时填 buffer / overlay；其余留空",
                "buffer_km": "仅 map_type=buffer 时填缓冲距离（公里），如 5",
                "overlay_op": "仅 map_type=overlay 时填 clip 或 intersection",
                "title": "含区域、指标、日期与单位的图名",
                "classification": {"method": "quantile|jenks|equal_interval|custom", "n": 5},
                "palette": {"scheme": "YlOrRd|YlGnBu|Reds|Blues", "reverse": False},
                "annotation": {"label_field": "可选", "show": False},
                "notes": ["补充说明，可空"],
            },
            "format_instruction": "只返回一个 JSON 对象，不要 Markdown 表格、代码围栏或解释；breaks 不用返回，由系统计算。",
        }
        draft = llm_callable(prompt, payload)
        if not isinstance(draft, Mapping):
            raise LLMError("制图师返回的不是 JSON 对象")
        hint = _map_type_hint(user_text or "")
        if hint is not None:
            # 原话已点名分析动作：图种与距离/操作以原话为准，模型只负责分级与配色。
            map_type, params = hint
            draft = dict(draft)
            draft["map_type"] = map_type
            draft.update(params)
        return _compose_spec(parse.request, loaded, draft)

    return map_


def _make_form_map_fn(
    parse: RequestParse,
    form: Mapping[str, Any],
    *,
    on_stage: Callable[[str], None] | None = None,
) -> Callable:
    emit = on_stage or (lambda _stage: None)

    def map_(loaded: Mapping[str, Any]) -> MapSpec:
        emit("mapping")
        return _form_spec(parse, form, loaded)

    return map_


def _to_mapspec(spec: Any) -> MapSpec:
    """返工后的 spec 是 dict，可能带审查补丁字段；渲染前过滤成 MapSpec。"""
    if isinstance(spec, MapSpec):
        return spec
    data = dict(spec) if isinstance(spec, Mapping) else {}
    allowed = {
        "title",
        "map_type",
        "extent",
        "layers",
        "classification",
        "palette",
        "annotation",
        "layout",
        "data_source_note",
        "crs",
        "notes",
        # 审查证据（R09 字体 / R10 缺失值）：返工 patch 可能改动它们，
        # 过滤时保留，否则重新渲染前会丢。
        "render_meta",
        "data_health",
    }
    clean = {key: value for key, value in data.items() if key in allowed}

    classification = clean.get("classification")
    if isinstance(classification, Mapping):
        clean["classification"] = {
            key: value
            for key, value in classification.items()
            if key in {"method", "n", "breaks", "unit"}
        }

    palette = clean.get("palette")
    palette_map = palette if isinstance(palette, Mapping) else {}
    scheme = _clean(palette_map.get("scheme")) or "YlOrRd"
    if scheme.lower() in FORBIDDEN_SCHEMES:
        scheme = "YlOrRd"
    elif scheme.strip().lower() not in AQI_SCHEMES and scheme not in matplotlib.colormaps:
        scheme = "YlOrRd"
    clean["palette"] = {"scheme": scheme, "reverse": bool(palette_map.get("reverse", False))}

    return MapSpec(**clean)


def _render_frame(map_spec: MapSpec, loaded: Mapping[str, Any]) -> Any:
    # T25：buffer / overlay 的分析结果面图层优先（分级设色直接渲染该图层）。
    analysis = loaded.get("analysis_layer")
    if analysis is not None and getattr(analysis, "gdf", None) is not None:
        return analysis.gdf

    points = loaded.get("points")
    layer = loaded.get("layer")
    field_name = map_spec.layers[0].field

    if map_spec.map_type == "choropleth":
        admin = loaded.get("admin")
        points = loaded.get("points")
        if admin is None or admin.gdf is None:
            raise DataError("choropleth 缺少面数据")
        gdf = admin.gdf
        if field_name and field_name not in gdf.columns:
            if points is None:
                raise FieldMissing(str(field_name), _numeric_columns(admin))
            gdf = aggregate_points_to_admin(admin.gdf, points.gdf, str(field_name))
        return gdf

    if points is None or points.gdf is None:
        raise DataError(f"{map_spec.map_type} 需要点数据")
    return points.gdf


def _make_render_fn(
    state: dict[str, Any],
    *,
    output_dir: Path | str,
    request_id: str,
    on_stage: Callable[[str], None] | None = None,
) -> Callable:
    out_dir = Path(output_dir) / "web" / request_id
    emit = on_stage or (lambda _stage: None)

    def render_(spec: Any) -> Path:
        emit("rendering")
        loaded = state.get("loaded")
        if not loaded:
            raise DataError("渲染前没有加载结果")
        map_spec = _to_mapspec(spec)
        gdf = _render_frame(map_spec, loaded)
        kwargs: dict[str, Any] = {}
        if map_spec.map_type in {"point", "idw"} and loaded.get("admin") is not None:
            # 点图用它画底图；IDW 还用它把插值色块裁到行政界内（否则只有站点凸包）。
            kwargs["background_gdf"] = loaded["admin"].gdf
        result = run_render(map_spec, gdf, out_dir, name="web_map", **kwargs)
        state["render"] = result
        if result.png_path is None:
            raise DataError("渲染没有返回 PNG 路径")
        return result.png_path

    return render_


def review_fn(spec: Any, *, png: Any = None, data_summary: Any = None, round_no: int = 1, timeout: float = 60.0) -> dict[str, Any]:
    """只跑确定性规则；不接 LLM 软判。"""
    return review(spec, png=png, data_summary=data_summary, round_no=round_no, timeout=timeout)


def new_request_id() -> str:
    return "r_" + time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]


def _needs_input(parse: RequestParse, summary: str = "信息不足，需要先补齐") -> FlowRun:
    return FlowRun(
        parse=parse,
        result=LoopResult(
            status="needs_input",
            questions=list(parse.questions)[:MAX_QUESTIONS],
            summary=summary,
        ),
    )


def run_one_sentence(
    text: str,
    *,
    history: list[str] | None = None,
    llm_callable: Callable[[str, Mapping[str, Any]], Any] | None = None,
    upload: UploadRecord | None = None,
    output_dir: Path | str | None = None,
    request_id: str | None = None,
    settings: Settings | None = None,
    timeout: float | None = None,
    clock: Callable[[], float] | None = None,
    on_stage: Callable[[str, str], None] | None = None,
    confirm_cost: bool = False,
) -> FlowRun:
    """一句话 → 解析 → `loop.run`；缺项时直接反问，不加载数据。

    ``history`` 是同一话题下此前几轮用户原话，用于把多轮追问补的字段合并起来
    （见 `parse_request`）。
    """
    current = settings or get_settings()
    emit = _make_emitter(on_stage)
    emit("parsing")
    caller = llm_callable or default_llm_callable(settings=current)
    parse = parse_request(text, caller, history=history)
    if parse.questions:
        return _needs_input(parse)

    # 社会经济统计指标（GDP / 人均GDP / 城镇化率 …）的数据源只给最新一期，
    # 「具体某一天」对它没有意义。这里补一个「最新」占位，否则 loop 的
    # missing_fields 会把它当成缺时间、反复追问「要哪一天的数据」。
    request = dict(parse.request)
    if request.get("metric") and not _is_air_quality_metric(request["metric"]):
        if not request.get("time"):
            request["time"] = "最新"
    parse = RequestParse(request=request, questions=[], raw=parse.raw)

    state: dict[str, Any] = {}
    result = loop_run(
        parse.request,
        load_fn=_make_load_fn(parse, upload=upload, state=state, on_stage=emit, confirm_cost=confirm_cost),
        map_fn=_make_llm_map_fn(parse, llm_callable=caller, on_stage=emit, user_text=text),
        render_fn=_make_render_fn(
            state,
            output_dir=output_dir or current.output_dir,
            request_id=request_id or new_request_id(),
            on_stage=emit,
        ),
        review_fn=_review_with_stage(emit),
        clock=clock if clock is not None else time.monotonic,
        timeout=timeout,
    )
    return FlowRun(parse=parse, result=result, render_result=state.get("render"))


def run_form(
    form: Mapping[str, Any],
    *,
    upload: UploadRecord | None = None,
    output_dir: Path | str | None = None,
    request_id: str | None = None,
    settings: Settings | None = None,
    timeout: float | None = None,
    clock: Callable[[], float] | None = None,
    on_stage: Callable[[str, str], None] | None = None,
    confirm_cost: bool = False,
) -> FlowRun:
    """表单 → `loop.run`；不调用模型。"""
    current = settings or get_settings()
    emit = _make_emitter(on_stage)
    request = {
        "place": _clean(form.get("place")),
        "time": normalize_time(form.get("time")),
        "metric": map_metric(form.get("metric")),
    }
    parse = RequestParse(request=request, questions=[], raw=None)
    missing = [name for name in ("place", "time", "metric") if not request[name]]
    if missing:
        return _needs_input(parse, "表单缺少必填项：" + "、".join(missing))

    state: dict[str, Any] = {}
    result = loop_run(
        request,
        load_fn=_make_load_fn(parse, upload=upload, state=state, on_stage=emit, confirm_cost=confirm_cost),
        map_fn=_make_form_map_fn(parse, form, on_stage=emit),
        render_fn=_make_render_fn(
            state,
            output_dir=output_dir or current.output_dir,
            request_id=request_id or new_request_id(),
            on_stage=emit,
        ),
        review_fn=_review_with_stage(emit),
        clock=clock if clock is not None else time.monotonic,
        timeout=timeout,
    )
    return FlowRun(parse=parse, result=result, render_result=state.get("render"))