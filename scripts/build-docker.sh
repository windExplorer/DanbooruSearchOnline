#!/usr/bin/env bash
# DanbooruSearchOnline —— 一键构建最新 Docker 镜像（Linux / macOS）
#
# 用法：
#   ./scripts/build-docker.sh                    # 构建镜像（仅代码+依赖）
#   DANBOURU_IMAGE="myrepo/danbooru:1.0" \       # 可选：自定义镜像名（含仓库/标签）
#     ./scripts/build-docker.sh
#
# 关于镜像体积：bge-m3 模型权重（数 GB）与标签库编码缓存不进镜像
# （见 .dockerignore），镜像小、构建快。运行时通过 compose 挂载本地模型/缓存，
# 或首次启动自动下载模型并编码。详见 docs/DOCKER.md 的「离线准备」章节。
#
# 版本号自动获取规则：
#   1) 优先读取仓库根目录 VERSION 文件（如 1.1.6）；
#   2) 回退解析 CHANGELOG.md 顶部的最新版本号；
#   3) 都没有则回退 latest。
# 默认标签 danbooru-search-online:<version> 与 :latest。
#
# 说明：构建上下文为仓库根目录，Dockerfile 位于 docker/Dockerfile。

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOCKERFILE="$(cd "$(dirname "$0")/../docker" && pwd)/Dockerfile"

# 版本号：优先 VERSION 文件，回退解析 CHANGELOG.md 顶部最新版本
if [[ -f "$ROOT/VERSION" ]]; then
  VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
else
  VERSION="$(grep -m1 -oE 'v[0-9]+\.[0-9]+\.[0-9]+' "$ROOT/CHANGELOG.md" | head -1 | tr -d v)"
fi
VERSION="${VERSION:-latest}"

DEFAULT_IMAGE="danbooru-search-online:${VERSION}"
SECOND_TAG="danbooru-search-online:latest"
IMAGE="${DANBOURU_IMAGE:-$DEFAULT_IMAGE}"

echo "=> 构建镜像：$IMAGE  (版本来源: $VERSION)"
echo "   上下文(context): $ROOT"
echo "   Dockerfile    : $DOCKERFILE"

# --progress=plain 让 BuildKit 输出原始逐行日志，pip 下载进度（torch / nvidia-* 的 MB 进度）实时可见
docker build --progress=plain -t "$IMAGE" -t "$SECOND_TAG" -f "$DOCKERFILE" "$ROOT"

# 导出镜像为 .tar 文件（便于离线分发 / 搬运到其它机器）
TAR_PATH="$ROOT/danbooru-search-online-${VERSION}.tar"
echo "=> 导出镜像为 tar 包：$TAR_PATH"
docker save "$IMAGE" -o "$TAR_PATH"
echo "   已生成: $TAR_PATH （其它机器用 'docker load -i $TAR_PATH' 导入）"

echo ""
echo "=> 构建完成。"
echo "   自编译启动 : docker compose -f docker/docker-compose.build.yml up -d --build"
echo "   已有镜像启动: docker compose -f docker/docker-compose.pull.yml up -d"
