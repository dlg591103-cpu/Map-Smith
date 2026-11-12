# Map Smith 一键启动脚本（Windows PowerShell）。
#
# 依据：docs/Spec/V0.1-专题制图智能体.md 第 6 节 T23（完成判定：解压即可运行）
# 与 docs/facts/08-交付形态.md（zip 包含一键启动脚本）。
#
# 用法：解压后在项目根目录执行
#   .\run.ps1                 # 默认 127.0.0.1:8501
#   .\run.ps1 -Port 9000      # 指定端口
#   .\run.ps1 -BindHost 0.0.0.0
#
# 脚本做三件事：
#   1. 定位 Python 3.12 解释器（优先环境变量 MAPSMITH_PYTHON，其次 .venv、py launcher）；
#   2. 首次运行时创建 .venv 并按 src/requirements.lock 安装依赖；
#   3. 以 python -m mapsmith 启动 Web 服务（T22 第二段入口，前端已随仓库构建）。
#
# 如执行策略限制脚本运行，可改用：
#   powershell -ExecutionPolicy Bypass -File .\run.ps1

param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8501
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
if (-not $root) { $root = (Get-Location).Path }

$venvDir = Join-Path $root ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$lockFile = Join-Path $root "src\requirements.lock"

function Write-Step([string]$Message) {
    Write-Host "[run.ps1] $Message"
}

function Test-Python312([string]$Exe) {
    # 检查什么：解释器存在且主次版本为 3.12+（SPEC 第 5 节要求 Python 3.12）。
    try {
        $raw = & $Exe --version 2>$null
        if ($raw -match "Python\s+3\.(\d+)\.") { return [int]$Matches[1] -ge 12 }
    } catch { }
    return $false
}

function Find-Interpreter {
    # 1) 用户显式指定（环境变量 MAPSMITH_PYTHON，绝对路径）。
    $explicit = $env:MAPSMITH_PYTHON
    if ($explicit -and (Test-Path $explicit) -and (Test-Python312 $explicit)) { return $explicit }

    # 2) 本项目已创建的 venv。
    if (Test-Path $venvPython) { return $venvPython }

    # 3) py launcher 请求 3.12；4) PATH 中的 python。
    #    注意：WindowsApps 中的 python 是商店存根，--version 无输出，会被版本检查排除。
    foreach ($probe in @(@("py", "-3.12"), @("python"))) {
        $cmd = Get-Command $probe[0] -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source -notlike "*WindowsApps*") {
            $args = @(); if ($probe.Count -gt 1) { $args = $probe[1..($probe.Count - 1)] }
            $exe = & $probe[0] @args -c "import sys; print(sys.executable)"
            if ($exe -and (Test-Python312 $exe)) { return $exe }
        }
    }
    return $null
}

$python = Find-Interpreter
if (-not $python) {
    Write-Host "[run.ps1] 未找到 Python 3.12 解释器。" -ForegroundColor Red
    Write-Host "[run.ps1] 请安装 Python 3.12 后重试，或用环境变量显式指定："
    Write-Host '[run.ps1]   $env:MAPSMITH_PYTHON = "C:\path\to\python.exe"'
    exit 1
}
Write-Step "解释器：$python"

# 依赖安装（首次运行）：.venv 不存在时创建并按锁文件安装。
if (-not (Test-Path $venvPython)) {
    Write-Step "创建虚拟环境 .venv ..."
    & $python -m venv $venvDir
    if ($LASTEXITCODE -ne 0) { Write-Host "[run.ps1] venv 创建失败。" -ForegroundColor Red; exit 1 }
}

# 依赖是否就绪：venv 内能导入 mapsmith 即视为已安装过。
# 注意：import 失败的 traceback 走 stderr，PowerShell 5.1 在 $ErrorActionPreference=Stop
# 下会把它转为异常，因此这里临时放宽并 try/catch 兜底。
$depsReady = $false
$prev = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    & $venvPython -c "import mapsmith" 2>$null | Out-Null
    $depsReady = ($LASTEXITCODE -eq 0)
} catch { $depsReady = $false }
$ErrorActionPreference = $prev

if (-not $depsReady) {
    Write-Step "按 src/requirements.lock 安装依赖（首次运行需数分钟）..."
    & $venvPython -m pip install -r $lockFile
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[run.ps1] 依赖安装失败，请检查网络后重试。" -ForegroundColor Red
        exit 1
    }
}

# 将 src/ 加入可导入路径：不修改包内代码，运行期注入。
$env:PYTHONPATH = (Join-Path $root "src")
Write-Step "启动 Map Smith Web 服务：http://${BindHost}:${Port}"
& $venvPython -m mapsmith --host $BindHost --port $Port
exit $LASTEXITCODE
