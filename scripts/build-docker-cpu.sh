#!/usr/bin/env bash
# DanbooruSearchOnline —— 一键构建纯 CPU 版 Docker 镜像（Linux / macOS）
#
# 与 build-docker.sh（CUDA 版）的区别：本脚本先用宿主机网络从 PyTorch 官方 CPU 源
# 预下载 torch 2.13.0+cpu wheel 到 docker/wheels-cpu/（容器内访问该源会被透明代理篡改、
# pip 校验 sha256 失败，故必须在宿主机下），再由 docker/Dockerfile.cpu 通过 bind mount
# 挂入安装，得到不含 CUDA runtime 的精简镜像（约 1.6GB，而非 CUDA 版约 2.9GB）。
#
# 用法：
#   ./scripts/build-docker-cpu.sh                  # 构建纯 CPU 版镜像（自动预下载 +cpu wheel）
#   DANBOURU_IMAGE="myrepo/danbooru-cpu:1.0" \     # 可选：自定义镜像名（含仓库/标签）
#     ./scripts/build-docker-cpu.sh
#
# 版本号自动获取规则：
#   1) 优先读取仓库根目录 VERSION 文件（如 1.1.6）；
#   2) 回退解析 CHANGELOG.md 顶部的最新版本号；
#   3) 都没有则回退 latest。
# 默认标签 danbooru-search-online-cpu:<version> 与 :latest（与 CUDA 版镜像名区分，可共存）。

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOCKERFILE="$(cd "$(dirname "$0")/../docker" && pwd)/Dockerfile.cpu"
WHEELS_DIR="$ROOT/docker/wheels-cpu"
TORCH_VER="2.13.0+cpu"

# 版本号：优先 VERSION 文件，回退解析 CHANGELOG.md 顶部最新版本
if [[ -f "$ROOT/VERSION" ]]; then
  VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
else
  VERSION="$(grep -m1 -oE 'v[0-9]+\.[0-9]+\.[0-9]+' "$ROOT/CHANGELOG.md" | head -1 | tr -d v)"
fi
VERSION="${VERSION:-latest}"

DEFAULT_IMAGE="danbooru-search-online-cpu:${VERSION}"
SECOND_TAG="danbooru-search-online-cpu:latest"
IMAGE="${DANBOURU_IMAGE:-$DEFAULT_IMAGE}"

# 解析 pip 命令（优先 python -m pip，回退 python3 / pip），适配不同机器上解释器名字不同
if command -v python >/dev/null 2>&1; then PIP="python -m pip"
elif command -v python3 >/dev/null 2>&1; then PIP="python3 -m pip"
elif command -v pip >/dev/null 2>&1; then PIP="pip"
else
  echo "=> 未找到 python / python3 / pip，无法预下载 torch +cpu wheel。" >&2
  echo "   请先安装 Python 并加入 PATH；或手动把 torch-${TORCH_VER}-cp312-cp312-manylinux_2_28_x86_64.whl" >&2
  echo "   放入 docker/wheels-cpu/ 后重试本脚本。" >&2
  exit 1
fi

# ── 步骤 1：宿主机预下载 torch +cpu wheel（容器内被代理篡改，必须在宿主机下）──
# 仅当 docker/wheels-cpu/ 下没有匹配的 +cpu wheel 时才下载，避免重复拉取。
echo "=> 准备 torch 纯 CPU 版 wheel（若已存在则跳过下载）"
mkdir -p "$WHEELS_DIR"
if ls "$WHEELS_DIR"/torch-*+cpu*.whl >/dev/null 2>&1; then
  echo "   已存在：$(ls "$WHEELS_DIR"/torch-*+cpu*.whl | head -1 | xargs basename)，跳过下载。"
else
  echo "   从 PyTorch 官方 CPU 源下载 torch==$TORCH_VER 的 Linux wheel ..."
  # 宿主机网络对该源正常；必须加 --platform manylinux_2_28_x86_64 --python-version 312 --only-binary=:all:
  # 否则在 macOS/非 Linux 宿主机上会下到错误平台的包。
  $PIP download "torch==$TORCH_VER" --no-deps \
    -d "$WHEELS_DIR" --platform manylinux_2_28_x86_64 --python-version 312 --only-binary=:all: \
    --index-url https://download.pytorch.org/whl/cpu/ \
    --retries 5 --timeout 120
  echo "   下载完成，已存入 $WHEELS_DIR"
fi

# ── 步骤 2：构建镜像（Dockerfile.cpu 通过 bind mount 挂入上面的 wheel）──
echo "=> 构建纯 CPU 版镜像：$IMAGE  (版本来源: $VERSION)"
echo "   上下文(context): $ROOT"
echo "   Dockerfile    : $DOCKERFILE"

# --progress=plain 让 BuildKit 输出原始逐行日志，pip 下载进度（torch 的 MB 进度）实时可见
docker build --progress=plain -t "$IMAGE" -t "$SECOND_TAG" -f "$DOCKERFILE" "$ROOT"

# 导出镜像为 .tar 文件（便于离线分发 / 搬运到其它机器）
TAR_PATH="$ROOT/danbooru-search-online-cpu-${VERSION}.tar"
echo "=> 导出镜像为 tar 包：$TAR_PATH"
docker save "$IMAGE" -o "$TAR_PATH"
echo "   已生成: $TAR_PATH （其它机器用 'docker load -i $TAR_PATH' 导入）"

echo ""
echo "=> 构建完成（纯 CPU 版，不含 CUDA runtime）。"
echo "   自编译启动 : docker compose -f docker/docker-compose.build.yml up -d --build"
echo "   已有镜像启动: docker compose -f docker/docker-compose.pull.yml up -d"
