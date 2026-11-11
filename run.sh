#!/usr/bin/env bash
# MapSmith 一键启动脚本（Linux / macOS）
# 用法：bash run.sh
# 步骤：检查解释器 -> 一次性装依赖 -> 启动 streamlit
# 端口可用 PORT 环境变量覆盖（默认 8501）：PORT=9000 bash run.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PORT="${PORT:-8501}"
VENV_DIR="$ROOT/.venv"
PYTHON="$VENV_DIR/bin/python"

# 1. 检查解释器：优先用已存在的 .venv，否则用系统 python3 创建。
if [ ! -x "$PYTHON" ]; then
    echo "未找到虚拟环境，尝试用系统 python3 创建 .venv ..."
    if ! command -v python3 >/dev/null 2>&1; then
        echo "错误：未找到 Python 解释器。请先安装 Python 3.12。" >&2
        exit 1
    fi
    python3 -m venv "$VENV_DIR"
fi

# 2. 一次性装依赖：用标记文件判断，已装过则跳过。
MARKER="$VENV_DIR/.deps_installed"
if [ ! -f "$MARKER" ]; then
    echo "安装依赖（src/requirements.lock）..."
    "$PYTHON" -m pip install --upgrade pip
    "$PYTHON" -m pip install -r "$ROOT/src/requirements.lock"
    touch "$MARKER"
fi

# 3. 启动 streamlit（启动命令与 T22 自检记录一致）。
# 设 headless 跳过首次启动的 email onboarding 询问（不改启动命令，仅加环境变量）。
export STREAMLIT_SERVER_HEADLESS=true
export STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
# mapsmith 包在 src/ 下，streamlit 只会把脚本父目录加入 sys.path，需显式把 src/ 放入 PYTHONPATH。
export PYTHONPATH="$ROOT/src"
echo "启动 MapSmith：http://localhost:$PORT"
exec "$PYTHON" -m streamlit run src/mapsmith/app.py --server.port "$PORT"