"""OpenAI 兼容的 Chat Completions 客户端（T22 第二段）。

只做一件事：把 system prompt + JSON payload 发给模型，取回一个 JSON 对象。
不绑定具体厂商；DeepSeek、OpenAI 及其他兼容服务共用同一契约。

密钥只在请求头使用，不写日志、不回显。配置见 `config.Settings.llm_*`。
"""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping

import requests

from ..config import Settings, get_settings

MISSING_CONFIG_MESSAGE = (
    "未配置模型：请设置 MAPSMITH_LLM_BASE_URL / MAPSMITH_LLM_API_KEY / "
    "MAPSMITH_LLM_MODEL，或在高级表单中出图。"
)


class LLMNotConfigured(RuntimeError):
    """缺少 base_url / api_key / model。"""


class LLMError(RuntimeError):
    """网络错误、非 2xx、超时、返回不是合法 JSON。"""


def configured(settings: Settings | None = None) -> bool:
    """三项必填是否齐全；不发起任何网络请求。"""
    return (settings or get_settings()).llm_configured


def _local_settings(settings: Settings | None) -> Settings:
    return settings if settings is not None else get_settings()


def _strip_fence(text: str) -> str:
    """去掉 ```json / ``` 围栏；模型偶尔会在 JSON 外再包一层代码块。"""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _parse_content(content: Any) -> dict[str, Any]:
    if not isinstance(content, str) or not content.strip():
        raise LLMError("模型返回内容为空")
    text = _strip_fence(content)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"模型返回不是合法 JSON：{text[:200]}") from exc
    if not isinstance(data, dict):
        raise LLMError(f"模型返回的 JSON 不是对象：{text[:200]}")
    return data


def chat_json(
    system_prompt: str,
    payload: Mapping[str, Any],
    *,
    timeout: float,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """调用 `{base_url}/chat/completions`，返回解析后的 JSON 对象。

    失败一律抛 `LLMError`（未配置抛 `LLMNotConfigured`），错误消息面向用户。
    """
    current = _local_settings(settings)
    if not current.llm_configured:
        raise LLMNotConfigured(MISSING_CONFIG_MESSAGE)

    limit = float(timeout)
    if limit <= 0:
        raise LLMError(f"模型调用超时：剩余时间不足（{limit:.1f} 秒）")

    url = str(current.llm_base_url).rstrip("/") + "/chat/completions"
    body = {
        "model": current.llm_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False),
            },
        ],
        "temperature": 0,
    }
    headers = {
        "Authorization": f"Bearer {current.llm_api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, json=body, headers=headers, timeout=limit)
    except requests.Timeout as exc:
        raise LLMError(f"模型调用超时：{limit:.0f} 秒") from exc
    except requests.RequestException as exc:
        raise LLMError(f"模型调用失败：{type(exc).__name__}: {exc}") from exc

    if response.status_code < 200 or response.status_code >= 300:
        snippet = response.text[:200] if response.text else ""
        raise LLMError(f"模型返回 HTTP {response.status_code}：{snippet}")

    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        snippet = response.text[:200] if response.text else ""
        raise LLMError(f"模型响应结构不符合预期：{snippet}") from exc

    return _parse_content(content)


def default_llm_callable(
    *,
    settings: Settings | None = None,
    timeout: float | None = None,
) -> Callable[[str, Mapping[str, Any]], dict[str, Any]]:
    """返回可直接注入 `flow` / `review` 的调用函数。

    签名与 `agents.reviewer.review(llm_callable=...)` 一致：`(system_prompt, payload)`。
    """
    current = _local_settings(settings)
    limit = current.llm_timeout_s if timeout is None else float(timeout)

    def call(system_prompt: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        return chat_json(system_prompt, payload, timeout=limit, settings=current)

    return call