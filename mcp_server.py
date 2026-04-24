"""
mcp_server.py
─────────────
MCP 服务层（可选）。

演示如何在完全不修改 core/ 的情况下将引擎暴露为 MCP 工具。

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
    Search Danbooru tags using natural language (Chinese or English).
    Returns a list of matched tags and a ready-to-use comma-separated prompt string.

    ## Parameter Selection Guide

    ### query
    The string used for querying, Chinese is recommended.

    ### use_segmentation (Smart Segmentation)
    - True  (default): Automatically splits long sentences into concept keywords,
                       searches each separately, then merges results. Best for
                       full-scene descriptions with multiple elements.
    - False:           Treats the entire input as a single semantic unit. Best for
                       looking up a specific tag, correcting spelling, or matching
                       a precise phrase.

    ### top_k (Semantic Recall per Segment)
    Controls how many candidate tags are retrieved per segment per vector layer.
    Final candidate pool size ≈ top_k × number_of_layers, then truncated to `limit`.
    - 5   (default): Balanced. Good for most full-scene queries.
    - 20:            Precise lookup. Use when searching for a specific tag.
    - 80~160:        Broad exploration. Use when discovering tags for a vague concept.
    Note: Higher top_k causes high-frequency segments to occupy more slots,
          potentially crowding out precise low-frequency matches.

    ### limit (Result Count)
    Maximum number of tags returned.
    - 80 (default): Suitable for full-scene prompt generation (fits most SDXL models).
    - 10~20:        Use for precise lookup or single-concept search to avoid noise.

    ### popularity_weight (0.0 ~ 1.0)
    Controls how much a tag's post count on Danbooru influences ranking.
    Higher = more common/mainstream tags ranked first.
    - 0.15 (default): Works well in most scenarios.

    ### show_nsfw
    Whether to include NSFW tags in results. Defaults to True.

    ---

    ## Usage Scenarios

    **Scenario 1 — Precise tag lookup / spell correction**
    e.g. "selafuku", "thighhigh", "twintail"
    → use_segmentation=False, top_k=20, limit=10

    **Scenario 2 — Vague concept exploration**
    e.g. "兔耳朵", "赛博朋克服装", "假肢"
    → use_segmentation=True, top_k=80, limit=80

    **Scenario 3 — Describe a subject to find its tag**
    e.g. "EVA中蓝发的零号机驾驶员", "命运石之门中的助手"
    → use_segmentation=False, top_k=20, limit=20

    **Scenario 4 — Full scene to prompt (most common use case)**
    e.g. "一个穿着白色水手服，蓝色短裙的少女在雨中的城市里奔跑"
    → use_segmentation=True, top_k=5, limit=80

    Args:
        query:              Natural language description (Chinese or English, Chinese is recommended).
        use_segmentation:   Enable smart segmentation. See guide above.
        top_k:              Candidate tags per segment per vector layer. See guide above.
        limit:              Maximum number of tags returned.
        popularity_weight:  Influence of tag post count on ranking (0.0~1.0).
        show_nsfw:          Whether to include NSFW tags. Defaults to False.

    Returns:
        A JSON string with fields:
          - prompt:   Ready-to-use comma-separated tag string.
          - keywords: Segmented keywords extracted from the query.
          - results:  List of matched tags with scores and metadata.
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
    Uses NPMI (Normalized Pointwise Mutual Information) scoring, which filters out
    tags that appear frequently only due to their own popularity.

    Recommended workflow:
      1. Call search_tags to get an initial tag list.
      2. Pick the tags you want to keep.
      3. Call get_related_tags with those tags to discover complementary tags
         that frequently co-occur with your selection in the Danbooru image pool.

    ## Usage Scenarios

    **Scenario 1 — Find common accessories/outfits for a clothing tag**
    e.g. tags=["fingerless_gloves"] → returns characters often wearing them

    **Scenario 2 — Get a character's typical visual features**
    e.g. tags=["amiya_(arknights)"] → returns outfit, expression, accessory tags
         that define this character's appearance

    **Scenario 3 — Explore a theme's tag ecosystem**
    e.g. tags=["fighter_jet"] → returns aircraft types, action, background tags

    **Scenario 4 — Intersection recommendations from multiple tags**
    e.g. tags=["maid", "twintails"] → returns tags specific to the
         "maid + twintails" combination, not just each tag individually

    Args:
        tags:      List of Danbooru tag names, e.g. ["white_serafuku", "sailor_collar"].
        limit:     Maximum number of recommendations returned.
        show_nsfw: Whether to include NSFW tags. Defaults to False.

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