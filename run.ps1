# MapSmith 一键启动脚本（Windows / PowerShell）
# 用法：在项目根目录执行  .\run.ps1
# 步骤：检查解释器 -> 一次性装依赖 -> 启动 streamlit
# 端口可用 PORT 环境变量覆盖（默认 8501）：$env:PORT=9000; .\run.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Port = if ($env:PORT) { $env:PORT } else { "8501" }
$VenvDir = Join-Path $Root ".venv"
$Python = Join-Path $VenvDir "Scripts\python.exe"

# 1. 检查解释器：优先用已存在的 .venv，否则用系统 python 创建。
if (-not (Test-Path $Python)) {
    Write-Host "未找到虚拟环境，尝试用系统 python 创建 .venv ..."
    $SysPython = Get-Command python -ErrorAction SilentlyContinue
    if (-not $SysPython) {
        Write-Error "未找到 Python 解释器。请先安装 Python 3.12（https://www.python.org/downloads/）"
        exit 1
    }
    & $SysPython.Source -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) {
        Write-Error "创建虚拟环境失败"
        exit 1
    }
}

# 2. 一次性装依赖：用标记文件判断，已装过则跳过。
$Marker = Join-Path $VenvDir ".deps_installed"
if (-not (Test-Path $Marker)) {
    Write-Host "安装依赖（src/requirements.lock）..."
    & $Python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { Write-Error "pip 升级失败"; exit 1 }
    & $Python -m pip install -r (Join-Path $Root "src\requirements.lock")
    if ($LASTEXITCODE -ne 0) { Write-Error "依赖安装失败"; exit 1 }
    New-Item -ItemType File -Path $Marker | Out-Null
}

# 3. 启动 streamlit（启动命令与 T22 自检记录一致）。
# 设 headless：Windows 上 server.headless 默认 false，首次启动会弹 email onboarding 询问阻塞监听，
# 这里显式置 true 跳过该询问（不改启动命令，仅加环境变量）。
$env:STREAMLIT_SERVER_HEADLESS = "true"
$env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = "false"
# mapsmith 包在 src/ 下，streamlit 只会把脚本父目录 src/mapsmith 加入 sys.path，
# 需把 src/ 显式放入 PYTHONPATH，否则 app.py 的 `from mapsmith.config` 会 ModuleNotFoundError。
$env:PYTHONPATH = Join-Path $Root "src"
Write-Host "启动 MapSmith：http://localhost:$Port"
& $Python -m streamlit run src/mapsmith/app.py --server.port $Port