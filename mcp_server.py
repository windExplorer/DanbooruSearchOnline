"""
mcp_server.py
─────────────
MCP 服务层（可选）。

演示如何在完全不修改 core/ 的情况下将引擎暴露为 MCP 工具。

挂载方式（在 ui_nicegui.py 中）：
    from mcp_server import mcp
    app.mount('/mcp', mcp.streamable_http_app())

接入地址：
    https://sakizuki-danboorusearch.hf.space/mcp

支持的工具：
    search_tags      自然语言搜索标签
    get_related_tags 基于共现表查关联推荐
"""

import json
import asyncio
from mcp.server.fastmcp import FastMCP
from core.engine import DanbooruTagger
from core.models import SearchRequest

mcp = FastMCP(
    name="danbooru-searcher",
    description="Search Danbooru tags by natural language and get co-occurrence recommendations.",
)


@mcp.tool()
async def search_tags(
    query: str,
    top_k: int = 10,
    limit: int = 30,
    show_nsfw: bool = True,
) -> str:
    """
    Search Danbooru tags using natural language (Chinese or English).

    Args:
        query:     Natural language description, e.g. "girl in white sailor uniform".
        top_k:     Candidate tags per semantic layer. Higher = broader recall.
        limit:     Maximum number of tags returned.
        show_nsfw: Whether to include NSFW tags. Defaults to True.

    Returns:
        A JSON string containing matched tags and a ready-to-use prompt string.
    """
    tagger = await DanbooruTagger.get_instance()
    request = SearchRequest(
        query=query,
        top_k=top_k,
        limit=limit,
        show_nsfw=show_nsfw,
    )
    response = await asyncio.to_thread(tagger.search, request)

    results = [
        {
            "tag":         r.tag,
            "cn_name":     r.cn_name,
            "category":    r.category,
            "final_score": r.final_score,
            "count":       r.count,
        }
        for r in response.results
    ]

    return json.dumps({
        "prompt":   response.tags_sfw if not show_nsfw else response.tags_all,
        "keywords": response.keywords,
        "results":  results,
    }, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_related_tags(
    tags: list[str],
    limit: int = 20,
    show_nsfw: bool = True,
) -> str:
    """
    Given a list of selected Danbooru tags, return co-occurrence-based recommendations.

    Args:
        tags:      List of Danbooru tag names, e.g. ["white_serafuku", "sailor_collar"].
        limit:     Maximum number of recommendations returned.
        show_nsfw: Whether to include NSFW tags. Defaults to True.

    Returns:
        A JSON string containing recommended tags sorted by relevance score.
    """
    tagger = await DanbooruTagger.get_instance()
    results = await asyncio.to_thread(
        tagger.get_related,
        tags,
        set(tags),
        limit,
        show_nsfw,
    )

    return json.dumps([
        {
            "tag":        r.tag,
            "cn_name":    r.cn_name,
            "category":   r.category,
            "cooc_score": r.cooc_score,
            "sources":    r.sources,
        }
        for r in results
    ], ensure_ascii=False, indent=2)