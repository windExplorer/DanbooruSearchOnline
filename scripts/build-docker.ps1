# DanbooruSearchOnline —— 一键构建最新 Docker 镜像（Windows / PowerShell）
#
# 用法：
#   .\scripts\build-docker.ps1                  # 构建镜像（仅代码+依赖）
#   $env:DANBOURU_IMAGE="myrepo/danbooru:1.0"   # 可选：自定义镜像名（含仓库/标签）
#   .\scripts\build-docker.ps1
#
# 关于镜像体积：bge-m3 模型权重（数 GB）与标签库编码缓存不进镜像
# （见 .dockerignore），镜像小、构建快。运行时通过 compose 挂载本地模型/缓存，
# 或首次启动自动下载模型并编码。详见 docs/DOCKER.md 的「离线准备」章节。
#
# 版本号自动获取规则：
#   1) 优先读取仓库根目录 VERSION 文件（如 1.1.6）；
#   2) 回退解析 CHANGELOG.md 顶部的最新版本号；
#   3) 都没有则回退 latest。
# 默认标签 danbooru-search-online:<version> 与 :latest。
#
# 说明：构建上下文为仓库根目录，Dockerfile 位于 docker/Dockerfile。

$ErrorActionPreference = 'Stop'

# 仓库根目录（scripts/ 的父目录）。PowerShell 5.1 的 Join-Path 仅支持两个参数，
# 多段路径需嵌套拼接，避免 "找不到接受实际参数的位置形式参数" 报错。
$ROOT = Split-Path -Parent $PSScriptRoot
$DOCKERFILE = Join-Path (Join-Path $ROOT 'docker') 'Dockerfile'
$VERSION_FILE = Join-Path $ROOT 'VERSION'

# 版本号：优先 VERSION 文件，回退解析 CHANGELOG.md 顶部最新版本
if (Test-Path $VERSION_FILE) {
    $VERSION = (Get-Content $VERSION_FILE -Raw).Trim()
} else {
    $m = Select-String -Path (Join-Path $ROOT 'CHANGELOG.md') -Pattern 'v\d+\.\d+\.\d+' | Select-Object -First 1
    $VERSION = if ($m) { $m.Matches[0].Value.TrimStart('v') } else { '' }
}
if (-not $VERSION) { $VERSION = 'latest' }

$DEFAULT_IMAGE = "danbooru-search-online:$VERSION"
$SECOND_TAG = "danbooru-search-online:latest"
$IMAGE = if ($env:DANBOURU_IMAGE) { $env:DANBOORU_IMAGE } else { $DEFAULT_IMAGE }

Write-Host "=> 构建镜像：$IMAGE  (版本来源: $VERSION)"
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
# 仅设 [Console]::OutputEncoding 只能纠正“内部捕获”的中文，屏幕仍会乱码；
# 必须把控制台代码页切到 UTF-8(chcp 65001) 才能同时让解码与显示都正确，结束后再还原。
$oldEnc = [Console]::OutputEncoding
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$oldCP = (chcp | Select-String -Pattern '\d+').Matches[0].Value
cmd /c "chcp 65001 > nul"
$exitFile = Join-Path $env:TEMP ('docker_exit_' + [System.Guid]::NewGuid().ToString() + '.txt')
# --progress=plain：BuildKit 默认在非 TTY（被管道接走）时吞掉实时进度条，
# 加此参数让它输出原始逐行日志，pip 下载进度（含 torch / nvidia-* 的 MB 进度）实时可见。
cmd /v:on /c "docker build --progress=plain -t `"$IMAGE`" -t `"$SECOND_TAG`" -f `"$DOCKERFILE`" `"$ROOT`" 2>&1 & echo !ERRORLEVEL! > `"$exitFile`"" | Tee-Object -Variable buildOut
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
    } elseif ($log -match 'timeout|context canceled|failed to resolve|network is unreachable|TLS handshake|proxy') {
        Write-Host "   可能原因：拉取基础镜像 / 依赖时网络超时或被墙。" -ForegroundColor Yellow
        Write-Host "   请检查代理设置，或为 Docker 配置镜像加速器（如国内源）后重试。" -ForegroundColor Yellow
    } else {
        Write-Host "   无法自动判断原因，请查看上方 docker 输出的完整报错日志。" -ForegroundColor Yellow
    }

    exit $buildExit
}

Write-Host ""
Write-Host "=> 构建完成。"
Write-Host "   自编译启动 : docker compose -f docker/docker-compose.build.yml up -d --build"
Write-Host "   已有镜像启动: docker compose -f docker/docker-compose.pull.yml up -d"

# 导出镜像为 .tar 文件（便于离线分发 / 搬运到其它机器）
$TAR_NAME = "danbooru-search-online-$VERSION.tar"
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
}
