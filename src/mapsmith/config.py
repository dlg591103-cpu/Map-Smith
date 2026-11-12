"""运行配置。

业务默认值集中在本文件，来源标注到 SPEC 或已确认事实；运行期可用
`MAPSMITH_` 前缀的环境变量覆盖，例如 `MAPSMITH_GLOBAL_TIMEOUT_S=90`。

原则：这里只放参数，不放实现逻辑；参数被违反时，调用方应给出明确错误，
而不是静默回落到默认值。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ENV_PREFIX = "MAPSMITH_"

PACKAGE_DIR = Path(__file__).resolve().parent
SRC_ROOT = PACKAGE_DIR.parent
PROJECT_ROOT = SRC_ROOT.parent


def _env_text(name: str) -> str | None:
    raw = os.environ.get(ENV_PREFIX + name)
    if raw is None or raw.strip() == "":
        return None
    return raw.strip()


def _env_path(name: str, default: Path) -> Path:
    raw = _env_text(name)
    return Path(raw).expanduser() if raw else default


def _env_int(name: str, default: int) -> int:
    raw = _env_text(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(
            f"环境变量 {ENV_PREFIX}{name} 必须是整数，实际为 {raw!r}"
        ) from exc


def _env_float(name: str, default: float) -> float:
    raw = _env_text(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(
            f"环境变量 {ENV_PREFIX}{name} 必须是数字，实际为 {raw!r}"
        ) from exc


@dataclass(frozen=True)
class Settings:
    """一次运行使用的配置。字段说明见各类注释。"""

    # 路径：产物默认写入 out/，该目录已被 .gitignore 忽略。
    project_root: Path = PROJECT_ROOT
    src_root: Path = SRC_ROOT
    demo_data_dir: Path = PACKAGE_DIR / "demo_data"
    output_dir: Path = PROJECT_ROOT / "out"

    # 交互与循环上限，来源：SPEC 第 4 节第 1、6、7 条。
    max_clarify_questions: int = 2
    max_rework_rounds: int = 2
    max_global_rounds: int = 8
    global_timeout_s: float = 60.0

    # LLM 配置，来源：docs/Spec/T22-一句话入口与loop接入.md 第 4 节。
    # 三项必填任一为空即视为未配置；api_key 不进入 as_dict()。
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_timeout_s: float = 30.0

    @property
    def llm_configured(self) -> bool:
        """base_url / api_key / model 都非空才算配置完成。"""
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)

    @classmethod
    def from_env(cls) -> "Settings":
        """读取环境变量覆盖后的配置；非法数值直接报错，不静默回落。"""
        return cls(
            project_root=_env_path("PROJECT_ROOT", PROJECT_ROOT),
            src_root=_env_path("SRC_ROOT", SRC_ROOT),
            demo_data_dir=_env_path("DEMO_DATA_DIR", PACKAGE_DIR / "demo_data"),
            output_dir=_env_path("OUTPUT_DIR", PROJECT_ROOT / "out"),
            max_clarify_questions=_env_int("MAX_CLARIFY_QUESTIONS", 2),
            max_rework_rounds=_env_int("MAX_REWORK_ROUNDS", 2),
            max_global_rounds=_env_int("MAX_GLOBAL_ROUNDS", 8),
            global_timeout_s=_env_float("GLOBAL_TIMEOUT_S", 60.0),
            llm_base_url=_env_text("LLM_BASE_URL"),
            llm_api_key=_env_text("LLM_API_KEY"),
            llm_model=_env_text("LLM_MODEL"),
            llm_timeout_s=_env_float("LLM_TIMEOUT_S", 30.0),
        )

    def as_dict(self) -> dict[str, object]:
        """用于日志与 `python -m mapsmith --config` 的稳定快照。"""
        return {
            "project_root": str(self.project_root),
            "src_root": str(self.src_root),
            "demo_data_dir": str(self.demo_data_dir),
            "output_dir": str(self.output_dir),
            "max_clarify_questions": self.max_clarify_questions,
            "max_rework_rounds": self.max_rework_rounds,
            "max_global_rounds": self.max_global_rounds,
            "global_timeout_s": self.global_timeout_s,
            "llm_base_url": self.llm_base_url,
            "llm_model": self.llm_model,
            "llm_timeout_s": self.llm_timeout_s,
            "llm_configured": self.llm_configured,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程内共享一份配置；修改环境变量后需调用 `get_settings.cache_clear()`。"""
    return Settings.from_env()