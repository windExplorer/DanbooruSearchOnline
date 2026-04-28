"""
mcp_server.py
─────────────
MCP 服务层

挂载方式（在 ui_nicegui.py 中）：
    from mcp_server import mcp
    app.mount('/mcp', mcp.streamable_http_app())

接入地址：
    https://sakizuki-danboorusearch.hf.space/mcp/mcp

支持的工具：
    search_tags      自然语言搜索标签
    get_related_tags 基于共现表查关联推荐
"""

import json
import asyncio
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from core.engine import DanbooruTagger
from core.models import SearchRequest
import core.counter as counter
import re


mcp = FastMCP(
    name="danbooru-searcher",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


@mcp.tool()
async def search_tags(
    query: str,
    use_segmentation: bool = True,
    top_k: int = 5,
    limit: int = 80,
    popularity_weight: float = 0.15,
    show_nsfw: bool = True,
) -> str:
    """
Search Danbooru tags using natural language and return a ready-to-use prompt.

## Args
- query: Natural language description ( **Chinese recommended** ).
- use_segmentation: True for full-scene descriptions (splits concepts). False for exact lookup, single character match, or spell correction.
- top_k: Recall per segment. Use 5 for full scenes, 20 for precise tag lookup, 80-160 for broad concept exploration.
	> Note: Higher top_k causes high-frequency segments to occupy more slots, potentially crowding out precise low-frequency matches.
- limit: Max tags returned. Use 80 for generating full SDXL prompts, 10-20 for precise lookups to avoid noise.
- popularity_weight: Influence of tag post count on ranking (0.0~1.0). Default 0.15.
- show_nsfw: Include NSFW tags. Default True.

## Parameter guide (pick the scenario that fits)

    | Scenario                         | use_segmentation | top_k  | limit |
    |----------------------------------|------------------|--------|-------|
    | Full scene → prompt (default)    | True             | 5      | 80    |
    | Vague concept exploration        | Select as needed | 80     | 80    |
    | Describe a subject / find a tag  | False            | 20     | 20    |
    | Precise lookup / spell correction| False            | 20     | 10    |

## Examples

**Scenario 1 — Precise tag lookup / spell correction**
e.g. "selafuku", "thighhigh", "twintail"
→ use_segmentation=False, top_k=20, limit=10

**Scenario 2 — Vague concept exploration**
e.g. "兔耳朵", "赛博朋克服装", "假肢"
→ use_segmentation=True, top_k=80, limit=80

**Scenario 3 — Describe a subject / find a tag**
e.g. "EVA中蓝发的零号机驾驶员", "命运石之门中的助手", "两侧有开口，有拉绳的运动短裤"
→ use_segmentation=False, top_k=20, limit=20

**Scenario 4 — Full scene to prompt (most common use case)**
e.g. "一个穿着白色水手服，蓝色短裙的少女在雨中的城市里奔跑"
→ use_segmentation=True, top_k=5, limit=80

## Returns
JSON string with fields: prompt (comma-separated tags), keywords, results.
    """
    tagger = await DanbooruTagger.get_instance()
    request = SearchRequest(
        query=query,
        top_k=top_k,
        limit=limit,
        popularity_weight=popularity_weight,
        show_nsfw=show_nsfw,
        use_segmentation=use_segmentation,
    )
    response = await asyncio.to_thread(tagger.search, request)
    # 计数：每次 MCP 搜索调用均计入搜索、成功、复制；访问不变
    await counter.increment()
    await counter.increment_success()
    await counter.increment_copy()
    await counter.increment_mcp()

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

    payload = {
        "prompt":   response.tags_sfw if not show_nsfw else response.tags_all,
        "keywords": response.keywords,
        "results":  results,
    }
    han_chars = re.findall(r'[\u4e00-\u9fff]', query)
    if len(query) > 0 and len(han_chars) / len(query) < 0.5:
        payload["hint"] = (
            "检测到英文查询，该搜索引擎对中文查询优化更好，如果搜索结果不合预期，推荐用中文重试"
        )
    return json.dumps(payload, ensure_ascii=False, indent=2)



@mcp.tool()
async def get_related_tags(
    tags: list[str],
    limit: int = 20,
    show_nsfw: bool = True,
) -> str:
    """
Return co-occurrence-based tag recommendations for a given tag list (NPMI scoring).
Typical workflow: call search_tags first, then pass selected tags here to discover complementary ones.

Works well for: clothing accessories, character visual features, theme exploration, multi-tag intersections.
    e.g. tags=["fingerless_gloves"] → returns characters often wearing them
    e.g. tags=["amiya_(arknights)"] → returns outfit, expression, accessory tags
         that define this character's appearance
    e.g. tags=["fighter_jet"] → returns aircraft types, action, background tags
    e.g. tags=["maid", "twintails"] → returns tags specific to the
         "maid + twintails" combination, not just each tag individually

Args:
    tags:      List of Danbooru tag names, e.g. ["white_serafuku", "sailor_collar"].
    limit:     Maximum number of recommendations returned.
    show_nsfw: Whether to include NSFW tags. Defaults to True.

Returns:
    A JSON string containing recommended tags sorted by NPMI co-occurrence score.
    """
    tagger = await DanbooruTagger.get_instance()
    results = await asyncio.to_thread(
        tagger.get_related,
        tags,
        set(tags),
        limit,
        show_nsfw,
    )
    # 计数：每次 MCP related 调用均计入搜索、成功、复制；访问不变
    await counter.increment()
    await counter.increment_success()
    await counter.increment_copy()
    await counter.increment_mcp()

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