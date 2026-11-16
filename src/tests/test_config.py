import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from mapsmith import __version__
from mapsmith.config import Settings, get_settings

SRC_ROOT = Path(__file__).resolve().parents[1]


def test_version():
    assert __version__ == "0.1.1"


def test_defaults_match_spec():
    settings = Settings()
    assert settings.max_clarify_questions == 2
    assert settings.max_rework_rounds == 2
    assert settings.max_global_rounds == 8
    assert settings.global_timeout_s == 60.0
    assert settings.demo_data_dir.name == "demo_data"
    assert settings.output_dir.name == "out"


def test_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("MAPSMITH_GLOBAL_TIMEOUT_S", "90")
    monkeypatch.setenv("MAPSMITH_MAX_REWORK_ROUNDS", "3")
    monkeypatch.setenv("MAPSMITH_OUTPUT_DIR", str(tmp_path))
    settings = Settings.from_env()
    assert settings.global_timeout_s == 90.0
    assert settings.max_rework_rounds == 3
    assert settings.output_dir == tmp_path


def test_invalid_env_rejected(monkeypatch):
    monkeypatch.setenv("MAPSMITH_MAX_GLOBAL_ROUNDS", "many")
    with pytest.raises(ValueError, match="MAPSMITH_MAX_GLOBAL_ROUNDS"):
        Settings.from_env()


def test_get_settings_is_cached():
    get_settings.cache_clear()
    first = get_settings()
    assert get_settings() is first
    get_settings.cache_clear()


def test_default_llm_is_local_ollama():
    """T25：默认预置本机 Ollama，用户可用 .env / 环境变量覆盖。"""
    settings = Settings()
    assert settings.llm_provider == "ollama"
    assert settings.llm_base_url == "http://127.0.0.1:11434/v1"
    assert settings.llm_model == "qwen2.5:3b"
    assert settings.llm_configured is True


def test_dotenv_loaded_without_overriding_env(monkeypatch, tmp_path):
    from mapsmith.config import _load_dotenv

    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "# 注释行\nMAPSMITH_LLM_MODEL=deepseek-chat\n"
        'MAPSMITH_LLM_BASE_URL="https://api.deepseek.com/v1"\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("MAPSMITH_LLM_MODEL", raising=False)
    monkeypatch.setenv("MAPSMITH_LLM_BASE_URL", "https://keep.example/v1")

    _load_dotenv(dotenv)

    assert os.environ["MAPSMITH_LLM_MODEL"] == "deepseek-chat"
    # 已存在的环境变量优先，.env 不覆盖。
    assert os.environ["MAPSMITH_LLM_BASE_URL"] == "https://keep.example/v1"


def test_subpackages_importable():
    for name in [
        "mapsmith.io",
        "mapsmith.tools",
        "mapsmith.agents",
        "mapsmith.render",
        "mapsmith.kb",
    ]:
        importlib.import_module(name)


def test_module_entrypoint():
    env = {**os.environ, "PYTHONPATH": str(SRC_ROOT)}
    version = subprocess.run(
        [sys.executable, "-m", "mapsmith", "--version"],
        capture_output=True,
        text=True,
        env=env,
        cwd=SRC_ROOT,
    )
    assert version.returncode == 0
    assert __version__ in version.stdout

    config = subprocess.run(
        [sys.executable, "-m", "mapsmith", "--config", "--json"],
        capture_output=True,
        text=True,
        env=env,
        cwd=SRC_ROOT,
    )
    assert config.returncode == 0
    data = json.loads(config.stdout)
    assert data["global_timeout_s"] == 60.0
    assert data["max_global_rounds"] == 8
    assert Path(data["demo_data_dir"]).name == "demo_data"