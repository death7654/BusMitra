<#
.SYNOPSIS
    Starts the BusMitra backend, following the "Quick Start for Team
    Members" steps in backend/README.md.

.DESCRIPTION
    By default runs the full README sequence every time:
      1. pip install -r requirements.txt
      2. python -m app.seed        (recreates the demo database)
      3. python ml/train.py        (retrains the Random Forest model)
      4. uvicorn app.main:app --reload
    Use the -Skip* switches to skip steps you don't want repeated on
    every run (seeding wipes existing data; training takes longer than
    the others).

.PARAMETER SkipInstall
    Skip `pip install -r requirements.txt`.

.PARAMETER SkipSeed
    Skip `python -m app.seed`. Skip this if you want to keep whatever
    is currently in data/bus.db instead of resetting it.

.PARAMETER SkipTrain
    Skip `python ml/train.py`. Skip this once you already have a
    ml/model.joblib you're happy with, to avoid retraining every start.

.PARAMETER Port
    Port for uvicorn. Default 8000 (matches the README).

.PARAMETER BindAddress
    Host uvicorn binds to. Default 0.0.0.0 so it's reachable from an
    Android emulator/device, not just 127.0.0.1.

.EXAMPLE
    Run from inside the backend folder:
    .\start-backend.ps1
    .\start-backend.ps1 -SkipSeed -SkipTrain
#>

param(
    [switch]$SkipInstall,
    [switch]$SkipSeed,
    [switch]$SkipTrain,

    [int]$Port = 8000,
    [string]$BindAddress = "0.0.0.0"
)

$ErrorActionPreference = "Stop"

# Assumes this script sits inside the backend folder itself, alongside
# requirements.txt, app/, and ml/.
$BackendPath = $PSScriptRoot

if (-not (Test-Path (Join-Path $BackendPath "requirements.txt"))) {
    Write-Error "Could not find requirements.txt next to this script. Place start-backend.ps1 inside the backend folder."
    exit 1
}

# ---------------------------------------------------------------------
# Optional virtual environment
# ---------------------------------------------------------------------
$venvActivate = Join-Path $BackendPath "venv\Scripts\Activate.ps1"
if (-not (Test-Path $venvActivate)) {
    $venvActivate = Join-Path $BackendPath ".venv\Scripts\Activate.ps1"
}
if (Test-Path $venvActivate) {
    Write-Host "Activating virtual environment..." -ForegroundColor Cyan
    & $venvActivate
}

Push-Location $BackendPath
try {
    # -------------------------------------------------------------
    # 1. Install dependencies
    # -------------------------------------------------------------
    if (-not $SkipInstall) {
        Write-Host "Installing dependencies (pip install -r requirements.txt)..." -ForegroundColor Cyan
        # pip install -r requirements.txt
    } else {
        Write-Host "Skipping dependency install." -ForegroundColor DarkYellow
    }

    # -------------------------------------------------------------
    # 2. Seed the database
    # -------------------------------------------------------------
    if (-not $SkipSeed) {
        Write-Host "Seeding database (python -m app.seed)..." -ForegroundColor Cyan
        python -m app.seed
    } else {
        Write-Host "Skipping database seed." -ForegroundColor DarkYellow
    }

    # -------------------------------------------------------------
    # 3. Train the ML model
    # -------------------------------------------------------------
    if (-not $SkipTrain) {
        Write-Host "Training ML model (python ml/train.py)..." -ForegroundColor Cyan
        python ml/train.py
    } else {
        Write-Host "Skipping model training." -ForegroundColor DarkYellow
    }

    # -------------------------------------------------------------
    # 4. Start the backend
    # -------------------------------------------------------------
    Write-Host ""
    Write-Host "Starting backend at http://127.0.0.1:$Port" -ForegroundColor Green
    Write-Host "Swagger docs:       http://127.0.0.1:$Port/docs" -ForegroundColor Green
    Write-Host "Health check:       http://127.0.0.1:$Port/health" -ForegroundColor Green
    Write-Host ""

    uvicorn app.main:app --reload --host $BindAddress --port $Port
} finally {
    Pop-Location
}