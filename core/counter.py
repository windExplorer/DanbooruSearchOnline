"""
counter.py
──────────
极简持久化计数器（核心业务指标：总搜索、总访问、复制次数、成功交互、词频聚合、bad_case）。
数据只存储于 HuggingFace Dataset，无任何本地落盘操作。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

# ── 核心状态变量 ────────────────────────────────
_memory_count: int = 0      # 总搜索次数
_dirty_count: int = 0

_memory_visits: int = 0     # 总访问次数
_dirty_visits: int = 0
BASE_VISITS: int = 0

_memory_copies: int = 0     # 总复制次数
_dirty_copies: int = 0
BASE_COPIES: int = 0

_memory_successes: int = 0  # 搜索后有交互的次数（用于算零点击率）
_dirty_successes: int = 0

_memory_keywords: Counter = Counter()   # 内存中的热词字典
_dirty_keywords: Counter = Counter()    # 尚未同步的词频增量
MAX_KEYWORDS_LIMIT = 200                # 云端最多只保存前 200 个热词

# ── bad_case 状态变量 ────────────────────────────
_memory_bad_cases: list[dict] = []      # 内存中全量 bad_case（最新在前）
_dirty_bad_cases: list[dict] = []       # 尚未同步的增量
MAX_BAD_CASES = 50                      # 云端最多只保存最近 50 条

_last_sync: float = 0.0
_sync_lock: Optional[asyncio.Lock] = None

SYNC_INTERVAL = 1800        # 每 30 分钟同步一次
SYNC_THRESHOLD = 200        # 或各项增量之和达到 200 次同步一次


def _get_sync_lock() -> asyncio.Lock:
    global _sync_lock
    if _sync_lock is None:
        _sync_lock = asyncio.Lock()
    return _sync_lock


def _get_config():
    token = os.environ.get("HF_TOKEN")
    username = os.environ.get("HF_USERNAME") or os.environ.get("SPACE_AUTHOR_NAME")
    repo_id = os.environ.get("COUNTER_REPO") or (
        f"{username}/DanbooruSearchStats" if username else None
    )
    return repo_id, token


# ── 远端 IO 操作 ──────────────────────────────────

def _read_remote() -> tuple[int, int, int, int, dict, list]:
    repo_id, token = _get_config()
    if not repo_id or not token:
        return 0, BASE_VISITS, BASE_COPIES, 0, {}, []

    try:
        from huggingface_hub import hf_hub_download
        path = hf_hub_download(
            repo_id=repo_id, repo_type="dataset", filename="count.json", token=token,
        )
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            r_total     = int(data.get("total", 0))
            r_visits    = int(data.get("visits", BASE_VISITS))
            r_copies    = int(data.get("copies", BASE_COPIES))
            r_successes = int(data.get("successes", int(r_total * 0.75)))
            r_keywords  = data.get("hot_keywords", {})
            r_bad_cases = data.get("bad_cases", [])
            return r_total, r_visits, r_copies, r_successes, r_keywords, r_bad_cases
    except Exception as e:
        print(f"[Counter] 读取远端失败: {e}")
        return 0, BASE_VISITS, BASE_COPIES, 0, {}, []


def _sync_remote_task(
    adds_count, adds_visits, adds_copies, adds_successes,
    adds_keywords: dict, adds_bad_cases: list,
) -> tuple[bool, int, int, int, int, dict, list]:
    repo_id, token = _get_config()
    if not repo_id or not token:
        return False, 0, 0, 0, 0, {}, []

    from huggingface_hub import HfApi, hf_hub_download
    from huggingface_hub.utils import HfHubHTTPError
    api = HfApi(token=token)

    for _ in range(3):
        try:
            try:
                path = hf_hub_download(
                    repo_id=repo_id, repo_type="dataset", filename="count.json",
                    force_download=True, token=token,
                )
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    r_total     = int(data.get("total", 0))
                    r_visits    = int(data.get("visits", BASE_VISITS))
                    r_copies    = int(data.get("copies", BASE_COPIES))
                    r_successes = int(data.get("successes", int(r_total * 0.75)))
                    r_keywords  = data.get("hot_keywords", {})
                    r_bad_cases = data.get("bad_cases", [])
            except Exception:
                r_total, r_visits, r_copies, r_successes, r_keywords, r_bad_cases = (
                    0, BASE_VISITS, BASE_COPIES, 0, {}, []
                )

            # 合并数字增量
            n_total     = r_total     + adds_count
            n_visits    = r_visits    + adds_visits
            n_copies    = r_copies    + adds_copies
            n_successes = r_successes + adds_successes

            # 合并词频并截断 Top 200
            merged_keywords = Counter(r_keywords)
            for word, count in adds_keywords.items():
                merged_keywords[word] += count
            top_keywords = dict(merged_keywords.most_common(MAX_KEYWORDS_LIMIT))

            # 合并 bad_cases：本地新增（最新）插到远端列表头部，截断到上限
            merged_bad_cases = (adds_bad_cases + r_bad_cases)[:MAX_BAD_CASES]

            content = json.dumps({
                "total":        n_total,
                "visits":       n_visits,
                "copies":       n_copies,
                "successes":    n_successes,
                "hot_keywords": top_keywords,
                "bad_cases":    merged_bad_cases,
            }, ensure_ascii=False, indent=2)

            api.upload_file(
                path_or_fileobj=content.encode("utf-8"),
                path_in_repo="count.json",
                repo_id=repo_id, repo_type="dataset", token=token,
                commit_message=(
                    f"Sync: 搜索:{n_total} | 成功:{n_successes} | "
                    f"复制:{n_copies} | 访问:{n_visits} | bad_cases:{len(merged_bad_cases)}"
                ),
            )
            print(
                f"[Counter] ☁️ 同步成功！搜索:{n_total}, 成功交互:{n_successes}, "
                f"复制:{n_copies}, bad_cases:{len(merged_bad_cases)}"
            )
            return True, n_total, n_visits, n_copies, n_successes, top_keywords, merged_bad_cases

        except HfHubHTTPError as e:
            if "412 Precondition Failed" in str(e):
                time.sleep(1)
            else:
                break
        except Exception:
            break

    return False, 0, 0, 0, 0, {}, []


async def _perform_sync():
    global _dirty_count, _dirty_visits, _dirty_copies, _dirty_successes
    global _dirty_keywords, _dirty_bad_cases, _last_sync
    global _memory_count, _memory_visits, _memory_copies, _memory_successes
    global _memory_keywords, _memory_bad_cases

    lock = _get_sync_lock()
    if lock.locked():
        return

    async with lock:
        has_dirty = (
            _dirty_count + _dirty_visits + _dirty_copies + _dirty_successes
            + len(_dirty_keywords) + len(_dirty_bad_cases)
        ) > 0
        if not has_dirty:
            return

        # 快照脏数据并立即清空，不阻塞主线程
        c_adds, v_adds, cp_adds, s_adds = (
            _dirty_count, _dirty_visits, _dirty_copies, _dirty_successes
        )
        k_adds  = dict(_dirty_keywords)
        bc_adds = list(_dirty_bad_cases)

        _dirty_keywords.clear()
        _dirty_bad_cases.clear()

        loop = asyncio.get_running_loop()
        success, l_total, l_visits, l_copies, l_successes, l_keywords, l_bad_cases = (
            await loop.run_in_executor(
                None, _sync_remote_task,
                c_adds, v_adds, cp_adds, s_adds, k_adds, bc_adds,
            )
        )

        if success:
            _dirty_count     -= c_adds
            _dirty_visits    -= v_adds
            _dirty_copies    -= cp_adds
            _dirty_successes -= s_adds
            _last_sync = time.time()

            _memory_count     = max(_memory_count,     l_total)
            _memory_visits    = max(_memory_visits,    l_visits)
            _memory_copies    = max(_memory_copies,    l_copies)
            _memory_successes = max(_memory_successes, l_successes)
            _memory_keywords.clear()
            _memory_keywords.update(l_keywords)
            _memory_bad_cases.clear()
            _memory_bad_cases.extend(l_bad_cases)
        else:
            # 同步失败：把脏数据放回，等下次重试
            _dirty_keywords.update(k_adds)
            _dirty_bad_cases.extend(bc_adds)


# ── 公共 API ──────────────────────────────────────

async def init():
    global _memory_count, _memory_visits, _memory_copies, _memory_successes
    global _memory_keywords, _memory_bad_cases, _last_sync

    repo_id, token = _get_config()
    if not repo_id or not token:
        return

    loop = asyncio.get_running_loop()
    (
        _memory_count, _memory_visits, _memory_copies, _memory_successes,
        r_keys, r_bad_cases,
    ) = await loop.run_in_executor(None, _read_remote)

    _memory_keywords.update(r_keys)
    _memory_bad_cases.clear()
    _memory_bad_cases.extend(r_bad_cases)
    _last_sync = time.time()


def _check_sync():
    repo_id, token = _get_config()
    if repo_id and token and (
        (time.time() - _last_sync > SYNC_INTERVAL)
        or (
            _dirty_count + _dirty_visits + _dirty_copies + _dirty_successes
            + len(_dirty_keywords) + len(_dirty_bad_cases)
        ) >= SYNC_THRESHOLD
    ):
        asyncio.create_task(_perform_sync())


async def increment() -> int:
    global _memory_count, _dirty_count
    _memory_count += 1; _dirty_count += 1
    _check_sync()
    return _memory_count

async def increment_visit() -> int:
    global _memory_visits, _dirty_visits
    _memory_visits += 1; _dirty_visits += 1
    _check_sync()
    return _memory_visits

async def increment_copy() -> int:
    global _memory_copies, _dirty_copies
    _memory_copies += 1; _dirty_copies += 1
    _check_sync()
    return _memory_copies

async def increment_success() -> int:
    global _memory_successes, _dirty_successes
    _memory_successes += 1; _dirty_successes += 1
    _check_sync()
    return _memory_successes

async def add_keywords(words: list[str]):
    global _dirty_keywords, _memory_keywords
    valid_words = [w for w in words if len(w) > 1 and w not in {'一个', '的', '在', '了', '是', '有'}]
    for word in valid_words:
        _memory_keywords[word] += 1
        _dirty_keywords[word] += 1
    _check_sync()

async def add_bad_case(query: str) -> None:
    """
    记录一条 bad_case，写入内存脏列表，随下次常规同步上报。
    调用方应确保 query 长度 > 2。
    """
    global _dirty_bad_cases, _memory_bad_cases
    entry = {
        "q": query,
        "t": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    # 乐观更新内存（最新在前，截断到上限）
    _memory_bad_cases.insert(0, entry)
    if len(_memory_bad_cases) > MAX_BAD_CASES:
        _memory_bad_cases[:] = _memory_bad_cases[:MAX_BAD_CASES]

    # 写入脏列表（最新在前，sync 时拼到远端列表头部）
    _dirty_bad_cases.insert(0, entry)

    _check_sync()


def get() -> int:           return _memory_count
def get_visits() -> int:    return _memory_visits
def get_copies() -> int:    return _memory_copies
def get_successes() -> int: return _memory_successes

def get_hot_keywords(top_n: int = 10) -> dict:
    return dict(_memory_keywords.most_common(top_n))

def get_bad_cases() -> list[dict]:
    return list(_memory_bad_cases)

async def force_sync():
    await _perform_sync()