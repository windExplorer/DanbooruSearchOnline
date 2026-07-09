# Docker 部署指南

本指南说明如何用 Docker 把本项目自托管起来。提供**两种部署方式**与**一键构建脚本**，覆盖本地开发机、内网服务器与云主机。

> 面向最终用户的功能说明见 [README.md](../README.md)；本地（非 Docker）从零跑起见 [DEPLOYMENT.md](./DEPLOYMENT.md)。

---

## 1. 方案概览

| 方式 | 文件 | 适用场景 |
|------|------|----------|
| 自编译（从源码构建镜像） | `docker/docker-compose.build.yml` | 想用最新代码、自己构建镜像 |
| 已有镜像（直接启动） | `docker/docker-compose.pull.yml` | 已构建 / 已从仓库拉取镜像，直接跑 |

两种方式的容器内行为完全一致：`DANBOORU_HOST=0.0.0.0`、`DANBOORU_PORT=7860`，模型与编码缓存通过相对路径目录持久化。

---

## 2. 前置要求

- **Docker** 与 **Docker Compose v2**（`docker compose` 子命令）已安装。
- **端口**：默认对外暴露 `7860`（可在 compose 文件或环境变量修改）。
- **模型权重不在镜像内**：`BAAI/bge-m3` 权重数 GB，不进镜像。容器首次启动会自动从 HuggingFace Hub 下载（国内可设 `HF_ENDPOINT=https://hf-mirror.com` 加速），并缓存到 `model_cache` volume。

---

## 3. 一键构建镜像（推荐）

无需手动敲 `docker build`，脚本会自动定位 Dockerfile 与构建上下文。提供 **CUDA 版** 与 **纯 CPU 版** 两套脚本：

```bash
# ── CUDA 版（默认，含完整 CUDA runtime，镜像较大 ~2.9GB）──
# Linux / macOS
./scripts/build-docker.sh            # 或 ./scripts/build-docker-cuda.sh
# Windows (PowerShell)
.\scripts\build-docker.ps1           # 或 .\scripts\build-docker-cuda.ps1

# ── 纯 CPU 版（不含 CUDA runtime，镜像更小 ~750MB，纯 CPU 推理足够）──
# Linux / macOS
./scripts/build-docker-cpu.sh
# Windows (PowerShell)
.\scripts\build-docker-cpu.ps1
```

- **CUDA 版**：用 `docker/Dockerfile`（默认 torch 2.13.0 CUDA 版）；镜像标签 `danbooru-search-online:<version>` 与 `:latest`。
- **纯 CPU 版**：用 `docker/Dockerfile.cpu`（torch 2.13.0+cpu）；脚本会先**在宿主机**从 PyTorch 官方 CPU 源预下载 `+cpu` wheel 到 `docker/wheels-cpu/`（容器内访问该源会被透明代理篡改、sha256 校验失败，故必须在宿主机下），再构建。镜像标签 `danbooru-search-online-cpu:<version>` 与 `:latest`（与 CUDA 版区分，二者可共存于同一台机器）。

**镜像版本号自动获取**（无需手填）：

1. 优先读取仓库根目录 `VERSION` 文件（如 `1.1.6`）；
2. 回退解析 `CHANGELOG.md` 顶部的最新版本号；
3. 都没有则回退 `latest`。

构建产物默认两个标签（CUDA 版 / 纯 CPU 版各自的前缀分别为 `danbooru-search-online` / `danbooru-search-online-cpu`）：

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

**构建产物（纯 CPU 版）**：`build-docker-cpu` 脚本在 `docker build` 成功后会自动执行 `docker save`，把镜像导出为仓库根目录的 `danbooru-search-online-cpu-<version>.tar`（如 `danbooru-search-online-cpu-1.1.6.tar`），**便于离线拷贝到其它机器**；导出完成后脚本默认 `docker rmi -f` 删除本地 docker 中的构建镜像，**只保留 tar 文件**（避免镜像堆积占用本地磁盘）。若本机也要直接 `docker compose up` 跑该镜像，请设环境变量 `DOCKER_KEEP_IMAGE=1` 保留它。

**构建脚本可用环境变量开关**：

| 变量 | 作用 |
|------|------|
| `DANBOURU_IMAGE` | 自定义镜像名（含仓库/标签），覆盖默认 `danbooru-search-online-cpu:<version>` |
| `DOCKER_BUILD_NO_CACHE` | 设为 `1`：构建加 `--no-cache` 完全从头重构（最干净、避免命中旧缓存层，但更慢） |
| `DOCKER_BUILD_PRUNE_ALL` | 设为 `1`：构建后 `docker builder prune -a -f` 彻底清空所有 BuildKit 构建缓存（当镜像体积异常偏大、疑似命中历史大缓存层时使用；下次构建会重新拉取基础镜像/依赖） |
| `DOCKER_KEEP_IMAGE` | 设为 `1`：导出 tar 后保留本地 docker 镜像（默认导出后即删除，仅留 tar） |

> 若导出的 tar 比预期（约 750MB）大很多（如 1.4GB+、或逐次翻倍到 2GB+），**根因是上次导出的 `*.tar` 落在项目根（即构建上下文），被 `COPY . /app` 打进了新镜像层**。现已在 `.dockerignore` 排除 `*.tar` / `*.tar.gz` / `*.tgz` 根治；若仍异常，先删掉根目录的旧 `danbooru-search-online-cpu-*.tar` 再重建。`DOCKER_BUILD_NO_CACHE=1` / `DOCKER_BUILD_PRUNE_ALL=1` 仅用于清理 BuildKit 构建缓存释放磁盘，与「tar 翻倍」无直接关系。

## 4. 自编译部署（从源码构建并启动）

在**仓库根目录**执行：

```bash
docker compose -f docker/docker-compose.build.yml up -d --build
```

- `build` 段指向 `docker/Dockerfile`，上下文为仓库根（`.dockerignore` 已排除模型权重、编码缓存、`.env` 等）。
- 首次会拉取 `python:3.12-slim` 基础镜像并安装依赖（依赖清单见 `requirements-docker.txt`，已不含 `modelscope`/`oss2` 等懒加载可选包以缩小体积），耗时取决于网速。
- **torch 用 `--no-deps` 走中科大 PyPI 镜像安装**：`Dockerfile` 先通过 `-i https://mirrors.ustc.edu.cn/pypi/simple/` 用中科大镜像 `--no-deps` 装 `torch`（**只下 torch 本体 ~526MB，不拉官方 CUDA 版自带的 ~2GB `nvidia-*` GPU 库**——纯 CPU 部署用不到，且下载它们正是之前构建卡半小时的原因）。随后单独补装 torch 运行必需的轻量依赖（`filelock` / `typing-extensions` / `sympy` / `networkx` / `jinja2` / `fsspec` / `triton`）。用中科大镜像是因为**国内可达**，且该镜像存的是 PyPI 官方包、**不走被污染的 `download.pytorch.org` CDN**，不会 sha256 失败。`torch` 不写在 `requirements-docker.txt` 内、由 `Dockerfile` 单独安装；清单里的 `sentence-transformers` 依赖 torch，因 torch 已装好且版本满足，pip 不会重复拉 CUDA 版。构建日志中**不再出现 `nvidia-*` 下载**，且无需再卸 nvidia。注意：**PyTorch 官方 CPU 专用源（`download.pytorch.org/whl/cpu`）在容器内访问会被透明代理篡改、pip 校验 sha256 失败，故不能在容器内直接装 CPU 版**；但**宿主机网络访问该源正常**（实测可达、未被篡改），因此纯 CPU 版（`docker/Dockerfile.cpu` + `build-docker-cpu` 脚本）改为**在宿主机预下载 `+cpu` wheel 再 bind mount 进容器安装**。
- **（可选）宿主机预下载 wheel 加速（CUDA 版）**：若容器内 pip 下载慢，可在宿主机先把 **CUDA 版** torch wheel 下好放进 `docker/wheels/`，构建时 `Dockerfile` 通过 BuildKit `bind mount` 临时挂入并优先安装（**不会留在镜像层，不会虚胖**）。宿主机若是 Windows/macOS，`pip download` **必须**加 `--platform manylinux_2_28_x86_64 --python-version 312 --only-binary=:all:`，否则会下到错误平台的包。示例（在仓库根目录执行）：
  ```bash
  # 仅加速（CUDA 版，镜像体积不变 ~2.9GB）
  pip download torch==2.13.0 --no-deps -d docker/wheels --platform manylinux_2_28_x86_64 --python-version 312 --only-binary=:all: -i https://mirrors.ustc.edu.cn/pypi/simple/ --trusted-host mirrors.ustc.edu.cn
  ```
  预下载后正常 `.\scripts\build-docker.ps1` 即可；若想联网回退（不用本地 wheel），清空 `docker/wheels/` 下的 `*.whl` 即可。`.whl` 已被 `.gitignore` 忽略，不会误提交。
- **（推荐）纯 CPU 版瘦身（约 750MB）**：无需手动操作，直接跑 `build-docker-cpu` 脚本即可。它会**在宿主机**从 PyTorch 官方 CPU 源预下载 `torch-2.13.0+cpu-...-manylinux_2_28_x86_64.whl`（~190MB，不含 CUDA kernel 代码）到 `docker/wheels-cpu/`，再由 `docker/Dockerfile.cpu` 通过 bind mount 挂入安装，**保持 torch 2.13.0 不降级**即可把镜像从 ~2.9GB 降到 ~750MB，纯 CPU 部署功能不变、启动更快。脚本会自动跳过已下载的 wheel，重复构建不会重新拉取。若需手动预下载（等价操作）：
  ```bash
  # 纯 CPU 版 wheel（宿主机网络对官方 CPU 源正常；容器内访问会被代理篡改故必须宿主机下）
  pip download torch==2.13.0+cpu --no-deps -d docker/wheels-cpu --platform manylinux_2_28_x86_64 --python-version 312 --only-binary=:all: --index-url https://download.pytorch.org/whl/cpu/
  ```
  ⚠️ 注意：仅 `docker/wheels-cpu/` 下的 `+cpu` wheel 会被 CPU 版构建使用；CUDA 版的 `docker/wheels/` 与 CPU 版互不干扰。若 `Dockerfile.cpu` 构建报「未找到 +cpu wheel」，说明宿主机预下载未成功，请先运行 `.\scripts\build-docker-cpu.ps1`。

---

## 5. 已有镜像部署（直接启动，无需仓库源码）

`docker-compose.pull.yml` 是**生产部署件**：它只引用镜像与相对路径数据目录，可以**单独拷到目标机器**，不需要整个 Git 仓库。前提是镜像已存在（本地构建过，或从镜像仓库拉取）。

```bash
# 1) 把 docker-compose.pull.yml 拷到服务器任意目录（如 /opt/danbooru/）
# 2) 进入该目录，启动即可；./model_cache、./tags_embedding 会自动创建
cd /opt/danbooru
docker compose -f docker-compose.pull.yml up -d

# 使用私有仓库镜像（镜像需先在目标机可拉取，例如已 docker pull 或配置好 registry 凭据）
DANBOORU_IMAGE="registry.example.com/your-name/danbooru-search-online:1.1.6" \
  docker compose -f docker-compose.pull.yml up -d
```

#### 从 tar 文件导入镜像（离线分发）

若目标机器无法访问镜像仓库，或你手里是构建脚本导出的 `danbooru-search-online-cpu-<version>.tar`，先在目标机导入镜像，再启动：

```bash
# 把 tar 与 docker-compose.pull.yml 一起拷到目标机（如 /opt/danbooru/）
docker load -i danbooru-search-online-cpu-1.1.6.tar
# 导入后本地即存在 danbooru-search-online-cpu:1.1.6，直接启动即可
cd /opt/danbooru
docker compose -f docker-compose.pull.yml up -d
```

> 相对挂载路径（`./model_cache`、`./tags_embedding`）以本 compose 文件所在目录为基准，所以数据目录会建在 compose 文件旁边，自包含、可随目录整体迁移。

> 与之相对，`docker-compose.build.yml` 是**构建辅助**（从源码 `build`，需要整仓库作为上下文），用于本地 / CI 造镜像，不属于部署文件。

### 5.1 离线准备：提前下载模型与复用本地缓存

镜像故意**不含**模型权重与编码缓存（光 `BAAI/bge-m3` 就 2GB+，打进镜像既臃肿又拖慢构建）。运行时靠挂载目录或自动下载拿到它们。如果你网络不稳、或本地已经有缓存，建议**提前准备、挂载复用**，首次启动即可秒级加载、跳过下载与 CPU 编码。

两类资产与挂载对应关系：

| 资产 | 宿主机目录（相对 compose 文件） | 容器内路径 | 作用 |
|------|--------------------------------|------------|------|
| bge-m3 模型权重 | `docker/model_cache/bge-m3/` | `/app/model/bge-m3` | 语义向量模型，缺失时才自动下载 |
| 标签库编码缓存 | `docker/tags_embedding/` | `/app/tags_embedding` | 四路向量矩阵等；三个文件齐全则直接加载，跳过编码 |

> 下方命令里的 `docker/` 都是指 compose 文件所在目录（即 `docker/`）。若你把 compose 拷到了 `/opt/danbooru/`，那这几个目录就建在 `/opt/danbooru/` 旁边。

#### A. 提前下载模型（推荐，避免容器内下载慢/失败）

模型来源 `BAAI/bge-m3`，任一方式下载到本地后，放到 `docker/model_cache/bge-m3/`（即挂载目录里），容器启动会优先用它、不再联网：

```bash
# 方式一：HuggingFace（官方，需先装 huggingface_hub）
huggingface-cli download BAAI/bge-m3 --local-dir docker/model_cache/bge-m3

# 方式二：ModelScope 魔搭（国内推荐，需先 pip install modelscope）
modelscope download --model BAAI/bge-m3 --local_dir docker/model_cache/bge-m3

# 国内加速 HuggingFace 源（先设镜像再下）
HF_ENDPOINT=https://hf-mirror.com \
  huggingface-cli download BAAI/bge-m3 --local-dir docker/model_cache/bge-m3
```

下载完成后目录结构应为：

```
docker/model_cache/bge-m3/
├── config.json
├── model.safetensors        （或 pytorch_model.bin）
├── tokenizer.json
├── tokenizer_config.json
├── special_tokens_map.json
├── modules.json
└── 1_Pooling/               （若模型包含）
```

> 也可用 git 方式（`git lfs install` 后 `git clone`），或更完整的下载 / 放置说明见 [`model/README.md`](../model/README.md)。
> 若你的模型在别的盘，不必复制：直接改 compose 的 `volumes` 把你的目录挂成 `/app/model/bge-m3`，或设置环境变量 `DANBOORU_MODEL_PATH` 指向容器内路径即可。

#### B. 复用本地已有的编码缓存（跳过 CPU 编码）

编码缓存由首次运行用模型对全量标签做向量编码**生成**（CPU 较慢），生成后持久化到 `docker/tags_embedding/`。三种复用方式：

1. **直接沿用**：上一次 `docker compose up` 已经生成过 `docker/tags_embedding/`，重启自动命中，无需任何操作。
2. **拷贝复用**：你在本机非 Docker 跑过本项目，根目录有 `tags_embedding/` 文件夹，整目录拷到 `docker/tags_embedding/` 即可。
3. **挂载复用**：缓存在别的盘，改 compose 把你的目录挂成 `/app/tags_embedding`。

缓存目录必须**同时包含以下三个文件**（缺一则判定为「无缓存」，会重新编码）：

```
docker/tags_embedding/
├── danbooru_multiview_embeddings.safetensors   # 四路向量矩阵
├── tags_metadata.parquet                       # 标签元数据
└── version_data.json                           # 版本信息
```

> ⚠️ **版本匹配**：`version_data.json` 里的 `schema_version` 必须与镜像代码的 `SCHEMA_VERSION` 一致（当前为 `4`），否则会被判定「格式不符」而触发全量重建（又会跑一次编码）。用同版本镜像/代码生成的缓存最稳。

#### C. 验证是否生效

启动后用日志确认走的是「加载缓存」而非「下载/编码」：

```bash
docker logs -f danbooru-search
# 命中本地模型与缓存时，应看到类似：
#   [PlatformUtils] 使用本地模型: /app/model/bge-m3
#   [Engine] 加载缓存 (/app/tags_embedding) ...
# 而非漫长的模型下载或 [Engine] 未找到缓存，开始首次构建
```

---

## 6. 环境变量

所有运行环境变量都已**直接写在 compose 文件**的 `environment:` 段里，无需 `.env` 文件。如需修改，直接编辑 `docker/docker-compose.*.yml` 或启动时用 shell 前缀覆盖：

```bash
DANBOORU_DEVICE=cpu HF_ENDPOINT=https://hf-mirror.com \
  docker compose -f docker/docker-compose.pull.yml up -d
```

| 变量 | 作用 | 默认值（compose 内） |
|------|------|----------------------|
| `DANBOORU_HOST` | 容器内绑定地址；设为 `0.0.0.0` 对外暴露 | `0.0.0.0` |
| `DANBOORU_PORT` | 容器内绑定端口 | `7860` |
| `HF_ENDPOINT` | HuggingFace 镜像，加速模型下载（如 `https://hf-mirror.com`） | `https://hf-mirror.com` |
| `DANBOORU_DEVICE` | 推理设备：`auto` / `cpu` / `cuda` | `auto` |
| `DANBOORU_MODEL_PATH` | 模型目录（容器内路径，默认 `/app/model/bge-m3`） | 自动 |



| `DISABLE_NSFW` | 设为 `1` 强制禁用 NSFW | `0` |


---

## 7. 数据持久化

compose 文件挂载了两个**相对路径目录**（相对本 compose 文件所在的 `docker/` 目录，首次运行自动创建），避免每次重建镜像 / 重启容器重复下载与编码：

| 宿主机目录 | 容器路径 | 内容 |
|------------|----------|------|
| `docker/model_cache` | `/app/model` | bge-m3 模型权重（首次下载后持久化） |
| `docker/tags_embedding` | `/app/tags_embedding` | 标签库向量编码缓存（首次全量编码后持久化） |

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
A：优先参考第 5.1 节**提前下载模型**到 `docker/model_cache/bge-m3/` 再启动；或设置 `HF_ENDPOINT=https://hf-mirror.com`（国内镜像）后重启容器。已放好的模型会被直接复用，不再联网下载。

**Q：改了代码后镜像没更新？**
A：自编译方式需带 `--build`（`docker compose -f docker/docker-compose.build.yml up -d --build`）；已有镜像方式需重新跑构建脚本生成新镜像，再 `up -d`。

**Q：容器退出 / 重启循环？**
A：检查 `docker logs danbooru-search` 是否有 Python 启动错误（如端口被占用、依赖缺失）。`restart: unless-stopped` 会在异常时尝试重启。

**Q：想用非 7860 端口？**
A：修改 compose 文件 `ports: - "新端口:7860"`（左侧宿主机端口），或改 `DANBOORU_PORT` 同时调整右侧容器端口。