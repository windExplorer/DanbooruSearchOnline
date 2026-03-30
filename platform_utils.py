"""
platform_utils.py
─────────────────
统一的平台检测与 Hub 操作封装。

支持平台：
  - HuggingFace Space
  - ModelScope 创空间（魔搭）
  - 本地开发环境

对外暴露：
  PLATFORM          : Literal['hf', 'ms', 'local']
  is_cloud()        : bool
  get_host_port()   : tuple[str, int]
  download_file()   : 下载单个文件，返回本地路径
  upload_bytes()    : 上传 bytes 到 Hub repo（用于计数器持久化）
  read_bytes()      : 从 Hub repo 读取文件内容，返回 bytes | None
  get_counter_cfg() : 返回 CounterConfig（repo_id / token / platform）

环境变量约定：
  ┌──────────────────────────────────────────────────────────────────────┐
  │ HuggingFace Space（由 HF 自动注入）                                  │
  │   SPACE_ID          Space 唯一标识，存在即代表在 HF 环境            │
  │   SPACE_AUTHOR_NAME 作者名                                           │
  │                                                                      │
  │ 用户手动配置（HF Secrets）：                                         │
  │   HF_TOKEN          HF 访问令牌                                      │
  │   HF_USERNAME       HF 用户名（可选，回退到 SPACE_AUTHOR_NAME）      │
  │   COUNTER_REPO      HF Dataset repo（默认 {username}/DanbooruStats） │
  ├──────────────────────────────────────────────────────────────────────┤
  │ ModelScope 创空间（由魔搭自动注入）                                   │
  │   MODELSCOPE_ENVIRONMENT  存在即代表在魔搭环境（值通常为 "studio"）  │
  │   STUDIO_ID               创空间 ID（备用检测）                      │
  │                                                                      │
  │ 用户手动配置（魔搭 Secrets）：                                        │
  │   MS_DATA_REPO_ID   存放数据文件的魔搭 Model repo                    │
  │                     形如 "YourName/DanbooruSearchData"               │
  │   MS_TOKEN          魔搭访问令牌（公开 repo 可不填）                 │
  │   MS_COUNTER_REPO   存放计数 JSON 的魔搭 Dataset repo                │
  │                     形如 "YourName/DanbooruSearchStats"              │
  └──────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

# ── 平台检测 ─────────────────────────────────────────────────────────────────

def _detect_platform() -> Literal['hf', 'ms', 'local']:
    if os.environ.get('SPACE_ID'):
        return 'hf'
    if os.environ.get('MODELSCOPE_ENVIRONMENT') or os.environ.get('STUDIO_ID'):
        return 'ms'
    return 'local'


PLATFORM: Literal['hf', 'ms', 'local'] = _detect_platform()


def is_cloud() -> bool:
    """是否运行在任意云端平台。"""
    return PLATFORM in ('hf', 'ms')


def get_host_port() -> tuple[str, int]:
    """
    返回 NiceGUI 应使用的 (host, port)。
    HF 和魔搭创空间都使用 0.0.0.0:7860；本地使用 127.0.0.1:1111。
    """
    if is_cloud():
        return '0.0.0.0', 7860
    return '127.0.0.1', 1111


def nsfw_allowed() -> bool:
    """
    返回当前平台是否允许用户开启 NSFW 显示。
    魔搭（MS）平台禁用 NSFW，其余平台默认允许。
    如需在任意平台强制禁用，可设置环境变量 DISABLE_NSFW=1。
    """
    if os.environ.get('DISABLE_NSFW', '0') == '1':
        return False
    return PLATFORM != 'ms'


# ── 计数器配置 ────────────────────────────────────────────────────────────────

@dataclass
class CounterConfig:
    platform: Literal['hf', 'ms', 'local']
    repo_id:  Optional[str]
    token:    Optional[str]

    @property
    def available(self) -> bool:
        return bool(self.repo_id and self.token and self.platform != 'local')


def get_counter_cfg() -> CounterConfig:
    """读取当前平台的计数器配置。"""
    if PLATFORM == 'hf':
        token    = os.environ.get('HF_TOKEN')
        username = os.environ.get('HF_USERNAME') or os.environ.get('SPACE_AUTHOR_NAME')
        repo_id  = os.environ.get('COUNTER_REPO') or (
            f'{username}/DanbooruSearchStats' if username else None
        )
        return CounterConfig(platform='hf', repo_id=repo_id, token=token)

    if PLATFORM == 'ms':
        token   = os.environ.get('MS_TOKEN')
        repo_id = os.environ.get('MS_COUNTER_REPO')
        return CounterConfig(platform='ms', repo_id=repo_id, token=token)

    return CounterConfig(platform='local', repo_id=None, token=None)


# ── 文件下载 ──────────────────────────────────────────────────────────────────

def download_file(
    filename: str,
    *,
    # HF 专用参数
    hf_repo_id:   Optional[str] = None,
    hf_repo_type: str           = 'space',
    hf_token:     Optional[str] = None,
    # MS 专用参数（Model repo）
    ms_repo_id:   Optional[str] = None,
    ms_token:     Optional[str] = None,
    ms_cache_dir: str           = '/tmp/ms_cache',
) -> str:
    """
    下载单个文件，返回本地绝对路径字符串。

    参数会根据当前 PLATFORM 自动选取，调用方也可显式传入 repo_id 覆盖默认值。

    HF 平台：
        hf_repo_id   默认读取环境变量 SPACE_ID
        hf_repo_type 默认 'space'（也支持 'model' / 'dataset'）

    MS 平台：
        ms_repo_id   默认读取环境变量 MS_DATA_REPO_ID
    """
    if PLATFORM == 'hf':
        from huggingface_hub import hf_hub_download
        repo_id = hf_repo_id or os.environ.get('SPACE_ID')
        if not repo_id:
            raise RuntimeError('[platform_utils] HF 平台未找到 SPACE_ID，无法下载文件。')
        return hf_hub_download(
            repo_id=repo_id,
            repo_type=hf_repo_type,
            filename=filename,
            token=hf_token or os.environ.get('HF_TOKEN'),
        )

    if PLATFORM == 'ms':
        from modelscope.hub.file_download import model_file_download
        repo_id = ms_repo_id or os.environ.get('MS_DATA_REPO_ID')
        if not repo_id:
            raise RuntimeError(
                '[platform_utils] 魔搭平台未配置 MS_DATA_REPO_ID，无法下载文件。\n'
                '请在创空间 Secrets 中添加 MS_DATA_REPO_ID=YourName/DanbooruData'
            )
        return model_file_download(
            model_id=repo_id,
            file_path=filename,
            cache_dir=ms_cache_dir,
        )

    # 本地环境：直接返回原始路径（由调用方保证文件存在）
    return filename


# ── Hub 读写（用于计数器持久化）────────────────────────────────────────────────

def read_bytes(filename: str, cfg: CounterConfig) -> Optional[bytes]:
    """
    从 Hub repo 读取文件内容，返回 bytes。
    若文件不存在返回 None；若发生网络或超时错误则抛出异常。
    """
    if not cfg.available:
        return None

    if cfg.platform == 'hf':
        from huggingface_hub import hf_hub_download
        from huggingface_hub.utils import EntryNotFoundError
        try:
            path = hf_hub_download(
                repo_id=cfg.repo_id,
                repo_type='dataset',
                filename=filename,
                token=cfg.token,
                force_download=True,
            )
            return Path(path).read_bytes()
        except EntryNotFoundError:
            # 明确是文件不存在，返回 None
            return None
        except Exception as e:
            # 网络超时等异常，直接向上抛出
            print(f'[platform_utils] HF 读取异常 ({filename}): {e}')
            raise

    if cfg.platform == 'ms':
        from modelscope.hub.file_download import model_file_download
        try:
            path = model_file_download(
                model_id=cfg.repo_id,
                file_path=filename,
                cache_dir='/tmp/ms_counter_cache',
            )
            return Path(path).read_bytes()
        except Exception as e:
            err_msg = str(e).lower()
            if 'not found' in err_msg or '404' in err_msg:
                return None
            print(f'[platform_utils] MS 读取异常 ({filename}): {e}')
            raise

    return None


def upload_bytes(
    content: bytes,
    filename: str,
    cfg: CounterConfig,
    commit_message: str = 'Update',
    *,
    retries: int = 3,
    retry_delay: float = 1.0,
) -> bool:
    """
    将 bytes 上传到 Hub repo 的 filename 路径。
    返回 True 表示成功，False 表示全部重试均失败。
    """
    if not cfg.available:
        return False

    for attempt in range(retries):
        try:
            if cfg.platform == 'hf':
                from huggingface_hub import HfApi
                from huggingface_hub.utils import HfHubHTTPError
                api = HfApi(token=cfg.token)
                api.upload_file(
                    path_or_fileobj=content,
                    path_in_repo=filename,
                    repo_id=cfg.repo_id,
                    repo_type='dataset',
                    commit_message=commit_message,
                )
                return True

            if cfg.platform == 'ms':
                _ms_upload_bytes(content, filename, cfg, commit_message)
                return True

        except Exception as e:
            # HF 412 是乐观锁冲突，值得重试
            if 'hf' in str(type(e).__module__) and '412' in str(e):
                pass
            print(f'[platform_utils] 上传失败（第 {attempt + 1} 次）: {e}')
            if attempt < retries - 1:
                time.sleep(retry_delay)

    return False


def _ms_upload_bytes(
    content: bytes,
    filename: str,
    cfg: CounterConfig,
    commit_message: str,
) -> None:
    """
    魔搭上传实现。
    魔搭 Dataset repo 的文件上传需要先写临时文件再调用 HubApi.upload。
    """
    import tempfile
    from modelscope.hub.api import HubApi

    api = HubApi()
    api.login(cfg.token)

    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(filename).suffix) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        # 魔搭 Dataset repo 上传接口
        api.upload_file(
            path_or_fileobj=tmp_path,
            path_in_repo=filename,
            repo_id=cfg.repo_id,
            repo_type='dataset',
            commit_message=commit_message,
        )
    finally:
        os.unlink(tmp_path)


# ── 模型路径解析 ───────────────────────────────────────────────────────────────

LOCAL_MODEL_PATH = 'my_model_bge_m3'
HF_MODEL_ID      = 'BAAI/bge-m3'
MS_MODEL_ID      = 'BAAI/bge-m3'   # 魔搭上同名，走国内节点


def resolve_model_path(prefer_local: Optional[str] = None) -> str:
    """
    按优先级解析模型路径：
      1. 本地目录（prefer_local 或 LOCAL_MODEL_PATH）
      2. 当前平台的 Hub Model ID（首次会自动下载缓存）
    返回可直接传给 SentenceTransformer 的路径或 model_id 字符串。
    """
    local = prefer_local or LOCAL_MODEL_PATH
    if os.path.exists(local):
        print(f'[platform_utils] 使用本地模型: {local}')
        return local

    if PLATFORM == 'ms':
        print(f'[platform_utils] 魔搭环境，使用 ModelScope Hub 模型: {MS_MODEL_ID}')
        try:
            from modelscope import snapshot_download
            cached = snapshot_download(MS_MODEL_ID, cache_dir='/tmp/ms_model')
            print(f'[platform_utils] 模型已缓存至: {cached}')
            return cached
        except Exception as e:
            print(f'[platform_utils] ModelScope snapshot_download 失败，回退到 HF ID: {e}')

    print(f'[platform_utils] 使用 HuggingFace Hub 模型: {HF_MODEL_ID}')
    return HF_MODEL_ID