# ChoirParts 本地启动（Windows / PowerShell）
#
# 用法：  .\start.ps1            -> http://127.0.0.1:8000
#         .\start.ps1 -Port 8010
#
# 说明：Python 依赖装在本仓库 backend\.venv\Lib\site-packages（没有改系统 Python），
#       前端已构建到 frontend\dist，后端会直接把它挂在根路径上。

param(
    [int]$Port = 8000,
    [switch]$Reload
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root 'backend'
$python = Join-Path $backend '.venv\Scripts\python.exe'

if (-not (Test-Path $python)) {
    throw "找不到虚拟环境：$python。请先按 LOCAL-SETUP.md 安装依赖。"
}

if (-not (Test-Path (Join-Path $root 'frontend\dist\index.html'))) {
    Write-Warning 'frontend\dist 不存在，页面会返回 503。先执行：cd frontend; npm install; npm run build'
}

# DSH 沙箱里 Python 的临时目录需要落在工作区内（见 LOCAL-SETUP.md 的说明）
$env:TMP = Join-Path $root '..\.tmp'
$env:TEMP = $env:TMP
New-Item -ItemType Directory -Force -Path $env:TMP | Out-Null

$uvicornArgs = @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$Port")
if ($Reload) { $uvicornArgs += '--reload' }

Write-Host "ChoirParts -> http://127.0.0.1:$Port" -ForegroundColor Green
Push-Location $backend
try {
    & $python @uvicornArgs
} finally {
    Pop-Location
}
