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
    search_tags        自然语言搜索标签
    get_related_tags   基于共现表查关联推荐
    get_anima_format   返回 Anima 模型 Hybrid 提示词格式规范
    get_newbie_format  返回 NewBie 模型 XML 提示词格式规范
"""

import json
import asyncio
import logging
from anyio import BrokenResourceError, ClosedResourceError
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from core.engine import DanbooruTagger
from core.models import SearchRequest
import core.counter as counter
import re


# ── 过滤客户端断连/超时产生的无害报错噪音 ──────────────────────────────
class _SuppressClientDisconnect(logging.Filter):
    _SUPPRESSED: tuple = ()
    _HAS_STARLETTE: bool = False

    @classmethod
    def _init_suppressed(cls):
        if cls._SUPPRESSED:
            return
        types: list = [BrokenResourceError, ClosedResourceError, asyncio.CancelledError]
        try:
            from starlette.requests import ClientDisconnect
            types.append(ClientDisconnect)
            cls._HAS_STARLETTE = True
        except ImportError:
            pass
        cls._SUPPRESSED = tuple(types)

    def filter(self, record: logging.LogRecord) -> bool:
        self._init_suppressed()
        exc = record.exc_info[1] if record.exc_info else None
        if isinstance(exc, self._SUPPRESSED):
            return False
        # 用类名字符串兜底（避免 starlette 版本差异导致 import 失败）
        if exc is not None and not self._HAS_STARLETTE:
            name = type(exc).__name__
            if name in ('ClientDisconnect',):
                return False
        return True


_disconnect_filter = _SuppressClientDisconnect()
logging.getLogger("mcp.server.streamable_http").addFilter(_disconnect_filter)
logging.getLogger("mcp.server").addFilter(_disconnect_filter)
logging.getLogger("uvicorn.error").addFilter(_disconnect_filter)


mcp = FastMCP(
    name="danbooru-searcher",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


@mcp.tool()
async def search_tags(
    query: str,
    search_mode: str = "full_scene",
    category: str = "all",
    show_nsfw: bool = True,
    include_wiki: bool = False,
) -> str:
    """
Search Danbooru tags using natural language and return a ready-to-use prompt.
Only supported for general, copyright, and character tag searches; **artists and meta tags are not supported.**

## Args
- query: Natural language description (Chinese recommended).
- search_mode: Preset strategy. Pick the one that matches your intent.
    "full_scene"       — Full scene → prompt (e.g. "一个穿着白色水手服的少女在雨中奔跑")
    "concept_explore"  — Vague concept exploration, broad recall (e.g. "赛博朋克服装", "兔耳朵", "中国风汉服")
    "subject_describe" — Describe **one** subject to find matching tags (e.g. "EVA中蓝发的驾驶员", "两侧有开口，前方有拉绳的运动短裤")
    "precise_lookup"   — Precise lookup / spell fix (e.g. "selafuku", "thighhigh")
- HINT: In subject_describe mode, the tokenizer is disabled, and you can only describe one thing at a time. To search for multiple things at once, use concept_explore or full_scene.
- category: Filter to a specific tag category. Default "all".
    "all"       — All (通用 + 版权 + 人物)
    "general"   — Visual attributes, clothing, pose, background, etc.
    "character" — Named characters from any series
    "copyright" — Specific anime/game/franchise titles
- show_nsfw: Include NSFW tags. Default True.
- include_wiki: Append wiki description to each result. Default False.
    Set True when tags are unfamiliar and need disambiguation.

## Query writing guide

Use **spaces, newlines, Chinese commas (，), or Chinese dunhao (、)** to manually separate concepts.
Each delimiter-bounded segment ≤7 characters stays atomic — the engine respects your intent.

| Query style | Example |
|---|---|
| Concept list (spaces) | `运动社团 校队 比赛 运动会` |
| Concept list (dun hao) | `反乌托邦、赛博朋克、蒸汽朋克` |
| Natural sentence | `一个穿着白色水手服的少女在雨中奔跑` |
| Mixed | `运动社团 一个穿水手服的少女` |

## Workflow

After search_tags, pass selected tags to get_related_tags to discover complementary tags via co-occurrence.
Chain freely: search_tags → get_related_tags → get_related_tags → search_tags for multi-hop exploration.

## Returns

JSON with: prompt (comma-separated tags), keywords, results.
Each result: tag, cn_name, category, final_score, count[, wiki if include_wiki=True].
    """
    _SEARCH_MODE_PRESETS: dict[str, dict] = {
        "precise_lookup":   {"top_k": 10, "limit": 10, "popularity_weight": 0.15, "use_segmentation": False, "group_mode": "off",    "max_per_group": 2},
        "concept_explore":  {"top_k": 80, "limit": 80, "popularity_weight": 0.15, "use_segmentation": True,  "group_mode": "expand",  "max_per_group": 2},
        "subject_describe": {"top_k": 20, "limit": 20, "popularity_weight": 0.15, "use_segmentation": False, "group_mode": "off",    "max_per_group": 2},
        "full_scene":       {"top_k": 5,  "limit": 80, "popularity_weight": 0.15, "use_segmentation": True,  "group_mode": "diverse", "max_per_group": 2},
    }
    preset = _SEARCH_MODE_PRESETS.get(search_mode, _SEARCH_MODE_PRESETS["full_scene"])

    _CATEGORY_MAP: dict[str, list[str]] = {
        "all":       ["General", "Character", "Copyright", "Artist", "Meta"],
        "general":   ["General"],
        "character": ["Character"],
        "copyright": ["Copyright"],
    }
    target_categories = _CATEGORY_MAP.get(
        category,
        _CATEGORY_MAP["all"],
    )

    tagger = await DanbooruTagger.get_instance()
    request = SearchRequest(
        query=query,
        top_k=preset["top_k"],
        limit=preset["limit"],
        popularity_weight=preset["popularity_weight"],
        show_nsfw=show_nsfw,
        use_segmentation=preset["use_segmentation"],
        target_categories=target_categories,
        group_mode=preset["group_mode"],
        max_per_group=preset["max_per_group"],
    )
    try:
        response = await tagger.search_async(request)
    except asyncio.TimeoutError:
        return json.dumps({
            "error": "搜索超时（120s），请简化查询或稍后重试",
        }, ensure_ascii=False, indent=2)
    # 计数：每次 MCP 搜索调用均计入搜索、成功、复制；访问不变
    await counter.increment()
    await counter.increment_success()
    await counter.increment_copy()
    await counter.increment_mcp()

    results = []
    for r in response.results:
        if r.nsfw == '1' and not show_nsfw:
            continue
        item = {
            "tag":         r.tag,
            "cn_name":     r.cn_name,
            "category":    r.category,
            "final_score": r.final_score,
            "count":       r.count,
        }
        if include_wiki:
            item["wiki"] = r.wiki
        results.append(item)

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
    limit: int = 50,
    show_nsfw: bool = True,
    include_wiki: bool = False,
) -> str:
    """
Return co-occurrence-based tag recommendations for a given tag list (NPMI scoring).
Only supported for general, copyright, and character tag searches; **artists and meta tags are not supported.**

This tool surfaces tags that frequently appear alongside the seeds in
Danbooru, mixing categories (General / Character / Copyright) by design.

## Typical use cases

- Attribute → characters who have it
  e.g. ["fingerless_gloves"] → tifa_lockhart, cammy_white, bridget_(guilty_gear), ...
- Work → characters in it
  e.g. ["overlord_(maruyama)"] → shalltear_bloodfallen, ainz_ooal_gown, albedo_(overlord), ...
- Character → their visual attributes
  e.g. ["amiya_(arknights)"] → outfits, expressions, accessories
- Theme exploration
  e.g. ["fighter_jet"] → aircraft types, actions, backgrounds
- Multi-tag intersection
  e.g. ["maid", "twintails"] → tags specific to the combination, scored by summed NPMI

For within-category exploration (e.g. "more clothing tags like X"), use search_tags
with the `category` parameter instead.

## Workflow

Chain freely: search_tags → get_related_tags → get_related_tags → search_tags.
Each hop along the co-occurrence graph reveals tags unreachable by semantic search alone.

## Args

- tags: List of canonical Danbooru tag names (underscores, no spaces).
        e.g. ["white_serafuku", "sailor_collar"]
- limit: Max recommendations returned. Default 50.
- show_nsfw: Include NSFW tags. Default True.
- include_wiki: Append wiki description to each result. Default False.
        Set True when result tags are unfamiliar and need disambiguation.

## Returns

JSON array sorted by aggregated NPMI score (descending). Each result:
- tag, cn_name, category, count (post_count), cooc_score (normalized to [0,1])
- sources: seed tags that contributed to this score
- wiki: only if include_wiki=True
    """
    tagger = await DanbooruTagger.get_instance()

    # ── 检查标签是否存在，不存在则尝试 search_tags 纠错 ──────────────────
    valid_tags = []
    invalid_tags = []
    for t in tags:
        if t in tagger._name_to_idx:
            valid_tags.append(t)
        else:
            invalid_tags.append(t)

    corrections = {}
    if invalid_tags:
        for bad_tag in invalid_tags:
            try:
                req = SearchRequest(
                    query=bad_tag,
                    top_k=5,
                    limit=5,
                    popularity_weight=0.15,
                    use_segmentation=False,
                    target_layers=['英文']
                )
                resp = await tagger.search_async(req)
                if resp.results:
                    corrections[bad_tag] = resp.results[0].tag
            except Exception:
                pass

    if not valid_tags and not corrections:
        return json.dumps({
            "error": "所有传入的标签均不存在于标签表中",
            "invalid_tags": invalid_tags,
        }, ensure_ascii=False, indent=2)

    # 用纠错后的标签替换无效标签
    corrected_tags = []
    for t in tags:
        if t in valid_tags:
            corrected_tags.append(t)
        elif t in corrections:
            corrected_tags.append(corrections[t])

    results = await tagger.get_related_async(
        corrected_tags,
        set(corrected_tags),
        limit,
        show_nsfw,
    )
    # 计数：每次 MCP related 调用均计入搜索、成功、复制；访问不变
    await counter.increment()
    await counter.increment_success()
    await counter.increment_copy()
    await counter.increment_mcp()

    output = []
    for r in results:
        item = {
            "tag":        r.tag,
            "cn_name":    r.cn_name,
            "category":   r.category,
            "count":      r.post_count,
            "cooc_score": r.cooc_score,
            "sources":    r.sources,
        }
        if include_wiki:
            item["wiki"] = r.wiki
        output.append(item)

    payload = {"results": output}
    if corrections:
        correction_notes = [
            f"{bad} → {good}" for bad, good in corrections.items()
        ]
        payload = {
            "correction_note": "标签拼写错误，已经纠错: " + ", ".join(correction_notes),
            "corrections": corrections,
            "results": output,
        }

    return json.dumps(payload, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_artist_recommendations(
    tags: list[str],
    limit: int = 30,
    min_cooc: int = 3,
    show_nsfw: bool = True,
) -> str:
    """
    Recommend artists who are skilled at drawing the given tags, based on NPMI co-occurrence data.

    Given a list of Danbooru tags (e.g. character names, clothing, styles), this tool returns
    artists whose works frequently co-occur with those tags on Danbooru, ranked by aggregated
    NPMI score.

    ## Args
    - tags: List of canonical Danbooru tag names (underscores, no spaces).
            e.g. ["1girl", "blue_hair", "school_uniform"]
    - limit: Max artists returned. Default 30.
    - min_cooc: Minimum co-occurrence count per (tag, artist) pair to consider. Default 3.
    - show_nsfw: Include NSFW artist data. Default True.

    ## Returns

    JSON array sorted by NPMI score (descending). Each result:
    - artist: Danbooru artist tag name
    - cooc_count: Total co-occurrence count across all input tags
    - post_count: Artist's total post count on Danbooru
    - sources: Input tags that matched this artist
    - top_tags: Top 10 tags this artist most frequently draws (with Chinese names)
    """
    tagger = await DanbooruTagger.get_instance()

    if not tags:
        return json.dumps({"error": "tags 列表不能为空"}, ensure_ascii=False, indent=2)

    # ── 检查标签是否存在，不存在则尝试 search_tags 纠错 ──────────────────
    valid_tags = []
    invalid_tags = []
    for t in tags:
        if t in tagger._name_to_idx:
            valid_tags.append(t)
        else:
            invalid_tags.append(t)

    corrections = {}
    if invalid_tags:
        for bad_tag in invalid_tags:
            try:
                req = SearchRequest(
                    query=bad_tag,
                    top_k=5,
                    limit=5,
                    popularity_weight=0.15,
                    use_segmentation=False,
                    target_layers=['英文']
                )
                resp = await tagger.search_async(req)
                if resp.results:
                    corrections[bad_tag] = resp.results[0].tag
            except Exception:
                pass

    if not valid_tags and not corrections:
        return json.dumps({
            "error": "所有传入的标签均不存在于标签表中",
            "invalid_tags": invalid_tags,
        }, ensure_ascii=False, indent=2)

    # 用纠错后的标签替换无效标签
    corrected_tags = []
    for t in tags:
        if t in valid_tags:
            corrected_tags.append(t)
        elif t in corrections:
            corrected_tags.append(corrections[t])

    results = await tagger.search_artists_by_tags_async(
        corrected_tags, limit=limit, min_cooc=min_cooc,
    )

    # 获取每个画师最常画的标签
    artist_names = [r.artist for r in results]
    top_tags_map = tagger.get_artist_top_tags(artist_names, show_nsfw=show_nsfw)

    output = []
    for r in results:
        item = {
            "artist":     r.artist,
            "cooc_count": r.cooc_count,
            "post_count": r.post_count,
            "sources":    r.sources,
            "top_tags":   top_tags_map.get(r.artist, []),
        }
        output.append(item)

    # 计数
    await counter.increment()
    await counter.increment_success()
    await counter.increment_copy()
    await counter.increment_mcp()

    payload = {"results": output}
    if corrections:
        correction_notes = [
            f"{bad} → {good}" for bad, good in corrections.items()
        ]
        payload = {
            "correction_note": "标签拼写错误，已经纠错: " + ", ".join(correction_notes),
            "corrections": corrections,
            "results": output,
        }

    return json.dumps(payload, ensure_ascii=False, indent=2)


# ── Anima 提示词格式说明 ─────────────────────────────────────────────────
_ANIMA_FORMAT_INSTRUCTION = """请严格按以下 Anima 混合提示词（Hybrid Prompt）规范，基于提供的标签和用户描述，输出最终结果。

# Anima Prompt Composer

## Overview

将已有的 Danbooru 风格标签数据整合为 Anima 模型的最优 Hybrid 提示词。该 Skill 假定调用方已经拥有充足的标签信息（通过 Tagger、Captioner 或用户输入），仅负责按 Anima 的格式规范与社区验证的最佳实践进行结构化组装。

## 核心设计理念

Anima 是一个 2B 参数的文生图模型（CircleStone Labs × Comfy Org），基于 NVIDIA Cosmos-Predict2-2B，使用 Qwen 3 0.6B 文本编码器。它同时理解 Danbooru 标签和自然语言，但两者的行为有本质差异——标签掌控结构与精度，自然语言掌控氛围与构图。

社区的共识结论：
- **纯标签提示词**：线条锐利、色彩平整、几乎没有解剖错误，但画面扁平，缺乏光影、氛围、构图的精确控制。
- **纯自然语言提示词**：细节丰富、光影动态、气氛到位，但超过 2~3 段后结构崩塌，手部最先出问题。
- **Hybrid 混合模式**：标签主导主体结构，自然语言补充环境与氛围，获得约 80% 的主体控制力加完整的氛围控制力。

核心风险：自然语言的影响力 **远强于** 标签。当你用自然语言描述背景时，模型会忽略 `close-up`、`upper body` 等取景标签，生成广角镜头。解决方案是对取景标签使用权重语法。

## 输出格式

````markdown
## Prompt
```
[标签块：逗号分隔，单行]

[自然语言段落：2 到 3 句英文]
```

## 中文解释

[分点说明提示词设计逻辑，包含Prompt自然语言段落的完整翻译]
````

**绝对禁止**在任何部分之外添加开场白、寒暄或总结。

## 标签格式化规则

- 所有标签小写，下划线 `_` 替换为空格。**唯一例外**：`score_1` 到 `score_9` 保持下划线。
- 标签内括号用反斜杠转义：`momoko (momopoco)` → `momoko \\(momopoco\\)`
- 画师标签前面加一个 `@` 符号
- 标签间用一个逗号加一个空格连接：`tag a, tag b, tag c`
- 不要编造不存在的标签。若不确定某标签是否存在，将该概念放入自然语言段落。
- Tag Dropout 机制意味着不需要塞入每一个相关标签——只保留最关键和区分性最强的。

## 标签块结构规则

### 官方推荐标签顺序
```
[quality/meta/year/safety] → [1girl/1boy/1other] → [character] → [series] → [@artist] → [general tags]
```

### 单人物详细结构
```
[quality/meta/safety], [1girl/1boy], [character name], [series], [@artist], [hair], [eyes], [clothing], [body/pose], [expression], [action], [background/atmosphere], [composition tags]
```

### 多人物详细结构（防串扰核心规则）
```
[quality/meta/safety], [2girls / 1girl 1boy],
[character_A name], [series_A], [A hair], [A eyes], [A clothing], [A body], [A expression],
[character_B name], [series_B], [B hair], [B eyes], [B clothing], [B body], [B expression],
[shared pose/action], [background], [atmosphere], [composition]
```

## 标签体系速查

### 质量标签（任选其一或混用）
- 人工评分系：`masterpiece`, `best quality`, `good quality`, `normal quality`, `low quality`, `worst quality`
- 美学评分系：`score_9`, `score_8`, `score_7`, `score_6` ... `score_1`（仅score标签保留下划线）

### 年代标签
- 具体年份：`year 2025`, `year 2024` ...
- 时期：`newest` (2022-2023), `recent` (2019-2021), `mid` (2015-2018), `early` (2011-2014), `old` (2005-2010)

### 元标签
`highres`, `absurdres`, `anime screenshot`, `jpeg artifacts`, `official art`

### 安全分级
`safe`, `sensitive`, `nsfw`, `explicit`

### 艺术家标签
**必须以 @ 开头**。没有 @ 前缀的风格几乎不生效。

格式：`@nnn yryr`, `@big chungus`

一段提示词中最多包含3个艺术家标签。

### 数据集标签（非动漫风格时的备选）
在提示词最开头另起一行使用，可大幅改变风格倾向：
- `ye-pop`：LAION-POP 数据集风格，偏抽象/油画/概念艺术
- `deviantart`：DeviantArt 数据集风格，偏数字绘画/插画

## 自然语言段落规则

自然语言段落严格 2 到 3 句英文，仅用于标签难以精确表达的内容：

1. **镜头取景**：angle、shot distance、framing (close-up, wide shot, dutch angle…)
2. **光线**：方向、质感、色温 (rim light, volumetric god rays, warm key light…)
3. **色彩调性**：palette、color grading (monochromatic indigo, vibrant cel-shaded…)
4. **天气与环境**：rain、fog、dappled sunlight、underwater…
5. **氛围**：somber、airy、tense、ethereal…
6. **多角色空间关系与动作**：谁在左边、谁在干什么、互动方式

**关键禁忌**：
- 不要在自然语言中重复标签已覆盖的内容（发型、瞳色、服装等）。
- 不要写超过 3 段的自然语言——超过 2~3 段后画面结构会崩溃，手部最先出问题。
- 自然语言中不要使用隐喻或情绪化修辞，应使用客观、具体、视觉化的描述。

## 默认前缀与默认值

**正向前缀**（无特殊要求时的默认值）：
```
masterpiece, best quality, score_7, safe,
```

**取景默认**：若用户未指定，默认近景人物、人物面向观众。若用户有描述则以用户描述为准。

**模式默认**：采用 Hybrid 混合结构（标签 + 自然语言）。仅当用户明确要求纯标签或纯自然语言时才切换。

## 权重语法

Anima 支持 Prompt Weighting，但需要的权重值 **高于 SDXL**：

- 正常强调：`(tag:2)` 起步
- 强强调：`(tag:3)` 到 `(tag:5)`
- 权重取值范围：2 ~ 5
- 若用户提供 1.2 等较小权重，**必须放大至 2~5 区间**
- 多角色区分性特征（如一个蓝发一个红发）使用权重：`(blue hair:2)`, `(red hair:2)`

## Composition Tag 对抗自然语言漂移（关键规则）

当 Hybrid 提示词中自然语言段落包含环境描述时，模型倾向于拉远镜头，忽略 `close-up`、`upper body`、`portrait` 等取景标签。必须采取以下对抗措施：

1. **对取景标签使用强权重**：`(upper body:2)`, `(close-up:3)`
2. **在自然语言首句中明确取景**：`The composition is a tight close-up portrait...`
3. 如果仍然拉远，继续提高权重至 `(upper body:5)` 甚至 `(upper body:7)`

## 多人物特征分离规则（Anima 最高风险项）

Anima 在多人场景中极易发生特征混淆。必须严格遵守：

1. **角色属性按角色分组排列**。同一角色的发型、瞳色、服装、体型连续出现后再切换。严禁交叉排列（如 `blue hair, red hair, short hair, long hair`）。

2. **自然语言中为每个角色写一句"外观锚定短语"**。格式：`CharacterName with [key features]...` 明确指出视觉归属。这比仅靠标签的防串扰效果强得多。

3. **使用空间方位词分离角色**：left/right/foreground/background。

4. **为易混淆特征使用权重**：`(blue hair:2)`, `(red hair:2)`。

5. **角色外观在标签块中充分描述**。官方文档明确指出：先命名角色，再描述其外观。仅列出角色名而不描述外观会让模型困惑。

6. **自然语言中不重复标签内容**——自然语言补充空间关系、互动动作、光影氛围、构图取景。

## 安全标签使用规则

- 在提示 prefix 中始终包含安全分级标签（safe / sensitive / nsfw / explicit）。
- 描绘现有角色时，**禁止使用 score_8、score_9 等过强标签**，以免过拟合导致角色特征丢失。使用 `score_7` 作为上限。

## 中文解释撰写规则

- 采用分点结构，每点对应一个设计决策。
- 解释覆盖：为何选择当前提示词架构、关键标签的作用、自然语言各句的功能。
- 多人物时**必须**解释角色分组策略。
- 必须包含自然语言部分的完整中文翻译。
- 语言中立、客观、技术化。不使用感叹号、表情符号或情绪化措辞。
- 避免冗长背景介绍，只解释本次提示词中实际出现的元素。

"""


@mcp.tool()
async def get_anima_format() -> str:
    """
    返回 Anima 文生图模型的 Hybrid 混合提示词格式规范。

    当用户提到「Anima 提示词」「Anima 格式」「Anima Prompt」「Anima 模型」等关键词时，
    应在搜索标签完成、最终输出前调用此工具，以获取完整的提示词组装规范。

    ## 适用场景

    - 用户明确要求输出 Anima 模型的提示词
    - 用户提到 anima、Anima 等关键词
    - 需要将标签转换为 Anima 的 Hybrid 混合格式

    ## Returns

    包含完整 Anima 提示词格式规范的 Markdown 文本，涵盖标签格式化规则、
    自然语言段落规则、权重语法、多人物防串扰规则等。
    """
    return _ANIMA_FORMAT_INSTRUCTION


# ── NewBie 提示词格式说明 ─────────────────────────────────────────────────
_NEWBIE_OUTPUT_FORMAT = """
## 输出格式要求

你的输出包括两部分：一个 XML 代码块和代码块外的中文翻译。

### 标签处理规则
- 标签内部的空格必须替换为下划线 `_`（如 `red eyes` → `red_eyes`）
- 标签名内的括号必须用反斜杠转义（如 `momoko (momopoco)` → `momoko_\\(momopoco\\)`）
- 权重括号（如 `(daito:1.2)`）保持原样，不转义
- 括号内包含多个独立标签时，拆解为独立标签

### XML 结构

```xml
<img>
 <character_1>
  <n>角色名</n>
  <gender>性别标签 (如 1girl)</gender>
  <appearance>外貌特征 (发色, 瞳色, 身体特征等)</appearance>
  <clothing>衣着 (具体服饰)</clothing>
  <expression>表情</expression>
  <action>动作</action>
  <position>位置</position>
 </character_1>

 <!-- 若有多个角色，按 character_2, character_3 顺延 -->

 <general_tags>
  <count>人数标签</count>
  <style>画风标签（若用户未指定，默认 anime_style,realistic_shading）</style>
  <background>背景标签</background>
  <atmosphere>画面情绪、氛围标签</atmosphere>
  <quality>very_aesthetic, masterpiece, no_text</quality>
  <resolution>max_high_resolution</resolution>
  <artist>画师标签</artist>
  <objects>各种物品（包括武器、饰品等）</objects>
  <other>其它标签</other>
 </general_tags>

 <caption>
  将所有标签串联为一段流畅、详细的英文场景描述。包含光线、情绪、角色和背景。
  不要在此处提及 style 或 quality 类词汇。
 </caption>
</img>
```

在 XML 代码块结束后，输出 `<caption>` 内容的中文翻译。

### 多人物规则（防特征混淆）

如果用户提到了多个人物，必须严格遵循以下规则：

1. **角色分组**：每个 character_N 块内连续排列该角色的所有专属属性（发型、瞳色、服装、体型、表情、动作），然后再切换到下一角色。
2. **外观标签充分**：每个角色至少 5 个角色特征标签。可使用 get_related_tags 获得更多特征。
3. **属性不交叉**：禁止将不同角色的同类属性交叉排列。不同角色的特征混淆是多人场景最常见的失败模式。
4. **空间锚定**：在 `<position>` 和 `<caption>` 中明确每个角色的空间位置（如"左侧"、"右侧"、"前景"等）。
5. **caption 角色锚定**：在 `<caption>` 中为每个角色写一句外观锚定短语，使用"[角色名] with [关键特征]"的句式，明确指出视觉归属。
"""


@mcp.tool()
async def get_newbie_format() -> str:
    """
    返回 NewBie 文生图模型的 XML 格式提示词规范。

    当用户提到「NewBie 提示词」「NewBie 格式」「NewBie Prompt」「NewBie 模型」等关键词时，
    应在搜索标签完成、最终输出前调用此工具，以获取完整的 XML 格式组装规范。

    ## 适用场景

    - 用户明确要求输出 NewBie 模型的提示词
    - 用户提到 newbie、NewBie 等关键词
    - 需要将标签转换为 NewBie 的 XML 格式

    ## Returns

    包含完整 NewBie 提示词格式规范的文本，涵盖 XML 结构、标签处理规则、多人物规则等。
    """
    return _NEWBIE_OUTPUT_FORMAT