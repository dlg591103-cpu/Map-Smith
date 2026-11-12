#!/usr/bin/env bash
# Map Smith 一键启动脚本（跨平台，bash）。
#
# 依据：docs/Spec/V0.1-专题制图智能体.md 第 6 节 T23（完成判定：解压即可运行）
# 与 docs/facts/08-交付形态.md（zip 包含一键启动脚本）。
#
# 用法：解压后在项目根目录执行
#   ./run.sh                  # 默认 127.0.0.1:8501
#   ./run.sh --port 9000      # 指定端口
#   ./run.sh --host 0.0.0.0
#
# 脚本做三件事：
#   1. 定位 Python 3.12 解释器（优先环境变量 MAPSMITH_PYTHON，其次 .venv、python3）；
#   2. 首次运行时创建 .venv 并按 src/requirements.lock 安装依赖；
#   3. 以 python -m mapsmith 启动 Web 服务（T22 第二段入口，前端已随仓库构建）。

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
venv_dir="$root/.venv"
venv_python="$venv_dir/bin/python"
lock_file="$root/src/requirements.lock"

step() { echo "[run.sh] $*"; }

is_python312() {
    # 检查什么：解释器存在且版本为 3.12+（SPEC 第 5 节要求 Python 3.12）。
    "$1" --version 2>/dev/null | grep -Eq '^Python 3\.([2-9][0-9]|[1-9][0-9]{2})\.' || return 1
}

find_interpreter() {
    # 1) 用户显式指定（环境变量 MAPSMITH_PYTHON，绝对路径）。
    if [ -n "${MAPSMITH_PYTHON:-}" ] && [ -x "${MAPSMITH_PYTHON}" ] && is_python312 "${MAPSMITH_PYTHON}"; then
        printf '%s' "${MAPSMITH_PYTHON}"
        return 0
    fi
    # 2) 本项目已创建的 venv。
    if [ -x "$venv_python" ]; then
        printf '%s' "$venv_python"
        return 0
    fi
    # 3) PATH 中的 python3 / python。
    for cmd in python3 python; do
        if command -v "$cmd" >/dev/null 2>&1 && is_python312 "$(command -v "$cmd")"; then
            printf '%s' "$(command -v "$cmd")"
            return 0
        fi
    done
    return 1
}

python_bin="$(find_interpreter)" || {
    echo "[run.sh] 未找到 Python 3.12 解释器。" >&2
    echo "[run.sh] 请安装 Python 3.12 后重试，或用环境变量显式指定：" >&2
    echo '[run.sh]   export MAPSMITH_PYTHON=/path/to/python3.12' >&2
    exit 1
}
step "解释器：$python_bin"

# 依赖安装（首次运行）：.venv 不存在时创建并按锁文件安装。
if [ ! -x "$venv_python" ]; then
    step "创建虚拟环境 .venv ..."
    "$python_bin" -m venv "$venv_dir"
fi

if ! "$venv_python" -c "import mapsmith" >/dev/null 2>&1; then
    step "按 src/requirements.lock 安装依赖（首次运行需数分钟）..."
    "$venv_python" -m pip install -r "$lock_file"
fi

# 将 src/ 加入可导入路径：不修改包内代码，运行期注入。
export PYTHONPATH="$root/src"
host="127.0.0.1"
port="8501"
while [ $# -gt 0 ]; do
    case "$1" in
        --host) host="${2:?缺少 --host 的值}"; shift 2 ;;
        --port) port="${2:?缺少 --port 的值}"; shift 2 ;;
        *) echo "[run.sh] 未知参数：$1（可用 --host / --port）" >&2; exit 1 ;;
    esac
done

step "启动 Map Smith Web 服务：http://$host:$port"
exec "$venv_python" -m mapsmith --host "$host" --port "$port"
