$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$runtimePath = 'D:\anaconda\envs\xmer-annotation'
foreach ($runtime in @('node.exe', 'python.exe')) {
    if (-not (Test-Path -LiteralPath (Join-Path $runtimePath $runtime))) { throw "Missing project runtime: $runtime" }
}
foreach ($port in @(5180, 5181)) {
    if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) { throw "Port $port is in use. Existing processes were left running." }
}
$apiProcess = Start-Process -FilePath (Join-Path $runtimePath 'python.exe') -ArgumentList @('cpm/server.py') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'api.log') -RedirectStandardError (Join-Path $PSScriptRoot 'api-error.log') -PassThru
$uiProcess = Start-Process -FilePath (Join-Path $runtimePath 'node.exe') -ArgumentList @('node_modules/vite/bin/vite.js', '--config', 'cpm/vite.config.ts') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'ui.log') -RedirectStandardError (Join-Path $PSScriptRoot 'ui-error.log') -PassThru
Write-Output "CPM preview: http://127.0.0.1:5180/"
Write-Output "CPM API PID: $($apiProcess.Id); CPM UI PID: $($uiProcess.Id)"
