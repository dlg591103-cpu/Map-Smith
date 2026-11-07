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
    assert __version__ == "0.1.0"


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