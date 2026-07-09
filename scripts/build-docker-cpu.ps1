# DanbooruSearchOnline —— 一键构建纯 CPU 版 Docker 镜像（Windows / PowerShell）
#
# 与 build-docker.ps1（CUDA 版）的区别：本脚本先用宿主机网络从 PyTorch 官方 CPU 源
# 预下载 torch 2.13.0+cpu wheel 到 docker/wheels-cpu/（容器内访问该源会被透明代理篡改、
# pip 校验 sha256 失败，故必须在宿主机下），再由 docker/Dockerfile.cpu 通过 bind mount
# 挂入安装，得到不含 CUDA runtime 的精简镜像（约 750MB，而非 CUDA 版约 2.9GB）。
#
# 用法：
#   .\scripts\build-docker-cpu.ps1                # 构建纯 CPU 版镜像（自动预下载 +cpu wheel）
#   $env:DANBOURU_IMAGE="myrepo/danbooru-cpu:1.0" # 可选：自定义镜像名（含仓库/标签）
#   .\scripts\build-docker-cpu.ps1
#   $env:DOCKER_BUILD_NO_CACHE="1"                # 可选：设为 1 则 --no-cache 完全从头重构（最干净，但更慢）
#   $env:DOCKER_KEEP_IMAGE="1"                    # 可选：设为 1 则导出 tar 后保留本地 docker 镜像（默认导出后即移除，仅留 tar 文件）
#
# 构建前的"清理"行为（避免旧产物残留造成混淆 / 占用磁盘）：
#   1) 自动移除已存在的同名旧镜像 tag（danbooru-search-online-cpu:<version> 与 :latest），
#      仅解除引用，底层共享层随后由 docker image prune 回收（不会删进新镜像）；
#   2) 默认复用 BuildKit 缓存以加速；如需绝对干净可设 DOCKER_BUILD_NO_CACHE=1；
#   3) 构建成功后自动 docker image prune -f 清理悬空层，释放磁盘。
#
# 版本号自动获取规则：
#   1) 优先读取仓库根目录 VERSION 文件（如 1.1.6）；
#   2) 回退解析 CHANGELOG.md 顶部的最新版本号；
#   3) 都没有则回退 latest。
# 默认标签 danbooru-search-online-cpu:<version> 与 :latest（与 CUDA 版镜像名区分，可共存）。

$ErrorActionPreference = 'Stop'

# 仓库根目录（scripts/ 的父目录）。PowerShell 5.1 的 Join-Path 仅支持两个参数，
# 多段路径需嵌套拼接，避免 "找不到接受实际参数的位置形式参数" 报错。
$ROOT = Split-Path -Parent $PSScriptRoot
$DOCKERFILE = Join-Path (Join-Path $ROOT 'docker') 'Dockerfile.cpu'
$VERSION_FILE = Join-Path $ROOT 'VERSION'
$WHEELS_DIR = Join-Path (Join-Path $ROOT 'docker') 'wheels-cpu'
$TORCH_VER = '2.13.0+cpu'

# 版本号：优先 VERSION 文件，回退解析 CHANGELOG.md 顶部最新版本
if (Test-Path $VERSION_FILE) {
    $VERSION = (Get-Content $VERSION_FILE -Raw).Trim()
} else {
    $m = Select-String -Path (Join-Path $ROOT 'CHANGELOG.md') -Pattern 'v\d+\.\d+\.\d+' | Select-Object -First 1
    $VERSION = if ($m) { $m.Matches[0].Value.TrimStart('v') } else { '' }
}
if (-not $VERSION) { $VERSION = 'latest' }

$DEFAULT_IMAGE = "danbooru-search-online-cpu:$VERSION"
$SECOND_TAG = "danbooru-search-online-cpu:latest"
$IMAGE = if ($env:DANBOURU_IMAGE) { $env:DANBOURU_IMAGE } else { $DEFAULT_IMAGE }

# ── 步骤 1：宿主机预下载 torch +cpu wheel（容器内被代理篡改，必须在宿主机下）──
# 仅当 docker/wheels-cpu/ 下没有匹配的 +cpu wheel 时才下载，避免重复拉取。
# 解析 pip 命令（优先 python -m pip，回退 python3 / pip），适配不同机器上解释器名字不同
$pipExe = $null; $pipPre = @()
if (Get-Command python -ErrorAction SilentlyContinue) { $pipExe = 'python'; $pipPre = @('-m','pip') }
elseif (Get-Command python3 -ErrorAction SilentlyContinue) { $pipExe = 'python3'; $pipPre = @('-m','pip') }
elseif (Get-Command pip -ErrorAction SilentlyContinue) { $pipExe = 'pip'; $pipPre = @() }
else {
    Write-Host "=> 未找到 python / python3 / pip，无法预下载 torch +cpu wheel。" -ForegroundColor Red
    Write-Host "   请先安装 Python 并加入 PATH；或手动把 torch-$TORCH_VER-cp312-cp312-manylinux_2_28_x86_64.whl" -ForegroundColor Yellow
    Write-Host "   放入 docker/wheels-cpu/ 后重试本脚本。" -ForegroundColor Yellow
    exit 1
}

Write-Host "=> 准备 torch 纯 CPU 版 wheel（若已存在则跳过下载）"
New-Item -ItemType Directory -Force -Path $WHEELS_DIR | Out-Null
$existing = Get-ChildItem -Path $WHEELS_DIR -Filter "torch-*+cpu*.whl" -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "   已存在：$(($existing | Select-Object -First 1).Name)，跳过下载。"
} else {
    Write-Host "   从 PyTorch 官方 CPU 源下载 torch==$TORCH_VER 的 Linux wheel ..."
    # 宿主机网络对该源正常；必须加 --platform manylinux_2_28_x86_64 --python-version 312 --only-binary=:all:
    # 否则在 Windows 宿主机上会下到错误平台的包。
    & $pipExe @pipPre download "torch==$TORCH_VER" --no-deps `
        -d $WHEELS_DIR --platform manylinux_2_28_x86_64 --python-version 312 --only-binary=:all: `
        --index-url https://download.pytorch.org/whl/cpu/ `
        --retries 5 --timeout 120
    if ($LASTEXITCODE -ne 0) {
        Write-Host "=> 下载 torch +cpu wheel 失败（退出码: $LASTEXITCODE）。" -ForegroundColor Red
        Write-Host "   请确认宿主机能访问 https://download.pytorch.org/whl/cpu/（浏览器可打开验证），" -ForegroundColor Yellow
        Write-Host "   或手动下载 torch-$TORCH_VER-cp312-cp312-manylinux_2_28_x86_64.whl 放入 docker/wheels-cpu/ 后重试。" -ForegroundColor Yellow
        exit $LASTEXITCODE
    }
    Write-Host "   下载完成，已存入 $WHEELS_DIR"
}

# ── 步骤 2：构建镜像（Dockerfile.cpu 通过 bind mount 挂入上面的 wheel）──
# 构建前清理：移除同名旧镜像 tag，避免旧产物残留引起混淆（底层共享层随后由 prune 回收）。
# 注意：docker rmi -f 对本脚本无副作用——即使旧镜像正被某容器引用，也只解除 tag 引用，
# 不影响该容器继续运行；后续 up -d --force-recreate 会基于新镜像重建。
Write-Host "=> 构建前清理同名旧镜像 tag（若存在则移除，缺失则忽略）"
cmd /c "docker rmi -f `"$IMAGE`" `"$SECOND_TAG`" > nul 2>&1"

# 是否完全从头构建（默认复用缓存加速；设 DOCKER_BUILD_NO_CACHE=1 则 --no-cache）
$noCache = if ($env:DOCKER_BUILD_NO_CACHE -eq '1') { '--no-cache' } else { '' }
if ($noCache) { Write-Host "   已启用 --no-cache：将完全从头重构（忽略所有缓存层）" }

Write-Host "=> 构建纯 CPU 版镜像：$IMAGE  (版本来源: $VERSION)"
Write-Host "   上下文(context): $ROOT"
Write-Host "   Dockerfile    : $DOCKERFILE"

# docker 是外部命令：PowerShell 5.1 会将其 stderr 包装成 RemoteException 而中断脚本，
# 且管道既捕获不到 stderr 文本、$LASTEXITCODE 又会被管道末端 cmdlet 覆盖。
# 故用 cmd /c 在 cmd 内部把 docker 的 stdout/stderr 合并到 stdout（2>&1），PowerShell
# 只收到纯文本流，经 Tee-Object 既实时显示（含进度条）又捕获进变量用于诊断；
# 退出码由 cmd 延迟扩展 !ERRORLEVEL! 写入临时文件（不干扰实时输出流），再读回判定成败。
$oldEAP = $ErrorActionPreference
$ErrorActionPreference = 'SilentlyContinue'
# 中文 Windows 控制台默认代码页为 GBK(936)，而 docker 输出是 UTF-8。
# 仅设 [Console]::OutputEncoding 只能纠正"内部捕获"的中文，屏幕仍会乱码；
# 必须把控制台代码页切到 UTF-8(chcp 65001) 才能同时让解码与显示都正确，结束后再还原。
$oldEnc = [Console]::OutputEncoding
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$oldCP = (chcp | Select-String -Pattern '\d+').Matches[0].Value
cmd /c "chcp 65001 > nul"
$exitFile = Join-Path $env:TEMP ('docker_exit_' + [System.Guid]::NewGuid().ToString() + '.txt')
# --progress=plain：BuildKit 默认在非 TTY（被管道接走）时吞掉实时进度条，
# 加此参数让它输出原始逐行日志，pip 下载进度（含 torch 的 MB 进度）实时可见。
cmd /v:on /c "docker build --progress=plain $noCache -t `"$IMAGE`" -t `"$SECOND_TAG`" -f `"$DOCKERFILE`" `"$ROOT`" 2>&1 & echo !ERRORLEVEL! > `"$exitFile`"" | Tee-Object -Variable buildOut
cmd /c "chcp $oldCP > nul"
[Console]::OutputEncoding = $oldEnc
$ErrorActionPreference = $oldEAP
$buildExit = if (Test-Path $exitFile) { [int](Get-Content $exitFile -Raw) } else { 1 }
Remove-Item $exitFile -Force -ErrorAction SilentlyContinue
$log = $buildOut -join "`n"

if ($buildExit -ne 0) {
    Write-Host ""
    Write-Host "=> 构建失败（docker build 退出码: $buildExit）。" -ForegroundColor Red

    # 根据报错关键字给出中文诊断，帮助你快速定位根因
    if ($log -match 'daemon is running|failed to connect|Cannot connect|system cannot find the file|dockerDesktopLinuxEngine|npipe|docker daemon running') {
        Write-Host "   Docker 未启动或尚未安装，请先启动 Docker Desktop（或 Linux 下 'sudo systemctl start docker'），" -ForegroundColor Yellow
        Write-Host "   并确认 'docker info' 能正常输出后，再重试本脚本。" -ForegroundColor Yellow
    } elseif ($log -match 'no such file or directory|Cannot locate Dockerfile|Dockerfile not found') {
        Write-Host "   可能原因：找不到 Dockerfile（路径不正确）。" -ForegroundColor Yellow
        Write-Host "   请确认文件存在：$DOCKERFILE" -ForegroundColor Yellow
    } elseif ($log -match 'permission denied|operation not permitted|denied') {
        Write-Host "   可能原因：权限不足（docker 组 / 文件权限）。" -ForegroundColor Yellow
        Write-Host "   Linux 下可把当前用户加入 docker 组，或用 sudo 运行。" -ForegroundColor Yellow
    } elseif ($log -match 'ERROR: 未在 docker/wheels-cpu') {
        Write-Host "   未找到 +cpu wheel：请确认步骤 1 预下载成功（docker/wheels-cpu/ 下应有 torch-*+cpu*.whl），" -ForegroundColor Yellow
        Write-Host "   或手动下载放入该目录后重试。" -ForegroundColor Yellow
    } elseif ($log -match 'timeout|context canceled|failed to resolve|network is unreachable|TLS handshake|proxy') {
        Write-Host "   可能原因：拉取基础镜像 / 依赖时网络超时或被墙。" -ForegroundColor Yellow
        Write-Host "   请检查代理设置，或为 Docker 配置镜像加速器（如国内源）后重试。" -ForegroundColor Yellow
    } else {
        Write-Host "   无法自动判断原因，请查看上方 docker 输出的完整报错日志。" -ForegroundColor Yellow
    }

    exit $buildExit
}

Write-Host ""
Write-Host "=> 构建完成（纯 CPU 版，不含 CUDA runtime）。"

# 清理：回收悬空镜像层与 BuildKit 构建缓存。
# 默认仅回收未被引用的悬空层（不拖慢后续构建）；
# 若发现镜像体积异常偏大（疑似命中了旧的庞大缓存层，例如历史 CUDA 版 torch 层），
# 可设 DOCKER_BUILD_PRUNE_ALL=1 彻底清空所有 BuildKit 构建缓存（下次构建会重新拉取
# 基础镜像/依赖，较慢但最干净），或直接设 DOCKER_BUILD_NO_CACHE=1 走 --no-cache 全程重来。
Write-Host "=> 清理悬空镜像层与 BuildKit 构建缓存，释放磁盘"
cmd /c "docker image prune -f > nul 2>&1"
if ($env:DOCKER_BUILD_PRUNE_ALL -eq '1') {
    Write-Host "   已启用 DOCKER_BUILD_PRUNE_ALL：彻底清空所有 BuildKit 构建缓存"
    cmd /c "docker builder prune -a -f > nul 2>&1"
} else {
    cmd /c "docker builder prune -f > nul 2>&1"
}
Write-Host "   自编译启动 : docker compose -f docker/docker-compose.build.yml up -d --build"
Write-Host "   已有镜像启动: docker compose -f docker/docker-compose.pull.yml up -d"

# 导出镜像为 .tar 文件（便于离线分发 / 搬运到其它机器）
$TAR_NAME = "danbooru-search-online-cpu-$VERSION.tar"
$TAR_PATH = Join-Path $ROOT $TAR_NAME
Write-Host "=> 导出镜像为 tar 包：$TAR_PATH"
$saveExitFile = Join-Path $env:TEMP ('docker_save_' + [System.Guid]::NewGuid().ToString() + '.txt')
cmd /v:on /c "docker save `"$IMAGE`" -o `"$TAR_PATH`" 2>&1 & echo !ERRORLEVEL! > `"$saveExitFile`""
$saveExit = if (Test-Path $saveExitFile) { [int](Get-Content $saveExitFile -Raw) } else { 1 }
Remove-Item $saveExitFile -Force -ErrorAction SilentlyContinue
if ($saveExit -ne 0) {
    Write-Host "=> 导出 tar 包失败（退出码: $saveExit）。镜像已构建成功，可手动执行：" -ForegroundColor Yellow
    Write-Host "   docker save $IMAGE -o $TAR_PATH" -ForegroundColor Yellow
} else {
    Write-Host "   已生成: $TAR_PATH （其它机器用 'docker load -i $TAR_PATH' 导入）"
    # 默认：导出 tar 后即移除本地 docker 中的构建镜像，仅保留 tar 文件（用户只需要镜像文件，
    # 不希望镜像堆积在本地 docker 里占用空间）。若需本地保留镜像以便直接 docker compose up，
    # 请设环境变量 DOCKER_KEEP_IMAGE=1。
    if ($env:DOCKER_KEEP_IMAGE -ne '1') {
        Write-Host "=> 移除本地 docker 中的构建镜像，仅保留 tar 文件"
        cmd /c "docker rmi -f `"$IMAGE`" `"$SECOND_TAG`" > nul 2>&1"
    } else {
        Write-Host "   已保留本地 docker 镜像 $IMAGE（因 DOCKER_KEEP_IMAGE=1）"
    }
}
