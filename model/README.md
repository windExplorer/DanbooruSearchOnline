# 模型目录 (model/)

本目录用于存放本地模型权重，**权重文件不提交到 git**（已加入 `.gitignore`）。

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
4. 旧版固定路径 `D:/LLMs/BAAI/bge-m3`（向后兼容）
5. 以上都没有时，自动从 HuggingFace Hub 下载 `BAAI/bge-m3` 并缓存

只要把模型放进 `model/bge-m3`，引擎会优先使用它，跳过联网下载。
