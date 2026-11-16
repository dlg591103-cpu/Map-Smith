"""T23 打包脚本回归：zip 必须包含前端产物，否则解压后首页会 503。"""

from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_SCRIPT = ROOT / "package.py"


def _load_package_module():
    spec = importlib.util.spec_from_file_location("mapsmith_package_script", PACKAGE_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_zip_includes_frontend_and_scripts(tmp_path: Path) -> None:
    module = _load_package_module()
    out = tmp_path / "mapsmith.zip"

    module.build_zip(out)

    with zipfile.ZipFile(out) as archive:
        names = set(archive.namelist())

    assert "web/dist/index.html" in names
    assert any(name.startswith("web/dist/assets/") for name in names)
    assert {"run.ps1", "run.sh", "Dockerfile", "docker-compose.yml"} <= names
    assert "src/mapsmith/__init__.py" in names
    assert not any(name.startswith((".venv/", "out/", ".git/")) for name in names)


def test_missing_frontend_fails_packaging(tmp_path: Path, monkeypatch) -> None:
    module = _load_package_module()
    monkeypatch.setattr(module, "ROOT", tmp_path)

    try:
        module.build_zip(tmp_path / "mapsmith.zip")
    except SystemExit as exc:
        assert "缺少必需文件" in str(exc)
    else:
        raise AssertionError("缺少 web/dist 时 build_zip 应失败")


def test_partial_zip_removed_when_required_entry_missing(tmp_path: Path, monkeypatch) -> None:
    module = _load_package_module()
    monkeypatch.setattr(module, "ROOT", tmp_path)

    for name in ("run.ps1", "run.sh", "Dockerfile", "docker-compose.yml"):
        (tmp_path / name).write_text("stub", encoding="utf-8")
    pkg = tmp_path / "src" / "mapsmith"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    dist = tmp_path / "web" / "dist"
    dist.mkdir(parents=True)
    # 目录存在于前置检查，但不会被写入 zip，触发后置条目校验。
    (dist / "index.html").mkdir()

    out = tmp_path / "mapsmith.zip"
    with pytest.raises(SystemExit, match="缺少必需条目"):
        module.build_zip(out)
    assert not out.exists(), "后置校验失败时应删除半成品 zip"