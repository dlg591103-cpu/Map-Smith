"""T22 第二段：OpenAI 兼容客户端测试。

全部用替身，不发真实网络请求；重点验证请求构造、错误转换与 JSON 解析。
"""

from __future__ import annotations

import json

import pytest
import requests

from mapsmith.agents import llm
from mapsmith.config import Settings


def settings(**overrides) -> Settings:
    values = {
        "llm_base_url": "https://example.test/v1",
        "llm_api_key": "sk-test",
        "llm_model": "test-model",
        "llm_timeout_s": 30.0,
    }
    values.update(overrides)
    return Settings(**values)


class FakeResponse:
    def __init__(self, status_code: int = 200, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or json.dumps(payload or {})

    def json(self):
        return self._payload


def test_configured_requires_all_three_fields():
    assert llm.configured(settings()) is True
    assert llm.configured(settings(llm_api_key=None)) is False
    assert llm.configured(settings(llm_base_url="")) is False
    assert llm.configured(settings(llm_model=None)) is False


def test_unconfigured_raises_readable_error():
    with pytest.raises(llm.LLMNotConfigured) as excinfo:
        llm.chat_json("system", {}, timeout=5, settings=settings(llm_api_key=None))

    message = str(excinfo.value)
    assert "未配置模型" in message
    assert "MAPSMITH_LLM_API_KEY" in message


def test_request_is_built_as_openai_compatible(monkeypatch):
    captured: dict = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return FakeResponse(payload={"choices": [{"message": {"content": '{"place": "徐州"}'}}]})

    monkeypatch.setattr(llm.requests, "post", fake_post)

    result = llm.chat_json("你是数据管家", {"user_text": "徐州 PM2.5"}, timeout=12, settings=settings())

    assert result == {"place": "徐州"}
    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["timeout"] == 12.0
    assert captured["json"]["model"] == "test-model"
    assert captured["json"]["temperature"] == 0
    assert captured["json"]["messages"][0] == {"role": "system", "content": "你是数据管家"}
    payload = json.loads(captured["json"]["messages"][1]["content"])
    assert payload == {"user_text": "徐州 PM2.5"}


def test_base_url_trailing_slash_is_removed(monkeypatch):
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        return FakeResponse(payload={"choices": [{"message": {"content": "{}"}}]})

    monkeypatch.setattr(llm.requests, "post", fake_post)

    llm.chat_json("s", {}, timeout=5, settings=settings(llm_base_url="https://example.test/v1/"))
    assert captured["url"] == "https://example.test/v1/chat/completions"


def test_timeout_is_translated(monkeypatch):
    def fake_post(*args, **kwargs):
        raise requests.Timeout("read timed out")

    monkeypatch.setattr(llm.requests, "post", fake_post)

    with pytest.raises(llm.LLMError, match="模型调用超时") as excinfo:
        llm.chat_json("s", {}, timeout=5, settings=settings())
    assert "5" in str(excinfo.value)


def test_http_error_includes_status_and_snippet(monkeypatch):
    def fake_post(*args, **kwargs):
        return FakeResponse(status_code=401, payload={"error": "bad key"}, text="bad key")

    monkeypatch.setattr(llm.requests, "post", fake_post)

    with pytest.raises(llm.LLMError) as excinfo:
        llm.chat_json("s", {}, timeout=5, settings=settings())
    assert "401" in str(excinfo.value)
    assert "bad key" in str(excinfo.value)


def test_json_fence_is_stripped(monkeypatch):
    content = "```json\n{\"title\": \"徐州 PM2.5 图\"}\n```"

    def fake_post(*args, **kwargs):
        return FakeResponse(payload={"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr(llm.requests, "post", fake_post)

    assert llm.chat_json("s", {}, timeout=5, settings=settings()) == {"title": "徐州 PM2.5 图"}


def test_invalid_json_raises_with_snippet(monkeypatch):
    def fake_post(*args, **kwargs):
        return FakeResponse(payload={"choices": [{"message": {"content": "抱歉，我无法完成"}}]})

    monkeypatch.setattr(llm.requests, "post", fake_post)

    with pytest.raises(llm.LLMError) as excinfo:
        llm.chat_json("s", {}, timeout=5, settings=settings())
    assert "不是合法 JSON" in str(excinfo.value)
    assert "抱歉" in str(excinfo.value)


def test_unexpected_response_shape_raises(monkeypatch):
    def fake_post(*args, **kwargs):
        return FakeResponse(payload={"choices": []}, text='{"choices": []}')

    monkeypatch.setattr(llm.requests, "post", fake_post)

    with pytest.raises(llm.LLMError, match="响应结构不符合预期"):
        llm.chat_json("s", {}, timeout=5, settings=settings())


def test_default_callable_uses_configured_timeout(monkeypatch):
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["timeout"] = kwargs["timeout"]
        return FakeResponse(payload={"choices": [{"message": {"content": "{\"ok\": true}"}}]})

    monkeypatch.setattr(llm.requests, "post", fake_post)

    call = llm.default_llm_callable(settings=settings(llm_timeout_s=17.0))
    assert call("system", {"x": 1}) == {"ok": True}
    assert captured["timeout"] == 17.0


def test_api_key_is_not_in_settings_snapshot():
    snapshot = settings().as_dict()
    assert "llm_api_key" not in snapshot
    assert "sk-test" not in json.dumps(snapshot, ensure_ascii=False)