param([int]$Port = 18765)
$ErrorActionPreference = 'Stop'
$taskConnection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $taskConnection) {
    Write-Host '服务未运行。'
    exit 0
}
$taskService = Get-CimInstance Win32_Process -Filter "ProcessId=$($taskConnection.OwningProcess)"
if ($taskService.CommandLine.IndexOf($PSScriptRoot, [System.StringComparison]::OrdinalIgnoreCase) -lt 0 -or
    $taskService.CommandLine -notmatch '-m fansub_finder serve') {
    throw '这个端口的进程未通过项目身份校验，未停止任何进程。'
}
Stop-Process -Id $taskService.ProcessId
Write-Host '新番字幕组监控已停止。'
