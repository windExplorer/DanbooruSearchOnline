"""
api_fastapi.py
──────────────
FastAPI 适配层（可选）。

演示如何在完全不修改 core/ 的情况下将引擎 API 化。

启动方式：
    uvicorn api_fastapi:app --host 0.0.0.0 --port 8000

请求示例：
    POST /search
    {
        "query": "白色水手服的女孩",
        "top_k": 5,
        "limit": 20
    }

    POST /related
    {
        "tags": ["white_serafuku", "sailor_collar"],
        "limit": 20,
        "show_nsfw": false
    }
"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from core.engine import DanbooruTagger
from core.models import SearchRequest, SearchResponse
import core.counter as counter


# ── Pydantic I/O 模型（API 层专用，与 core.models 解耦）──


class SearchIn(BaseModel):
    query: str
    search_mode: str = "full_scene"
    category: str = "all"
    show_nsfw: bool = True
    include_wiki: bool = False


class TagOut(BaseModel):
    tag: str
    cn_name: str
    wiki: str = ""


class RelatedIn(BaseModel):
    tags: list[str]
    limit: int = Field(50, ge=1, le=200)
    show_nsfw: bool = True
    include_wiki: bool = False


class RelatedTagOut(BaseModel):
    tag: str
    cn_name: str
    sources: list[str]
    wiki: str = ""


class SearchOut(BaseModel):
    prompt: str
    results: list[TagOut]
    keywords: list[str]
    hint: str | None = None


class ArtistIn(BaseModel):
    tags: list[str]
    limit: int = Field(30, ge=1, le=100)
    min_cooc: int = Field(3, ge=1, le=100)
    show_nsfw: bool = True


class ArtistOut(BaseModel):
    artist: str
    cooc_count: int
    post_count: int
    sources: list[str]
    top_tags: list[str]


_SEARCH_MODE_PRESETS: dict[str, dict[str, Any]] = {
    "precise_lookup": {"top_k": 10, "limit": 10, "popularity_weight": 0.15, "use_segmentation": False, "group_mode": "off", "max_per_group": 2},
    "concept_explore": {"top_k": 80, "limit": 80, "popularity_weight": 0.15, "use_segmentation": True, "group_mode": "expand", "max_per_group": 2},
    "subject_describe": {"top_k": 20, "limit": 20, "popularity_weight": 0.15, "use_segmentation": False, "group_mode": "off", "max_per_group": 2},
    "full_scene": {"top_k": 5, "limit": 80, "popularity_weight": 0.15, "use_segmentation": True, "group_mode": "diverse", "max_per_group": 2},
}

_CATEGORY_MAP: dict[str, list[str]] = {
    "all": ["General", "Character", "Copyright", "Artist", "Meta"],
    "general": ["General"],
    "character": ["Character"],
    "copyright": ["Copyright"],
}


async def _correct_tags(tagger: DanbooruTagger, tags: list[str]) -> tuple[list[str], list[str], dict[str, str]]:
    valid_tags: list[str] = []
    invalid_tags: list[str] = []
    for tag in tags:
        if tag in tagger._name_to_idx:
            valid_tags.append(tag)
        else:
            invalid_tags.append(tag)

    corrections: dict[str, str] = {}
    for bad_tag in invalid_tags:
        try:
            request = SearchRequest(
                query=bad_tag,
                top_k=5,
                limit=5,
                popularity_weight=0.15,
                use_segmentation=False,
                target_layers=['英文'],
            )
            response = await tagger.search_async(request)
            if response.results:
                corrections[bad_tag] = response.results[0].tag
        except Exception:
            pass

    corrected_tags: list[str] = []
    for tag in tags:
        if tag in valid_tags:
            corrected_tags.append(tag)
        elif tag in corrections:
            corrected_tags.append(corrections[tag])

    return corrected_tags, invalid_tags, corrections


def _with_corrections(results: list[dict[str, Any]], corrections: dict[str, str]) -> dict[str, Any]:
    if not corrections:
        return {"results": results}
    correction_notes = [f"{bad} → {good}" for bad, good in corrections.items()]
    return {
        "correction_note": "标签拼写错误，已经纠错: " + ", ".join(correction_notes),
        "corrections": corrections,
        "results": results,
    }


# ── FastAPI 子应用（挂载到 NiceGUI 的 /api 路径下）──
# lifespan / 预热由 ui_nicegui.py 的 @app.on_startup 统一管理，此处不重复。
app = FastAPI(
    title="Danbooru Tag Searcher API",
    description="通过 /api/docs 查看完整接口文档。",
    version="1.0.0",
)


# ── 端点 ──

@app.post("/search")
async def search(body: SearchIn) -> dict[str, Any]:
    tagger = await DanbooruTagger.get_instance()

    # SearchIn → core.models.SearchRequest（两者字段一一对应，直接解包）
    preset = _SEARCH_MODE_PRESETS.get(body.search_mode, _SEARCH_MODE_PRESETS["full_scene"])
    target_categories = _CATEGORY_MAP.get(body.category, _CATEGORY_MAP["all"])
    request = SearchRequest(
        query=body.query,
        top_k=preset["top_k"],
        limit=preset["limit"],
        popularity_weight=preset["popularity_weight"],
        show_nsfw=body.show_nsfw,
        use_segmentation=preset["use_segmentation"],
        target_categories=target_categories,
        group_mode=preset["group_mode"],
        max_per_group=preset["max_per_group"],
    )

    # 并发安全的异步 search（信号量串行化 + 线程池执行）
    try:
        response: SearchResponse = await tagger.search_async(request)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=503, detail="搜索超时（120s），请简化查询或稍后重试")

    # 计数：每次 API 搜索调用均计入搜索、成功、复制；访问不变
    await counter.increment()
    await counter.increment_success()
    await counter.increment_copy()

    results: list[dict[str, Any]] = []
    for result in response.results:
        if result.nsfw == '1' and not body.show_nsfw:
            continue
        item = {
            "tag": result.tag,
            "cn_name": result.cn_name,
        }
        if body.include_wiki:
            item["wiki"] = result.wiki
        results.append(item)

    payload: dict[str, Any] = {
        "prompt": response.tags_sfw if not body.show_nsfw else response.tags_all,
        "keywords": response.keywords,
        "results": results,
    }
    han_chars = re.findall(r'[\u4e00-\u9fff]', body.query)
    if body.query and len(han_chars) / len(body.query) < 0.5:
        payload["hint"] = "检测到英文查询，该搜索引擎对中文查询优化更好，如果搜索结果不合预期，推荐用中文重试"
    return payload


@app.post("/related")
async def related(body: RelatedIn) -> dict[str, Any]:
    """
    给定已选标签列表，返回基于共现表的关联推荐。

    - tags：种子标签列表（Danbooru 英文标签名）
    - limit：最多返回条数，默认 50
    - show_nsfw：是否包含 NSFW 标签，默认 True
    """
    tagger = await DanbooruTagger.get_instance()
    corrected_tags, invalid_tags, corrections = await _correct_tags(tagger, body.tags)
    if not corrected_tags:
        return {
            "error": "所有传入的标签均不存在于标签表中",
            "invalid_tags": invalid_tags,
        }
    results = await tagger.get_related_async(
        corrected_tags,
        set(corrected_tags),
        body.limit,
        body.show_nsfw,
    )
    # 计数：每次 API related 调用均计入搜索、成功、复制；访问不变
    await counter.increment()
    await counter.increment_success()
    await counter.increment_copy()

    output: list[dict[str, Any]] = []
    for result in results:
        item = {
            "tag": result.tag,
            "cn_name": result.cn_name,
            "sources": result.sources,
        }
        if body.include_wiki:
            item["wiki"] = result.wiki
        output.append(item)

    return _with_corrections(output, corrections)


@app.post("/artists")
async def artists(body: ArtistIn) -> dict[str, Any]:
    """
    给定标签列表，推荐擅长绘制这些标签的画师（基于 NPMI 共现数据）。

    - tags：种子标签列表（Danbooru 英文标签名）
    - limit：最多返回条数，默认 30
    - min_cooc：单个 (tag, artist) 对的最小共现次数，默认 3
    """
    tagger = await DanbooruTagger.get_instance()
    if not body.tags:
        return {"error": "tags 列表不能为空"}

    corrected_tags, invalid_tags, corrections = await _correct_tags(tagger, body.tags)
    if not corrected_tags:
        return {
            "error": "所有传入的标签均不存在于标签表中",
            "invalid_tags": invalid_tags,
        }

    results = await tagger.search_artists_by_tags_async(
        corrected_tags, limit=body.limit, min_cooc=body.min_cooc,
    )
    artist_names = [result.artist for result in results]
    top_tags_map = tagger.get_artist_top_tags(artist_names, show_nsfw=body.show_nsfw)
    # 计数
    await counter.increment()
    await counter.increment_success()
    await counter.increment_copy()

    output = [
        {
            "artist": result.artist,
            "cooc_count": result.cooc_count,
            "post_count": result.post_count,
            "sources": result.sources,
            "top_tags": top_tags_map.get(result.artist, []),
        }
        for result in results
    ]
    return _with_corrections(output, corrections)


@app.get("/health")
async def health():
    tagger = await DanbooruTagger.get_instance()
    return {"status": "ok", "loaded": tagger.is_loaded}
