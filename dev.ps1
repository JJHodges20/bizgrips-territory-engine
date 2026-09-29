# BizGrips Territory Engine — Windows task runner mirroring the Makefile targets.
# Usage: .\dev.ps1 <target> [args]
#   targets: setup | test | test-cov | lint | format | dev | db-upgrade | db-revision "<msg>" |
#            seed-fixtures [scenario] | import-data | clean

param(
    [Parameter(Position = 0)] [string] $Target = "help",
    [Parameter(Position = 1)] [string] $Arg = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$Py = Join-Path $Root "venv\Scripts\python.exe"

function Invoke-Py { & $Py @args; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } }

switch ($Target) {
    "setup" {
        if (-not (Test-Path $Py)) { python -m venv venv }
        Invoke-Py -m pip install --upgrade pip
        Invoke-Py -m pip install -e ".[dev,geo]"
        if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
        Write-Host "Setup complete. Run '.\dev.ps1 test' then '.\dev.ps1 dev'."
    }
    "test"     { Invoke-Py -m pytest -q }
    "test-cov" { Invoke-Py -m pytest -q --cov=app --cov-report=term-missing }
    "lint"     { Invoke-Py -m ruff check .; Invoke-Py -m ruff format --check . }
    "format"   { Invoke-Py -m ruff format .; Invoke-Py -m ruff check --fix . }
    "dev"      { Invoke-Py -m uvicorn app.main:app --reload --port 8000 }
    "db-upgrade"  { Invoke-Py -m alembic upgrade head }
    "db-revision" {
        if (-not $Arg) { Write-Error "Usage: .\dev.ps1 db-revision \"message\""; exit 1 }
        Invoke-Py -m alembic revision --autogenerate -m $Arg
    }
    "seed-fixtures" {
        $scenario = if ($Arg) { $Arg } else { "denver_suburban_available" }
        Invoke-Py scripts/seed_fixtures.py --scenario $scenario
    }
    "import-data" {
        Invoke-Py scripts/import_geography.py
        Invoke-Py scripts/import_census.py
    }
    "clean" {
        foreach ($d in @(".pytest_cache", ".ruff_cache", "htmlcov", "build")) {
            if (Test-Path $d) { Remove-Item -Recurse -Force $d }
        }
        Get-ChildItem -Recurse -Directory -Filter "__pycache__" -Exclude venv |
            Where-Object { $_.FullName -notlike "*\venv\*" } |
            ForEach-Object { Remove-Item -Recurse -Force $_.FullName }
    }
    default {
        Write-Host "Usage: .\dev.ps1 <setup|test|test-cov|lint|format|dev|db-upgrade|db-revision|seed-fixtures|import-data|clean>"
    }
}
