# DanbooruSearchOnline —— 自托管 Docker 镜像
#
# 构建（在仓库根目录执行，构建上下文为项目根）：
#   docker build -t danbooru-search-online:latest -f docker/Dockerfile .
# 或用一键脚本： scripts/build-docker.sh  /  scripts/build-docker.ps1
#
# 说明：
#   - 镜像仅包含代码与依赖；bge-m3 模型权重（数 GB）与标签库向量编码缓存
#     不进镜像（见 .dockerignore），运行时自动下载模型并首次全量编码。
#   - 模型与编码缓存通过 docker-compose 的 named volume 持久化，首次慢、之后秒级启动。
#   - 容器默认绑定 0.0.0.0:7860（由 platform_utils.get_host_port() 读取环境变量），
#     可直接对外暴露；如需改端口，设置环境变量 DANBOORU_PORT。

FROM python:3.12

WORKDIR /app

# 先装依赖，利用层缓存：仅依赖变更时才重新安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 非 root 用户运行
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    # Docker 部署默认值：对外暴露 0.0.0.0:7860（可被 get_host_port() 读取覆盖）
    DANBOORU_HOST=0.0.0.0 \
    DANBOORU_PORT=7860

# 复制项目代码（模型权重与编码缓存已通过 .dockerignore 排除）
COPY --chown=user . /app

EXPOSE 7860

CMD ["python", "ui_nicegui.py"]
