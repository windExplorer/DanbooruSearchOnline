# 本地部署 / 操作指南

本指南说明如何在本地（开发机 / 自托管服务器）从零跑起本项目，涵盖依赖安装、运行方式、GPU 可选、首次编码、环境变量与生产部署建议。

> 面向最终用户的功能介绍（参数说明、API / MCP 接入等）见 [README.md](./README.md)。本文件只讲「怎么把项目跑起来」。

---

## 1. 环境要求

| 项目 | 要求 |
|---|---|
| Python | `>=3.10`，推荐 `3.12`（与项目 Docker 镜像一致） |
| 包管理器 | [uv](https://docs.astral.sh/uv/)（推荐，已取代 `pip + requirements.txt`） |
| NVIDIA GPU | **可选**。有则加速首次编码；无 GPU 也能正常运行 |
| 磁盘 | 依赖 + 模型约 4~6 GB（`torch`/`sentence-transformers` 占大头，模型缓存另算 ~2 GB） |

> Windows 用户建议在 **PowerShell** 中操作；uv 进度条会写到 stderr，PowerShell 下可能显示为空白，但下载/安装仍在正常进行（用 `uv sync --verbose` 可看到实时进度）。

---

## 2. 安装依赖（uv）

项目已迁移到 `pyproject.toml` + `uv.lock`，不再依赖 `requirements.txt`（`uv sync` 时以 `pyproject.toml` 为准）。

### 2.1 默认（CPU 版 torch，适合生产 / 无 GPU 环境）

```powershell
uv sync
```

这会安装 PyPI 上的 **CPU 版 torch**，保证无 GPU 的服务器、CI、Docker 容器都能正常 `uv sync`。

### 2.2 启用 GPU（CUDA 版 torch，可选）

`gpu` 是一个**可选 extra**。只在显式激活时才拉取 CUDA 版 torch，不影响默认环境。

> ⚠️ RTX 50 系（如 5080 / 5090）是 Blackwell 架构，需要 **CUDA 12.8**。本项目已配置从 PyTorch `cu128` 源拉取对应 torch。

```powershell
# 第一次：安装时带上 gpu extra（从 PyTorch cu128 源下载 CUDA 版 torch，约 2~3 GB）
uv sync --extra gpu

# 之后每次运行，都必须带上 --extra gpu，否则 uv 会回退到 CPU 版 torch
uv run --extra gpu python ui_nicegui.py
```

验证 GPU 是否可用：

```powershell
uv run --extra gpu python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
# 期望输出类似：2.11.0+cu128 True NVIDIA GeForce RTX 5080
```

**要点**：`uv sync`（不带 extra）= CPU；`uv sync --extra gpu` = CUDA。`uv run` 同理——不带 `--extra gpu` 跑出来的进程 `torch.cuda.is_available()` 会是 `False`。

---

## 3. 运行（三种入口）

所有命令均通过 `uv run` 前缀使用虚拟环境，无需手动 `activate`。

### 3.1 网页界面（NiceGUI，最常用）

```powershell
# CPU
uv run python ui_nicegui.py

# GPU（需先 uv sync --extra gpu）
uv run --extra gpu python ui_nicegui.py
```

- 本地自动打开浏览器，地址：**http://127.0.0.1:11111**
- 启动完成后，界面会预热引擎（首次需全量编码，见第 4 节）
- 云端平台（HF / 魔搭）自动绑定 `0.0.0.0:7860`

### 3.2 REST API（FastAPI）

```powershell
uv run uvicorn api_fastapi:app --host 0.0.0.0 --port 8000
```

- 交互式文档：**http://127.0.0.1:8000/api/docs**
- 引擎在**首次请求时**懒加载（UI 版是在 startup 预热）
- 接口：`POST /api/search`、`POST /api/related`、`POST /api/artists`、`GET /api/health`

### 3.3 命令行（CLI）

```powershell
# 语义搜索
uv run python cli.py search "白色水手服的女孩" --top-k 10

# 共现关联推荐（标签用英文逗号分隔）
uv run python cli.py related "white_serafuku,sailor_collar" --limit 20
```

---

## 4. 首次启动：全量编码

### 为什么会有这一步

搜索引擎需要对数据库里**全部标签**预先做向量编码，构建 4 个维度的向量空间（英文 / 中文扩展词 / 维基释义 / 中文核心词）。这一步**只在首次（或缓存失效）时发生一次**，之后每次启动都只是「加载缓存」，几秒完成。

### 进度可见

编码过程已加进度输出，不会「假死」：

- 每层打印：`[Engine] ▶ 第 1/4 层「英文」`
- 每条文本计数：`[Engine]   编码 N 条文本 (device=cpu)`
- 编码实时进度条（tqdm）

### 耗时参考

| 环境 | 首次全量编码耗时 |
|---|---|
| CPU（无 GPU） | 几十分钟 ~ 1 小时（取决于标签总量与 CPU） |
| GPU（如 RTX 5080） | 几分钟 |

> 服务**运行时**的搜索只编码你输入的「一句话」（`batch=1`），毫秒级，与全量编码无关。

### 缓存位置与重建

- 编码结果写入：`tags_embedding/`（含 `danbooru_multiview_embeddings.safetensors` + `tags_metadata.parquet`）
- 该目录已被 `.gitignore` 忽略，不进仓库
- 强制重建（例如切换 CPU/GPU、标签库更新后）：

```powershell
Remove-Item -Recurse -Force tags_embedding
uv run python ui_nicegui.py   # 会自动重新全量编码
```

---

## 5. 环境变量

### 集中配置（推荐）：项目根 `.env`

所有配置项都可集中写在项目根的 **`.env`** 文件里（已提供 `.env.example` 模板，复制为 `.env` 后填入即可）。**程序启动时自动加载，无需在终端手动 export**。

- `.env` 已被 `.gitignore` 忽略（`*.env`），可放心写入本地绝对路径，不会误提交
- 真正在终端 / 系统设置的环境变量优先级更高（会覆盖 `.env` 中的同名项）

```ini
# .env 示例
DANBOORU_MODEL_PATH=model/bge-m3      # 模型目录（相对项目或绝对路径）
DANBOORU_DEVICE=auto                  # auto / cpu / cuda
DANBOORU_RELOAD=0                     # 1 开启 NiceGUI 热重载
HF_ENDPOINT=https://hf-mirror.com     # 国内加速模型下载（可选）
```

| 变量 | 作用 | 默认值 |
|---|---|---|
| `DANBOORU_DEVICE` | 推理设备：`auto`（默认，有 CUDA 用 GPU，否则 CPU） / `cpu` / `cuda`（无 CUDA 时自动回退并打印告警） | `auto` |
| `DANBOORU_RELOAD` | 设为 `1` 开启 NiceGUI 热重载（本地默认**关闭**，避免因报错反复重启导致 Ctrl+C 退不掉） | `0` |
| `HF_ENDPOINT` | HuggingFace 镜像，加速模型下载（如 `https://hf-mirror.com`） | 官方 |
| `HF_TOKEN` | HF 访问令牌（HF 平台自动注入，本地可选） | 无 |
| `DISABLE_NSFW` | 设为 `1` 强制禁用 NSFW 显示 | `0` |
| `OSS_*` | 阿里云 OSS 计数器后端（4 项：ACCESS_KEY_ID / SECRET / ENDPOINT / BUCKET_NAME）。**未配置则自动退化为本地模式**，不影响搜索 | 无 |

### 模型路径（可配置）

模型加载优先级（由 `platform_utils.resolve_model_path()` 决定）：

1. 代码显式传入的路径
2. 环境变量 `DANBOORU_MODEL_PATH`（自定义任意路径）
3. **项目内 `model/bge-m3/`**（默认：模型已放在此处，无需任何额外配置）
4. 以上都没有时，自动从 HuggingFace Hub 下载 `BAAI/bge-m3` 并缓存（国内可配 `HF_ENDPOINT` 镜像加速）

**推荐做法**：将 `BAAI/bge-m3` 整体放到本项目的 `model/bge-m3/` 目录（放置规范见 `model/README.md`），引擎默认就会直接使用它，彻底摆脱对外部固定路径的依赖。如需指向别处，用环境变量指定即可：

```powershell
$env:DANBOORU_MODEL_PATH = "D:/path/to/your/bge-m3"
uv run python ui_nicegui.py
```

---

## 6. 生产 / 无 GPU 部署

**核心结论**：GPU 只加速「那一次首次编码」，对线上服务吞吐无影响。生产无 GPU 完全可行——只要 `tags_embedding/` 缓存在启动前就位，运行时只编码单条 query，CPU 绰绰有余。

推荐做法（任选其一）：

1. **预构建 + 加载（最简单）**：在任意有 GPU / 有时间的机器上跑一次全量编码，把 `tags_embedding/` 随部署分发（挂载 volume、从 HF/OSS 拉取，或提交进镜像）。线上启动即「加载缓存」，冷启动秒级。
2. **Docker 构建期烤进镜像**：在 Dockerfile 里加一步触发一次 build（CPU 慢编一次，缓存留在镜像层），保证镜像自带缓存。
3. **运行时下载缓存**：代码内 `_pull_cloud_files()` 支持从 HF / OSS 拉取预构建的 `tags_embedding/*`，适合云部署。

> 注意：当前 `Dockerfile` 仍使用 `pip install -r requirements.txt`。若要切到 uv 构建（推荐，与本地一致），可将安装步骤改为 `uv sync --no-dev` 并由 uv 生成的 `.venv` 提供运行环境。

---

## 7. 常见问题

**Q：`uv sync` 看起来卡住没反应？**
A：PowerShell 把 uv 的进度条当控制字符吞掉了，界面空白但仍在下载（主要是 `torch` 约 1~2 GB）。加 `--verbose` 看实时进度，或直接在普通终端 / cmd 运行。

**Q：Ctrl+C 退不掉 / 报错刷屏？**
A：旧版默认开启 NiceGUI `reload`，本地报错会反复重启导致进程难退出。现已默认关闭 `reload`（单进程，Ctrl+C 正常）。需要热重载时 `set DANBOORU_RELOAD=1` 再启动。

**Q：本地有 5080 但 `torch.cuda.is_available()` 是 False？**
A：你跑的是 `uv run`（CPU 环境）。带 GPU 必须用 `uv run --extra gpu ...`，且需先 `uv sync --extra gpu` 安装 CUDA 版 torch。

**Q：想用 CPU 但内存不够编码？**
A：可临时调小 `core/engine.py` 中 `_encode_texts` 的 `batch_size`，或确保使用 GPU 编码。
