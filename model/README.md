# 模型目录 (model/)

本目录用于存放本地模型权重，**权重文件不提交到 git**（已加入 `.gitignore`）。

## 获取模型（BAAI/bge-m3）

本工具使用 [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) 作为语义向量模型。模型**不随仓库分发**，需自行获取后放入 `model/bge-m3/`。以下任一方式均可，下载后目录结构见下方「放置方式」。

### 方式一：HuggingFace Hub（官方源）

- 模型主页：https://huggingface.co/BAAI/bge-m3

使用 `huggingface-cli`（推荐，自动处理 LFS 大文件）：

```powershell
# 直接下载并放到项目内的 model/bge-m3
uv run huggingface-cli download BAAI/bge-m3 --local-dir model/bge-m3
```

或使用 git（需先 `git lfs install`）：

```powershell
git lfs install
git clone https://huggingface.co/BAAI/bge-m3 model/bge-m3
```

### 方式二：ModelScope 魔搭（国内推荐）

- 模型主页：https://modelscope.cn/models/BAAI/bge-m3

使用 `modelscope` CLI：

```powershell
pip install modelscope            # 若未安装 CLI
modelscope download --model BAAI/bge-m3 --local_dir model/bge-m3
```

或使用 git（需先 `git lfs install`）：

```powershell
git lfs install
git clone https://www.modelscope.cn/BAAI/bge-m3.git model/bge-m3
```

### 国内加速（HuggingFace 源）

若 HuggingFace 官方源下载慢，可使用镜像 `hf-mirror.com`（也可在 `.env` 中设置 `HF_ENDPOINT`）：

```powershell
$env:HF_ENDPOINT = "https://hf-mirror.com"
uv run huggingface-cli download BAAI/bge-m3 --local-dir model/bge-m3
```

## 放置方式

将 `BAAI/bge-m3` 模型整体放到本目录下，形成：

```
model/
└── bge-m3/
    ├── config.json
    ├── model.safetensors
    ├── tokenizer.json
    ├── tokenizer_config.json
    ├── special_tokens_map.json
    ├── modules.json
    └── 1_Pooling/        (若模型包含)
```

## 模型加载优先级

引擎通过 `platform_utils.resolve_model_path()` 决定模型来源（从高到低）：

1. 代码显式传入的路径
2. 环境变量 `DANBOORU_MODEL_PATH`（例如 `DANBOORU_MODEL_PATH=/path/to/bge-m3`）
3. 本目录 `model/bge-m3`  ← **推荐，把模型移过来即可，无需任何额外配置**
4. 以上都没有时，自动从 HuggingFace Hub 下载 `BAAI/bge-m3` 并缓存

只要把模型放进 `model/bge-m3`，引擎会优先使用它，跳过联网下载。
