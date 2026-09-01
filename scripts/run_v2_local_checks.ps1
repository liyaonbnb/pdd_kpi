$ErrorActionPreference = "Stop"

$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$python = Join-Path $projectRoot "venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = "python"
}

Push-Location $projectRoot
try {
    Write-Host "[1/4] Python 单元测试"
    & $python -m unittest discover -s tests -p "test*.py"

    Write-Host "[2/4] V2 全生命周期演练"
    & $python -m v2.local_workflow

    Write-Host "[3/4] Python 编译检查"
    & $python -m compileall -q v2 tests

    Write-Host "[4/4] 前端 lint/build"
    Push-Location (Join-Path $projectRoot "frontend")
    try {
        npm run lint
        npm run build
    }
    finally {
        Pop-Location
    }

    Write-Host "本地 V2 回归检查全部通过。" -ForegroundColor Green
}
finally {
    Pop-Location
}
