# DanbooruSearchOnline —— CUDA 版 Docker 镜像（默认；含完整 CUDA runtime 的 torch，体积较大）
#   纯 CPU 精简版见同级 docker/Dockerfile.cpu（用 build-docker-cpu 脚本构建）。
#
# 构建（在仓库根目录执行，构建上下文为项目根）：
#   docker build -t danbooru-search-online:latest -f docker/Dockerfile .
# 或用一键脚本： scripts/build-docker.sh  /  scripts/build-docker.ps1
#
# 说明：
#   - 默认（.dockerignore）镜像仅含代码与依赖；bge-m3 模型权重（数 GB）与标签库
#     向量编码缓存不进镜像（保持镜像小巧、构建快速）。运行时两种来源：
#       1) 通过 compose 相对路径目录（docker/model_cache、docker/tags_embedding）挂载；
#       2) 或首次启动自动从 HuggingFace Hub 下载模型并全量编码（见 docs/DOCKER.md）。
#   - 模型与编码缓存都通过 compose 的相对路径目录持久化，首次慢、之后秒级启动。
#   - 基础镜像用 python:3.12-slim（而非 python:3.12）显著缩小体积；slim 缺 libgomp1
#     （torch 运行必需），已在装依赖时一并补上并清理 apt 缓存。
#   - torch 用 --no-deps 从中科大 PyPI 镜像安装（国内快、且该镜像存的是 PyPI 官方包、不走被污染的
#     download.pytorch.org CDN，不会 sha256 失败）：只下 torch 本体（~526MB），不拉 ~2GB 的 nvidia-*
#     CUDA 库（纯 CPU 部署用不到，且下载它们正是之前构建卡半小时的原因）。torch 运行必需的轻量依赖
#     （filelock / typing-extensions / sympy / networkx / jinja2 / fsspec / triton）随后单独补装。
#     注：PyTorch 官方 CPU 专用源（download.pytorch.org/whl/cpu）在本机网络下经透明代理被篡改，pip
#     校验 sha256 失败，故不可用。
#   - modelscope / oss2 不在 Docker 依赖内（代码里均为懒加载，未用到的功能不受影响）。
#   - 容器默认绑定 0.0.0.0:7860（由 platform_utils.get_host_port() 读取环境变量），
#     可直接对外暴露；如需改端口，设置环境变量 DANBOORU_PORT。

FROM python:3.12-slim

WORKDIR /app

# 先装依赖，利用层缓存：仅依赖变更时才重新安装
# 体积与速度优化（纯 CPU 部署，功能不变）：
#   1) --no-deps 装 torch —— 只下 torch 本体（~526MB），不拉官方 CUDA 版自带的 ~2GB nvidia-*
#      GPU 库（纯 CPU 推理用不到，且下载它们正是之前构建卡半小时的原因）；
#      · 若 docker/wheels/ 下存在本地 torch wheel，优先用之安装，彻底绕过容器内慢速下载
#        （通过 BuildKit bind mount 临时挂入，不进镜像层；可放 CPU 版 +cpu wheel 进一步瘦身，
#         宿主机用 `pip download ... --index-url https://download.pytorch.org/whl/cpu/` 预下载）；
#      · 否则回退到中科大 PyPI 镜像（--no-deps）安装。
#   2) 单独补装 torch 运行必需的轻量依赖（filelock / typing-extensions / sympy / networkx /
#      jinja2 / fsspec / triton），CPU 推理无需 nvidia；
#   3) 再装精简版依赖清单（不含 modelscope / oss2，含 sentence-transformers 等），因 torch 已装好
#      且版本满足，pip 不会重复拉 CUDA 版 torch。
# torch 不写在 requirements-docker.txt 内，由本步单独安装。
COPY requirements-docker.txt .
# 可选：宿主机预下载的 wheel（docker/wheels/）通过 BuildKit bind mount 临时挂入，
# 优先本地安装以绕过容器内慢速下载；用 mount（而非 COPY）可避免 wheel 文件留在镜像层
# 导致虚胖。如需进一步瘦身，把 CPU 版 torch wheel（torch-2.13.0+cpu-...-linux_x86_64.whl）
# 放进 docker/wheels/ 即可（详见 docs/DOCKER.md「可选：预下载 wheel 加速 / 换 CPU 版瘦身」）。
RUN --mount=type=bind,source=docker/wheels,target=/wheels,rw \
    apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && (if ls /wheels/torch-*.whl >/dev/null 2>&1; then \
            pip install --no-cache-dir --no-deps /wheels/*.whl; \
        else \
            pip install --no-cache-dir --no-deps -i https://mirrors.ustc.edu.cn/pypi/simple/ --trusted-host mirrors.ustc.edu.cn torch; \
        fi) \
    && pip install --no-cache-dir --progress-bar on -i https://mirrors.ustc.edu.cn/pypi/simple/ --trusted-host mirrors.ustc.edu.cn filelock typing-extensions sympy networkx jinja2 fsspec triton \
    && pip install --no-cache-dir --progress-bar on -i https://mirrors.ustc.edu.cn/pypi/simple/ --trusted-host mirrors.ustc.edu.cn -r requirements-docker.txt

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
# --exclude 目的是把预下载的 torch wheel 目录排除在镜像之外（它已通过上面的 bind mount 安装，
# 不必再打进镜像层造成虚胖）。
COPY --exclude=docker/wheels --exclude=docker/wheels-cpu --chown=user . /app

EXPOSE 7860

CMD ["python", "ui_nicegui.py"]
