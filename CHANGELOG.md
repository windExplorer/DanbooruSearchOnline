# 更新日志 (Changelog)

本项目派生自 [SuzumiyaAkizuki/DanbooruSearchOnline](https://github.com/SuzumiyaAkizuki/DanbooruSearchOnline)（GPL-3.0）。本文件只记录**本仓库**（windExplorer/DanbooruSearchOnline）自身的改动。

版本号采用 `主版本.次版本.修订` 格式；每次发布请打对应的 git tag。

---

## [v1.1.6] - 2026-07-09

Docker 化：一键构建、compose 自编译 / 已有镜像部署、文档归整。

### 新增
- `docker/Dockerfile`（增强版）：非 root 运行、默认 `DANBOORU_HOST=0.0.0.0`/`DANBOORU_PORT=7860`、依赖层缓存；镜像仅含代码与依赖，模型权重与编码缓存在首次运行时下载/生成并经 named volume 持久化。
- `docker/docker-compose.build.yml`：自编译（源码构建）部署；`docker/docker-compose.pull.yml`：已有镜像部署。
- `scripts/build-docker.sh` 与 `scripts/build-docker.ps1`：一键构建最新镜像，**自动读取 `VERSION` 文件（回退解析 `CHANGELOG.md` 顶部版本号）作为镜像标签，并同时打 `latest` 标签**。
- `VERSION` 文件：记录当前版本号，供构建脚本自动获取，避免手填版本。
- `docs/DOCKER.md`：Docker 部署操作指南（构建、自编译 / 镜像部署、环境变量、数据持久化、故障排查）。
- 文档归整：`DEPLOYMENT.md`、`API.md` 迁移至 `docs/`，修正内部相对链接；`.gitignore` 放行 `docs/` 与 `scripts/*.sh`。
- `platform_utils.get_host_port()` 支持 `DANBOORU_HOST`/`DANBOORU_PORT` 环境变量覆盖，Docker / 反代场景可对外暴露。

### 变更
- 删除根目录旧 `Dockerfile`，统一使用 `docker/Dockerfile`（`docker-compose.build.yml` 的 `dockerfile` 路径同步修正为 `docker/Dockerfile`）。
- 结果「放大弹窗」修复：卡片尺寸由 NiceGUI 未识别的 Tailwind 任意值类（`w-[92vw]` 等 → 卡片收缩到内容宽度）改为内联 `style('width:92vw;max-width:1200px;height:88vh;')` 并补 `w-full`；「同类标签」弹窗改用 `_render_group_expansion`（参数化 `target`/`register`）复用含复选框的真实渲染逻辑；删除被取代的只读方法 `_render_group_readonly`。

### 修复
- **CPU 版构建脚本编码与兼容性**：`scripts/build-docker-cpu.ps1` / `build-docker-cuda.sh` 原为 UTF-8 无 BOM，中文版 Windows 的 PowerShell 5.1 默认按 GBK 解析，中文字符错位吃掉字符串引号，引发一连串「缺少终止符 / 意外的 `}`」解析错误；已转为 UTF-8 带 BOM。同时修正 `Join-Path $ROOT 'docker' 'wheels-cpu'` 三参数调用（PowerShell 5.1 仅支持两参数），改为嵌套 `Join-Path (Join-Path $ROOT 'docker') 'wheels-cpu'`。
- **torch CPU wheel 平台标签**：预下载命令的 `--platform linux_x86_64` 标签不存在，pip 找不到 `torch-2.13.0+cpu` 对应 wheel；修正为真实标签 `manylinux_2_28_x86_64`（同步修正 `Dockerfile.cpu` 注释与 `docs/DOCKER.md`）。
- **BuildKit 绑定挂载缺失**：`.dockerignore` 误将 `docker/wheels`、`docker/wheels-cpu` 排除，导致 `RUN --mount=type=bind,source=docker/wheels-cpu` 报 `"/docker/wheels-cpu": not found`；已移除这两行，并在两个 Dockerfile 的 `COPY --chown=user . /app` 加 `--exclude=docker/wheels --exclude=docker/wheels-cpu`，既保证挂载可找到、又避免 wheel 打进镜像层造成虚胖。
- **CPU 版镜像体积异常（3.64GB → ~752MB）**：`sentence-transformers` 依赖 `torch`，pip 解析时把已装的 `2.13.0+cpu` 误判为不满足，又拉一份普通 CUDA 版 torch（含 ~2GB nvidia CUDA 运行时）。`Dockerfile.cpu` 装 `requirements-docker.txt` 时新增约束文件 `torch==2.13.0+cpu`（`pip install -r ... -c`）锁死，禁止 pip 安装普通 CUDA 版，最终镜像仅含纯 CPU 版 torch。
- **Docker Compose 配置完善**：`docker-compose.*.yml` 的 `environment` 各项加注释；`DANBOORU_DEVICE` 默认改为 `cpu` 并注明可选值 `auto` / `cpu` / `cuda`；模型挂载由 `./model_cache` 改为 `../model`（直接复用项目根 `model/` 目录，免去拷贝）；默认镜像 tag 改为 `danbooru-search-online-cpu:1.1.6`（与 `VERSION` 文件及导出 tar 包名一致，CPU 版带 `-cpu` 后缀与 CUDA 版区分）。
- **精简镜像启动崩溃**：`platform_utils.py` 顶层 `import oss2` 导致未安装该可选依赖（为瘦身已排除 `oss2` / `modelscope`）的环境一导入即抛 `ModuleNotFoundError: No module named 'oss2'`，整个服务无法启动；改为在函数内懒加载（`_get_oss_bucket` / `read_bytes` / `resolve_model_path` 中按需 import，未安装时优雅降级为本地计数器模式），未配置 OSS 也可正常启动。
- **页面底部版本号错误（0.1.0 → 1.1.6）**：镜像内 `*.md` 被 `.dockerignore` 排除（CHANGELOG.md 不存在）、且镜像未 `pip install` 项目本身，导致 `_get_version()` 回退读取 `pyproject.toml` 的 `version=0.1.0`，页面显示 0.1.0 而非 1.1.6；改为**优先读取随代码 COPY 进镜像的 `VERSION` 文件**（与镜像 tag / compose 一致，不被 `.dockerignore` 排除），回退顺序 `VERSION → CHANGELOG.md → importlib 包元数据 → pyproject → 环境变量 APP_VERSION`；并同步把 `pyproject.toml` 的 `version` 从 `0.1.0` 改为 `1.1.6`，把 `CHANGELOG.md` 顶部误写的 `v1.1.7` 修正回 `v1.1.6` 并合并下方重复条目。
- **CPU 镜像体积逐次翻倍累加（750MB→1.46GB→2.19GB…）**：构建脚本把导出的 `danbooru-search-online-cpu-<version>.tar` 落在项目根（即构建上下文），而 `.dockerignore` 未排除 `*.tar`，导致 `Dockerfile.cpu` 的 `COPY . /app` 把**上一次导出的 tar 打进新镜像层**，每次构建体积叠加上一次的 tar 大小而翻倍（此前一度误判为 BuildKit 构建缓存所致，实为 tar 被 COPY 进镜像）。修复：`.dockerignore` 新增 `*.tar` / `*.tar.gz` / `*.tgz` 排除，镜像回到稳定的约 750MB。
- **CPU 构建脚本优化（`scripts/build-docker-cpu.ps1`）**：① 构建前自动 `docker rmi -f` 移除同名旧镜像 tag，避免旧产物残留混淆；② `docker build` 成功后自动 `docker save` 导出 `danbooru-search-online-cpu-<version>.tar`，并默认 `docker rmi -f` 删掉本地 docker 中的构建镜像、仅保留 tar 文件（避免镜像堆积占用本地磁盘），设 `DOCKER_KEEP_IMAGE=1` 可保留本地镜像以便直接 `docker compose up`；③ 构建后 `docker image prune -f` 回收悬空镜像层、并 `docker builder prune -f` 回收 BuildKit 构建缓存释放磁盘。新增环境变量：`DOCKER_BUILD_NO_CACHE=1`（强制 `--no-cache` 完全从头重构，最干净但更慢）、`DOCKER_BUILD_PRUNE_ALL=1`（彻底 `docker builder prune -a` 清空全部构建缓存）。
- **「复制选中 / 复制全部标签」按钮在 HTTP 下点击无反应**：原实现用 NiceGUI 的 `ui.clipboard.write()`，底层依赖浏览器 Clipboard API，而该 API 仅在 HTTPS / localhost 等**安全上下文**可用；以 `http://IP:7860` 这类 HTTP 访问时 `navigator.clipboard` 不可用，点击复制静默失败、毫无反应。改为新增 `_copy_to_clipboard()`：优先用 Clipboard API，不可用时自动降级到隐藏 `textarea` + `document.execCommand('copy')`，HTTP 非安全上下文也能正常复制。

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
