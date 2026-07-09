#!/usr/bin/env bash
# DanbooruSearchOnline —— 一键构建最新 Docker 镜像（Linux / macOS）
#
# 用法：
#   ./scripts/build-docker.sh                    # 使用默认标签（版本号自动获取）
#   DANBOORU_IMAGE="myrepo/danbooru:1.0" \       # 可选：自定义镜像名（含仓库/标签）
#     ./scripts/build-docker.sh
#
# 版本号自动获取规则：
#   1) 优先读取仓库根目录 VERSION 文件（如 1.1.6）；
#   2) 回退解析 CHANGELOG.md 顶部的最新版本号；
#   3) 都没有则回退 latest。
# 默认镜像标签为 danbooru-search-online:<version>，并同时打 danbooru-search-online:latest，
# 以便 docker-compose.pull.yml 的默认值可直接使用。
#
# 说明：构建上下文为仓库根目录，Dockerfile 位于 docker/Dockerfile。
#       镜像只含代码与依赖，模型权重与编码缓存在首次运行时下载/生成并挂载持久化。

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

IMAGE="${DANBOORU_IMAGE:-$DEFAULT_IMAGE}"

echo "=> 构建镜像：$IMAGE  (版本来源: $VERSION)"
echo "   上下文(context): $ROOT"
echo "   Dockerfile    : $DOCKERFILE"

docker build -t "$IMAGE" -t "danbooru-search-online:latest" -f "$DOCKERFILE" "$ROOT"

echo ""
echo "=> 构建完成。"
echo "   自编译启动 : docker compose -f docker/docker-compose.build.yml up -d --build"
echo "   已有镜像启动: docker compose -f docker/docker-compose.pull.yml up -d"
