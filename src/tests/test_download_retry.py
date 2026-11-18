"""quotsoft 下载：直连优先、代理兜底、重试与中文错误提示。"""

from __future__ import annotations

import pytest
import requests

from mapsmith.io.models import DataError
from mapsmith.tools import load_layer


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    # 重试间隔只在真实网络下有意义，测试里不要真的等。
    monkeypatch.setattr(load_layer.time, "sleep", lambda _seconds: None)


def test_download_prefers_direct_connection(monkeypatch):
    calls: list[bool] = []

    def fake(url, timeout, *, trust_env):
        calls.append(trust_env)
        return "csv"

    monkeypatch.setattr(load_layer, "_fetch_once", fake)

    assert load_layer._download("https://example/x.csv", 30) == "csv"
    assert calls == [False]


def test_download_falls_back_to_proxy_after_two_direct_failures(monkeypatch):
    calls: list[bool] = []

    def fake(url, timeout, *, trust_env):
        calls.append(trust_env)
        if trust_env is False:
            raise requests.exceptions.SSLError("EOF occurred in violation of protocol")
        return "csv"

    monkeypatch.setattr(load_layer, "_fetch_once", fake)

    assert load_layer._download("https://example/x.csv", 30) == "csv"
    assert calls == [False, False, True]


def test_download_reports_friendly_error_after_all_attempts(monkeypatch):
    calls: list[bool] = []

    def fake(url, timeout, *, trust_env):
        calls.append(trust_env)
        raise requests.exceptions.ReadTimeout("Read timed out")

    monkeypatch.setattr(load_layer, "_fetch_once", fake)

    with pytest.raises(DataError) as info:
        load_layer._download("https://example/x.csv", 30)

    message = str(info.value)
    assert "数据源响应超时" in message
    assert "已尝试 3 次" in message
    # 不再把 requests 原始异常整段丢给用户
    assert "ReadTimeout" not in message
    assert len(calls) == 3


def test_http_error_is_not_retried(monkeypatch):
    calls: list[bool] = []

    def fake(url, timeout, *, trust_env):
        calls.append(trust_env)
        raise DataError("数据源返回 HTTP 404：https://example/x.csv")

    monkeypatch.setattr(load_layer, "_fetch_once", fake)

    with pytest.raises(DataError) as info:
        load_layer._download("https://example/x.csv", 30)

    assert "HTTP 404" in str(info.value)
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (requests.exceptions.SSLError("x"), "TLS 提前断开"),
        (requests.exceptions.ConnectTimeout("x"), "连接数据源超时"),
        (requests.exceptions.ConnectionError("x"), "无法连接数据源"),
    ],
)
def test_net_hint_covers_common_failures(error, expected):
    assert expected in load_layer._net_hint(requests, error)