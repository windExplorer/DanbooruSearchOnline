# 更新日志 (Changelog)

本项目派生自 [SuzumiyaAkizuki/DanbooruSearchOnline](https://github.com/SuzumiyaAkizuki/DanbooruSearchOnline)（GPL-3.0）。本文件只记录**本仓库**（windExplorer/DanbooruSearchOnline）自身的改动。

版本号采用 `主版本.次版本.修订` 格式；每次发布请打对应的 git tag。

---

## [v1.1.6] - 2026-07-09

修复放大弹窗：内容宽度未占满、同类标签缺复选框。

### 变更
- 弹窗卡片尺寸由 Tailwind 任意值类（`w-[92vw]` 等，NiceGUI 未识别 → 卡片收缩到内容宽度，整体变窄）改为内联 `style('width:92vw;max-width:1200px;height:88vh;')`；内容容器补 `w-full`，确保表格/列表占满宽度。
- 「同类标签」弹窗改用主页面同款 `_render_group_expansion`（参数化 `target`/`register`），复用含复选框的真实渲染逻辑，弹窗内可勾选且不影响主面板分页/滚动状态；弹窗模式 `visible_limit=None` 展示全部标签、隐藏「加载更多」、不触发主面板滚动恢复。
- 删除被取代的只读方法 `_render_group_readonly`。

## [v1.1.5] - 2026-07-09

结果区域新增「放大查看」按钮，弹窗全量浏览。

### 变更
- 四个结果区域标题处各加一个放大按钮（`open_in_full` 图标），点击打开大尺寸弹窗（约 92vw / 88vh，内部可滚动），便于一目了然查看全量内容。
- 新增 `_open_expand_dialog(kind)`，按类型渲染：`table` 复用主表格的 `body` 行模板只读展示全部行；`group` 调用新增的 `_render_group_readonly` 只读展开所有分组、显示全部标签（不含分页/复选框）；`artist` / `related` 复用 `_render_artist_rec` / `_render_related_list`，新增 `target` 与 `register` 参数以支持渲染到弹窗容器、且不污染主面板的复选框状态字典。
- 为弹窗提供数据快照：`__init__` 增加 `_current_artist_results` / `_current_artist_top_tags` / `_current_group_data` / `_table_body_slot`，分别由对应渲染函数写入，供弹窗读取最新结果。

## [v1.1.4] - 2026-07-09

滚动条样式微调：与列表留间距、贴卡片右侧。

### 变更
- `.region-scroll` 增加 `margin-right: -16px`（抵消卡片 `p-4` 右边距，使滚动条真正贴到卡片右边缘）与 `padding-right: 16px`（列表内容与滚动条之间留出间距，避免贴紧），并加 `scrollbar-gutter: stable` 防止滚动条出现/消失时列表左右跳动。
- 作用于四个独立滚动区域：匹配标签结果、同类标签、推荐擅长画师、关联推荐。

## [v1.1.3] - 2026-07-09

结果面板滚动下放到四个区域，外层不再滚动。

### 变更
- 重构结果区高度链：`.search-right` 改为纵向 flex 且自身 `overflow: hidden`，`.results-section` 填满剩余高度，`.two-col-layout` 等高拉伸（`align-items: stretch; height: 100%`）。
- 卡片（`.col-left` / `.col-right`）改为纵向 flex、有界高度（`max-height: 100%; overflow: hidden`），移除原先整卡滚动的 `col-scroll`。
- 四个结果区域各自独立滚动：新增 `.region-scroll`（`flex:1 1 0; min-height:0; overflow-y:auto`），分别包裹「匹配标签结果」表格（`region-grow2` 占更大比例）、「同类标签」、`self.group_expansion_container`、「推荐擅长画师」、`self.related_list_container`、「关联推荐」。
- 滚动条仅出现在这四个小块内部，整体面板 / 两栏卡片不再出现外层滚动条；移动端（≤1100px）区域限高 50vh、≤900px 兜底允许整页滚动。

## [v1.1.2] - 2026-07-09

UI 微调：搜索体验与底部栏精简。

### 变更
- 搜索选项默认展开（`ui.expansion(value=True)`）。
- 搜索框固定高度 180px，超出内容改为内部滚动（`min-height` 改为 `height/max-height: 180px`，`q-field__native` 加 `overflow-y: auto`），移除 `autogrow`，避免无限增高。
- 底部统计栏改为单行，去掉上边距（与上方容器已有 20px 间距）、下边距统一为 20px（`pt-0 mt-0 pb-5`），并移除换行 `<br>` 让链接与统计同处一行。
- 底部「版本号」改用真实数字版本号：新增 `_get_version()` 优先读取 CHANGELOG.md 顶部最新版本（`## [x.y.z]`），回退包元数据 / pyproject.toml，替换原先的 git commit 短哈希。

---

## [v1.1.1] - 2026-07-09

顶部导航栏全宽化，并将主标签页移入导航栏，提升空间利用率。

### 变更
- 顶层容器由限宽的 `dt-shell` 重构为全屏纵向 flex 的 `dt-page`；`dt-header` 作为其直接子元素天然占满整行视口宽度，去掉原先依赖 `100vw + 负 margin` 撑满的脆弱 hack。
- 主标签页（标签搜索 / 使用说明）从独立一行移入顶部导航栏右侧，与标题、徽章同栏，节省一整行高度；标签页去卡片底色融入导航条（`.dt-nav-tabs`）。
- banner / 结果面板 / 底部统计条各自加 `max-w-[1500px] mx-auto`，保持内容居中、不顶满视口。

### 文档
- 新增 `API.md`：覆盖 `/api/*` REST 接口（`/search`、`/related`、`/artists`、`/health`）、MCP 工具（`search_tags`、`get_related_tags`、`get_artist_recommendations`、`get_artist_profile`、`get_anima_format`、`get_newbie_format`）、其他路由、启动方式与 `core/models.py` 数据模型参考。

---

## [v1.1.0] - 2026-07-09

界面整体重写（保留全部检索能力与交互逻辑，仅重构前端外壳与样式）。

### 新增
- 统一主题：indigo/violet/pink 配色、渐变页眉、卡片圆角阴影（`.dt-card`）、自定义滚动条。
- 页眉信息条与「自托管版本」标识。

### 变更
- 重写 `build_page`、`_build_search_card`、`_build_selection_bar`、`_build_results_columns`、`_build_group_notice`、`_build_notice` 的视觉与布局；保留全部控件绑定与 `self.*` 容器引用（结果表格、关联推荐、画师推荐、同类标签、已选 chips 等刷新逻辑不变）。
- 两栏结果卡片加图标标题，画师列表支持自定义滚动条。

### 移除（原作者残留）
- 微信赞赏码弹窗（`_build_sponsor_dialog` 及 `SPONSOR_*` 常量、页脚「请作者喝杯咖啡」按钮）。
- Google Analytics（gtag）与 Google Search Console 验证 meta / 路由。
- 初始化横幅与公告中的原作者外部服务链接（备用 Space、问秋月、使用指南站外地址）。
- 注意事项中的「点赞 / Star / 赞赏」引导与站外链接。
- 重复的 `robots.txt` 路由定义（保留一个）。
- 页脚 MCP 外链改为指向本仓库与本地 `/api/docs`。

---

## [v1.0.0] - 2026-07-09

派生基线版本。在保留原项目全部检索能力的基础上，完成以下本地化 / 工程化改造。

### 新增
- 集中配置 `.env`（及 `.env.example` 模板），替代原项目非标准的 `config.env`，启动时自动加载。
- 部署文档 `DEPLOYMENT.md`：依赖安装、运行方式、可选 GPU、首次编码、环境变量与生产部署说明。
- `pyproject.toml`：以 uv 管理的项目元信息与依赖声明。
- `model/README.md`：模型放置规范与 bge-m3 手动下载说明（HuggingFace / ModelScope 链接与命令、国内镜像）。
- `README.md` 新增「派生说明」与「本仓库相对原项目的改动」章节。

### 变更
- **模型路径可配置化**：默认指向项目内 `model/bge-m3/`，支持 `DANBOORU_MODEL_PATH` 与 `.env` 覆盖，不再依赖原项目写死的外部固定路径；均不存在时自动从 HuggingFace Hub 下载。
- 模型权重（数 GB）加入 `.gitignore`，不入库。
- 许可证标注由误标的 `mit` 修正为 `gpl-3.0`，与仓库 `LICENSE` 文件一致。
- `README` frontmatter 移除原作者 OSS 缩略图。

### 修复
- MCP 服务（`/mcp` 子应用）关机报错：将 lifespan 的 enter/exit 放入同一后台任务，修复 `Ctrl+C` 退出时的 `RuntimeError: Attempted to exit cancel scope in a different task`。
- 全局 `excepthook` 忽略 `KeyboardInterrupt` / `SystemExit`，避免正常退出被误报为致命错误。

### 移除
- 原作者 `sync_to_hf` GitHub Actions 工作流（含其专属仓库 ID 与密钥配置）。
- `README` 中原作者个人资料：微信赞赏码（收款码）、基于私有服务器的搜索统计板块，以及强制友情链接要求。

---

> 后续更新请在本文件**顶部**按上述格式新增条目，并打对应的 git tag（如 `v1.0.1`、`v1.1.0`）。
