#!/usr/bin/env bash
# DanbooruSearchOnline —— CUDA 版构建（等价于 build-docker.sh）
#
# 本脚本直接转发到 build-docker.sh（CUDA 版，默认含完整 CUDA runtime 的 torch，
# 镜像较大、纯 CPU 推理用不到 GPU 部分）。若只需纯 CPU 精简镜像，请用 build-docker-cpu.sh。
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/build-docker.sh" "$@"
