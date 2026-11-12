# Map Smith 容器镜像。
#
# 依据：docs/Spec/V0.1-专题制图智能体.md 第 6 节 T23（完成判定：容器可起）
# 与 docs/facts/08-交付形态.md（评委不装 Python 也能运行，规避本机环境差异）。
#
# 构建：docker build -t mapsmith:v0.1.0 .
# 运行：docker compose up（推荐）或
#       docker run --rm -p 8501:8501 mapsmith:v0.1.0
#
# 镜像只包含运行所需内容：src/（源码、demo_data、字体）与 web/dist/（前端构建产物，
# 无需 Node）。依赖按 src/requirements.lock 固定版本安装。

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLCONFIGDIR=/tmp/mpl \
    PYTHONPATH=/app/src

WORKDIR /app

# 先拷锁文件安装依赖，命中层缓存：源码变动不会触发重装。
COPY src/requirements.lock /app/src/requirements.lock
RUN python -m pip install -r /app/src/requirements.lock

COPY src/ /app/src/
COPY web/dist/ /app/web/dist/

# 产物目录（MapSpec 渲染的 PNG / PDF 写入 /app/out），可在运行时挂载持久化。
RUN mkdir -p /app/out
VOLUME ["/app/out"]

EXPOSE 8501

CMD ["python", "-m", "mapsmith", "--host", "0.0.0.0", "--port", "8501"]
