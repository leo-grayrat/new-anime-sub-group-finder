param([int]$Port = 18765)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    $env:UV_CACHE_DIR = Join-Path $PSScriptRoot '.cache\uv'
    uv sync --frozen --no-dev
    if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，请检查网络和 uv 安装。' }
}
if (-not (Test-Path -LiteralPath 'config.json')) {
    Copy-Item -LiteralPath 'config.example.json' -Destination 'config.json'
}
Write-Host "网页：http://127.0.0.1:$Port  MCP：http://127.0.0.1:$Port/mcp"
& $taskPython -m fansub_finder serve --port $Port
