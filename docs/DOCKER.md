# Docker 部署指南

本指南说明如何用 Docker 把本项目自托管起来。提供**两种部署方式**与**一键构建脚本**，覆盖本地开发机、内网服务器与云主机。

> 面向最终用户的功能说明见 [README.md](../README.md)；本地（非 Docker）从零跑起见 [DEPLOYMENT.md](./DEPLOYMENT.md)。

---

## 1. 方案概览

| 方式 | 文件 | 适用场景 |
|------|------|----------|
| 自编译（从源码构建镜像） | `docker/docker-compose.build.yml` | 想用最新代码、自己构建镜像 |
| 已有镜像（直接启动） | `docker/docker-compose.pull.yml` | 已构建 / 已从仓库拉取镜像，直接跑 |

两种方式的容器内行为完全一致：`DANBOORU_HOST=0.0.0.0`、`DANBOORU_PORT=7860`，模型与编码缓存通过 named volume 持久化。

---

## 2. 前置要求

- **Docker** 与 **Docker Compose v2**（`docker compose` 子命令）已安装。
- **端口**：默认对外暴露 `7860`（可在 compose 文件或环境变量修改）。
- **模型权重不在镜像内**：`BAAI/bge-m3` 权重数 GB，不进镜像。容器首次启动会自动从 HuggingFace Hub 下载（国内可设 `HF_ENDPOINT=https://hf-mirror.com` 加速），并缓存到 `model_cache` volume。

---

## 3. 一键构建镜像（推荐）

无需手动敲 `docker build`，脚本会自动定位 Dockerfile 与构建上下文：

```bash
# Linux / macOS
./scripts/build-docker.sh

# Windows (PowerShell)
.\scripts\build-docker.ps1
```

**镜像版本号自动获取**（无需手填）：

1. 优先读取仓库根目录 `VERSION` 文件（如 `1.1.6`）；
2. 回退解析 `CHANGELOG.md` 顶部的最新版本号；
3. 都没有则回退 `latest`。

构建产物默认两个标签：

- `danbooru-search-online:<version>`（如 `danbooru-search-online:1.1.6`）
- `danbooru-search-online:latest`（供 `docker-compose.pull.yml` 默认值直接引用）

**自定义镜像名 / 推送到私有仓库**（可选）：

```bash
# bash
DANBOORU_IMAGE="registry.example.com/your-name/danbooru-search-online:1.1.6" \
  ./scripts/build-docker.sh

# PowerShell
$env:DANBOORU_IMAGE="registry.example.com/your-name/danbooru-search-online:1.1.6"
.\scripts\build-docker.ps1
```

---

## 4. 自编译部署（从源码构建并启动）

在**仓库根目录**执行：

```bash
docker compose -f docker/docker-compose.build.yml up -d --build
```

- `build` 段指向 `docker/Dockerfile`，上下文为仓库根（`.dockerignore` 已排除模型权重、编码缓存、`.env` 等）。
- 首次会拉取 `python:3.12` 基础镜像并安装依赖，耗时取决于网速。

---

## 5. 已有镜像部署（直接启动）

若已用第 3 节脚本构建过镜像（或已从仓库拉取），直接启动即可，**不重新构建**：

```bash
# 默认使用本地 danbooru-search-online:latest
docker compose -f docker/docker-compose.pull.yml up -d

# 或指定自定义镜像
DANBOORU_IMAGE="registry.example.com/your-name/danbooru-search-online:1.1.6" \
  docker compose -f docker/docker-compose.pull.yml up -d
```

---

## 6. 环境变量

在 compose 文件或 `docker run -e` 中设置：

| 变量 | 作用 | 默认值（容器） |
|------|------|----------------|
| `DANBOORU_HOST` | 容器内绑定地址；设为 `0.0.0.0` 对外暴露 | `0.0.0.0`（Dockerfile 已设） |
| `DANBOORU_PORT` | 容器内绑定端口 | `7860`（Dockerfile 已设） |
| `HF_ENDPOINT` | HuggingFace 镜像，加速模型下载（如 `https://hf-mirror.com`） | 官方源 |
| `DANBOORU_DEVICE` | 推理设备：`auto` / `cpu` / `cuda` | `auto` |
| `DANBOORU_MODEL_PATH` | 模型目录（容器路径，默认 `/app/model/bge-m3`） | 自动 |
| `DISABLE_NSFW` | 设为 `1` 强制禁用 NSFW | `0` |

> `docker-compose.*.yml` 已通过 `env_file: ../.env`（可选）注入本地 `.env`，也支持在宿主机 shell 用 `HF_ENDPOINT=... DANBOORU_DEVICE=...` 前缀覆盖。

---

## 7. 数据持久化

compose 文件挂载了两个 named volume，避免每次重建镜像 / 重启容器重复下载与编码：

| Volume | 宿主机挂载点（容器路径） | 内容 |
|--------|--------------------------|------|
| `model_cache` | `/app/model` | bge-m3 模型权重（首次下载后持久化） |
| `embedding_cache` | `/app/tags_embedding` | 标签库向量编码缓存（首次全量编码后持久化） |

首次启动会经历：下载模型（数分钟~十几分钟，取决于网速）→ 全量编码（CPU 几十分钟、GPU 几分钟）。之后重启仅需加载缓存，秒级启动。

---

## 8. 访问服务

启动后浏览器打开：

```
http://<你的服务器IP或域名>:7860
```

- Web UI：`/`
- REST API 文档：`/api/docs`
- MCP 端点：`/mcp/mcp`

容器日志可观察启动进度（模型下载、编码层数、进度条）：

```bash
docker logs -f danbooru-search
```

---

## 9. 推送到镜像仓库（可选）

若要分发或部署到其它机器：

```bash
# 打标签（若构建时未指定 DANBOORU_IMAGE）
docker tag danbooru-search-online:latest registry.example.com/your-name/danbooru-search-online:1.1.6
# 推送
docker push registry.example.com/your-name/danbooru-search-online:1.1.6
```

目标机器用 `docker-compose.pull.yml` 并设 `DANBOORU_IMAGE` 指向该地址即可。

---

## 10. 常用命令

```bash
# 启动（后台）
docker compose -f docker/docker-compose.pull.yml up -d
# 停止
docker compose -f docker/docker-compose.pull.yml down
# 查看日志
docker logs -f danbooru-search
# 重启
docker compose -f docker/docker-compose.pull.yml restart
# 删除容器与网络（保留 volume 数据）
docker compose -f docker/docker-compose.pull.yml down
# 彻底清理（含 volume，会丢失模型与编码缓存，需重新下载/编码）
docker compose -f docker/docker-compose.pull.yml down -v
```

---

## 11. 故障排查

**Q：访问 `:7860` 一直转圈 / 空白？**
A：多半是首次启动仍在下载模型或全量编码。用 `docker logs -f danbooru-search` 查看是否出现 `[Engine] ▶ 第 1/4 层` 进度条或模型下载日志。编码完成前服务不可用属正常。

**Q：模型下载极慢或失败？**
A：设置 `HF_ENDPOINT=https://hf-mirror.com`（国内镜像）后重启容器；或将模型预先放到宿主机的 volume 对应目录，避免重复下载。

**Q：改了代码后镜像没更新？**
A：自编译方式需带 `--build`（`docker compose -f docker/docker-compose.build.yml up -d --build`）；已有镜像方式需重新跑构建脚本生成新镜像，再 `up -d`。

**Q：容器退出 / 重启循环？**
A：检查 `docker logs danbooru-search` 是否有 Python 启动错误（如端口被占用、依赖缺失）。`restart: unless-stopped` 会在异常时尝试重启。

**Q：想用非 7860 端口？**
A：修改 compose 文件 `ports: - "新端口:7860"`（左侧宿主机端口），或改 `DANBOORU_PORT` 同时调整右侧容器端口。
