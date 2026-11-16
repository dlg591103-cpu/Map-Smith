"""T23 打包脚本：产出可分发的 zip（含 src/、demo_data/、启动脚本、Docker 文件、README）。

用法（仓库根目录）：
    python package.py            # 产出 dist/mapsmith.zip
    python package.py --out dist/custom.zip

zip 解压后即可用 run.ps1（Windows）或 run.sh（Linux/macOS）一键启动，
或用 Dockerfile / docker-compose.yml 构建容器。断网可跑：demo_data 随 src/ 打入。
"""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# 打进的顶层条目：src/ 目录 + 根目录的运行/打包文件。
PACK_FILES = [
    "run.ps1",
    "run.sh",
    "Dockerfile",
    "docker-compose.yml",
    "package.py",
    "README.md",
]

# 顶层目录：整个 src/（demo_data 在 src/mapsmith/demo_data/ 内，随 src 一并进入）。
PACK_DIRS = ["src"]

# 明确排除：不把开发期产物、虚拟环境、git 元数据打进分发包。
EXCLUDE_PARTS = {".venv", "__pycache__", ".git", ".pytest_cache", "out"}


def _should_skip(parts: tuple[str, ...]) -> bool:
    return any(part in EXCLUDE_PARTS for part in parts)


def build_zip(out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in PACK_FILES:
            path = ROOT / name
            if path.exists():
                zf.write(path, arcname=name)

        for dir_name in PACK_DIRS:
            base = ROOT / dir_name
            for path in sorted(base.rglob("*")):
                if path.is_file():
                    parts = path.relative_to(ROOT).parts
                    if _should_skip(parts):
                        continue
                    zf.write(path, arcname=path.relative_to(ROOT).as_posix())

    size_kb = out_path.stat().st_size / 1024
    print(f"已产出 {out_path}（{size_kb:.1f} KB）")


def main() -> None:
    parser = argparse.ArgumentParser(description="打包 MapSmith 为可分发的 zip")
    parser.add_argument("--out", default=str(ROOT / "dist" / "mapsmith.zip"))
    args = parser.parse_args()
    build_zip(Path(args.out))


if __name__ == "__main__":
    main()