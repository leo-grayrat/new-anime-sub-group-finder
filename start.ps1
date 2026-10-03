param([int]$Port = 18765)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
try {
    $taskStatus = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/status" -TimeoutSec 2
    if ($taskStatus.sources.mikan -and $taskStatus.season) {
        Write-Host "服务已运行：http://127.0.0.1:$Port；停止请使用 stop.cmd。"
        exit 0
    }
} catch {
    # No existing service; proceed with normal startup.
}
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath 'config.json')) {
    Copy-Item -LiteralPath 'config.example.json' -Destination 'config.json'
}
if (-not (Test-Path -LiteralPath $taskPython)) {
    $taskConfig = Get-Content -LiteralPath 'config.json' -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($taskConfig.proxy) {
        $env:HTTP_PROXY = $taskConfig.proxy
        $env:HTTPS_PROXY = $taskConfig.proxy
    }
    $env:UV_CACHE_DIR = Join-Path $PSScriptRoot '.cache\uv'
    uv sync --frozen --no-dev
    if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，请检查网络和 uv 安装。' }
}
Write-Host "网页：http://127.0.0.1:$Port  MCP：http://127.0.0.1:$Port/mcp"
& $taskPython -m fansub_finder serve --port $Port
