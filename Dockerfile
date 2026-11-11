# MapSmith 专题制图 — T23 打包
# 基于 python:3.12-slim；只装 src/requirements.lock 里的依赖，不预装非必需依赖。
# demo_data 位于 src/mapsmith/demo_data/，随 src/ 一并打入镜像，启动时不联网拉数据。

FROM python:3.12-slim

# 中文图例不乱码：固定 UTF-8；关闭 stdout 缓冲与 pip 缓存以减小体积。
ENV PYTHONIOENCODING=utf-8 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src \
    MAPSMITH_OUTPUT_DIR=/app/out \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

# 先装依赖，利用 Docker layer cache（改源码不触发重装依赖）。
# requirements.lock 是 pip freeze 产物，锁死版本保证可复现。
COPY src/requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir -r /app/requirements.lock

# 打源码与 demo_data（demo_data 在 src/mapsmith/demo_data/ 内，随 src 一并进入）。
COPY src /app/src

# 出图目录需可写；默认 /app/out，可用 MAPSMITH_OUTPUT_DIR 覆盖。
RUN mkdir -p /app/out

EXPOSE 8501

# 启动命令与 T22 自检记录一致（python -m streamlit run src/mapsmith/app.py --server.port 8501）。
# --server.address 0.0.0.0 是容器内被宿主机访问所必需；端口可用 PORT 环境变量覆盖，默认 8501。
CMD python -m streamlit run src/mapsmith/app.py --server.port ${PORT:-8501} --server.address 0.0.0.0