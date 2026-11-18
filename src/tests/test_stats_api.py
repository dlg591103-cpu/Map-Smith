"""聚汇数据开放 API 接入的单元测试（不联网）。

真实调用需要 MAPSMITH_STATS_API_KEY，这里只覆盖：
- Key 读取；
- 行政区名去后缀的宽松匹配；
- 榜单 slug 的挑选逻辑。
"""

from __future__ import annotations

from mapsmith.tools.stats_api import _base_name, _pick_slug, stats_api_key


def test_stats_api_key_reads_env(monkeypatch):
    monkeypatch.delenv("MAPSMITH_STATS_API_KEY", raising=False)
    assert stats_api_key() == ""

    monkeypatch.setenv("MAPSMITH_STATS_API_KEY", "  ghk_demo  ")
    assert stats_api_key() == "ghk_demo"


def test_base_name_strips_admin_suffix():
    assert _base_name("杭州市") == "杭州"
    assert _base_name("苏州市") == "苏州"
    assert _base_name("鼓楼区") == "鼓楼"
    assert _base_name("杭州") == "杭州"
    assert _base_name("") == ""


def test_pick_slug_prefers_matching_adcode():
    rankings = [
        {"slug": "gdp/province/100000", "title": "全国各省GDP"},
        {"slug": "gdp/city/320000", "title": "江苏省各地级市GDP总量排行榜"},
        {"slug": "gdp/city/330000", "title": "浙江省各地级市GDP总量排行榜"},
    ]
    assert _pick_slug(rankings, "320000", {"南京市", "苏州市"}) == "gdp/city/320000"
    assert _pick_slug(rankings, "330000", {"杭州市"}) == "gdp/city/330000"


def test_pick_slug_falls_back_to_title_names():
    rankings = [
        {"slug": "gdp/city/999999", "title": "某省各市GDP"},
        {"slug": "custom/slug", "title": "南京市、苏州市、无锡市GDP排行"},
    ]
    assert _pick_slug(rankings, "", {"南京市", "苏州市", "无锡市"}) == "custom/slug"


def test_pick_slug_returns_none_when_no_match():
    assert _pick_slug([], "320000", {"南京市"}) is None
    assert _pick_slug([{"slug": "x", "title": "无关榜单"}], "320000", {"南京市"}) is None


def test_resolve_metric_slug_contains_match():
    """口语说法常带装饰词：包含匹配要能命中内置别名。

    实测问题：用户说「小学生数量」，精确查表失配（内置键是「小学生数」），
    动态搜索也没结果，最后静默落到空气质量路径、报「可用字段 AQI/CO/PM2.5」。
    """
    from mapsmith.tools.stats_api import resolve_metric_slug

    assert resolve_metric_slug("小学生数量") == "xiaoxue"
    assert resolve_metric_slug("初中生数量") == "chuzhong"
    assert resolve_metric_slug("常住人口") == "renkou"
    assert resolve_metric_slug("人口总数") == "renkou"
    assert resolve_metric_slug("财政收入") == "yshouru"


def test_resolve_metric_slug_unknown_returns_none(monkeypatch):
    """聚汇确实没有的指标返回 None，由调用方给明确提示，不静默走空气路径。"""
    monkeypatch.setenv("MAPSMITH_STATS_API_KEY", "")
    from mapsmith.tools.stats_api import resolve_metric_slug

    assert resolve_metric_slug("受教育率") is None
