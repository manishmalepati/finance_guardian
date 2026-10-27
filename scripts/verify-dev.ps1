param([switch]$WithDocker)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$tsc = Join-Path $projectRoot 'frontend\node_modules\.bin\tsc.cmd'

if (-not (Test-Path -LiteralPath $python)) {
    throw 'Project Python environment is missing. Create .venv and install backend/requirements.txt.'
}
if (-not (Test-Path -LiteralPath $tsc)) {
    throw 'Frontend dependencies are missing. Run npm ci in frontend.'
}

Push-Location $projectRoot
try {
    $env:PYTHONDONTWRITEBYTECODE = '1'
    & $python -B -m pytest -p no:cacheprovider backend/tests -q
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    & $tsc --project frontend/tsconfig.json --noEmit
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    if ($WithDocker) {
        docker compose ps
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
} finally {
    Pop-Location
}
