# ==============================================================================
# Local Banking AI Platform - Windows PowerShell Local Runner
# ==============================================================================
# Sets up virtual environment, installs dependencies, runs database
# migrations, seeds demo data, and starts Banking, AI, and Frontend servers.
# ==============================================================================

$ErrorActionPreference = "Stop"
$ROOT_DIR = $PSScriptRoot

Write-Host "========================================================================" -ForegroundColor Cyan
Write-Host "🏦 Local Banking AI Platform - Local Environment Setup & Runner (PowerShell)" -ForegroundColor Cyan
Write-Host "========================================================================" -ForegroundColor Cyan

# 1. Check Python installation (>= 3.11 required)
$PYTHON_CMD = ""
if (Get-Command "python" -ErrorAction SilentlyContinue) {
    $PYTHON_CMD = "python"
} elseif (Get-Command "py" -ErrorAction SilentlyContinue) {
    $PYTHON_CMD = "py -3.11"
} else {
    Write-Error "Python is not installed or not in PATH."
    exit 1
}

$pyCheck = & $PYTHON_CMD -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Host "✓ Detected Python $pyCheck" -ForegroundColor Green

# 2. Setup Virtual Environment
$VENV_DIR = Join-Path $ROOT_DIR ".venv"
if (-not (Test-Path $VENV_DIR)) {
    Write-Host "📦 Creating virtual environment in .venv..." -ForegroundColor Yellow
    & $PYTHON_CMD -m venv $VENV_DIR
}

$VENV_PY = Join-Path $VENV_DIR "Scripts\python.exe"
if (-not (Test-Path $VENV_PY)) {
    $VENV_PY = Join-Path $VENV_DIR "bin\python.exe"
}
$VENV_ACTIVATE = Join-Path $VENV_DIR "Scripts\Activate.ps1"
if (Test-Path $VENV_ACTIVATE) {
    . $VENV_ACTIVATE
}
Write-Host "✓ Virtual environment ready ($VENV_DIR)" -ForegroundColor Green

# Locate alembic executable in virtualenv
$VENV_ALEMBIC = if (Test-Path (Join-Path $VENV_DIR "Scripts\alembic.exe")) {
    Join-Path $VENV_DIR "Scripts\alembic.exe"
} elseif (Test-Path (Join-Path $VENV_DIR "bin\alembic.exe")) {
    Join-Path $VENV_DIR "bin\alembic.exe"
} elseif (Test-Path (Join-Path $VENV_DIR "bin\alembic")) {
    Join-Path $VENV_DIR "bin\alembic"
} else {
    "alembic"
}

# 3. Environment Configuration (.env)
$ENV_FILE = Join-Path $ROOT_DIR ".env"
$ENV_EXAMPLE = Join-Path $ROOT_DIR ".env.example"
if (-not (Test-Path $ENV_FILE)) {
    Write-Host "⚙️ Creating .env from .env.example..." -ForegroundColor Yellow
    Copy-Item $ENV_EXAMPLE $ENV_FILE
}

$DATA_DIR = Join-Path $ROOT_DIR "data"
$LOGS_DIR = Join-Path $DATA_DIR "logs"
$UPLOADS_DIR = Join-Path $DATA_DIR "uploads"
$VECTOR_DIR = Join-Path $DATA_DIR "vectorstore"
New-Item -ItemType Directory -Force -Path $LOGS_DIR | Out-Null
New-Item -ItemType Directory -Force -Path $UPLOADS_DIR | Out-Null
New-Item -ItemType Directory -Force -Path $VECTOR_DIR | Out-Null

# Environment paths & service URLs for local execution
$NORMALIZED_ROOT = $ROOT_DIR -replace '\\', '/'
$env:APP_ENV = "development"
$env:LOG_LEVEL = "INFO"
$env:LOG_FORMAT = "json"
$env:BANKING_DATABASE_URL = "sqlite:///$NORMALIZED_ROOT/data/banking.db"
$env:AI_DATABASE_URL = "sqlite:///$NORMALIZED_ROOT/data/ai.db"
$env:LANGGRAPH_CHECKPOINT_DB = "$NORMALIZED_ROOT/data/checkpoints.db"
$env:AI_UPLOAD_DIR = "$NORMALIZED_ROOT/data/uploads"
$env:AI_VECTOR_STORE_PATH = "$NORMALIZED_ROOT/data/vectorstore"

$env:BANKING_SERVICE_URL = "http://localhost:8001/api/v1"
$env:AI_BANKING_SERVICE_URL = "http://localhost:8001/api/v1"
$env:BANKING_API_BASE_URL = "http://localhost:8001/api/v1"
$env:BANKING_API_URL = "http://localhost:8001/api/v1"
$env:AI_API_URL = "http://localhost:8002/api/v1"
$env:CORS_ORIGINS = "http://localhost:8501,http://127.0.0.1:8501"

# 4. Install Dependencies
Write-Host "📦 Checking and installing dependencies..." -ForegroundColor Yellow
& $VENV_PY -m pip install --quiet --upgrade pip
& $VENV_PY -m pip install --quiet -e (Join-Path $ROOT_DIR "common")
& $VENV_PY -m pip install --quiet -e (Join-Path $ROOT_DIR "banking_service")
& $VENV_PY -m pip install --quiet -e (Join-Path $ROOT_DIR "ai_service")
& $VENV_PY -m pip install --quiet -r (Join-Path $ROOT_DIR "frontend\requirements.txt")
Write-Host "✓ Dependencies installed" -ForegroundColor Green

# 5. Database Migrations & Fixtures
Write-Host "🔄 Running database migrations..." -ForegroundColor Yellow
Push-Location (Join-Path $ROOT_DIR "banking_service")
try {
    & $VENV_ALEMBIC upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "Banking Service alembic migration failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}

Push-Location (Join-Path $ROOT_DIR "ai_service")
try {
    & $VENV_ALEMBIC upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "AI Service alembic migration failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}

Write-Host "🌱 Seeding demo fixtures..." -ForegroundColor Yellow
Push-Location (Join-Path $ROOT_DIR "banking_service")
try {
    & $VENV_PY -m app.seed
    if ($LASTEXITCODE -ne 0) {
        throw "Database seed failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}
Write-Host "✓ Migrations and seed completed" -ForegroundColor Green

# 6. Start Services
Write-Host "🚀 Starting servers..." -ForegroundColor Cyan

$bankingOut = Join-Path $LOGS_DIR "banking.log"
$bankingErr = Join-Path $LOGS_DIR "banking_err.log"
$aiOut = Join-Path $LOGS_DIR "ai.log"
$aiErr = Join-Path $LOGS_DIR "ai_err.log"
$frontendOut = Join-Path $LOGS_DIR "frontend.log"
$frontendErr = Join-Path $LOGS_DIR "frontend_err.log"

$bankingProc = Start-Process -FilePath $VENV_PY `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--log-level", "warning" `
    -WorkingDirectory (Join-Path $ROOT_DIR "banking_service") `
    -RedirectStandardOutput $bankingOut `
    -RedirectStandardError $bankingErr `
    -PassThru

$aiProc = Start-Process -FilePath $VENV_PY `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002", "--log-level", "warning" `
    -WorkingDirectory (Join-Path $ROOT_DIR "ai_service") `
    -RedirectStandardOutput $aiOut `
    -RedirectStandardError $aiErr `
    -PassThru

$frontendProc = Start-Process -FilePath $VENV_PY `
    -ArgumentList "-m", "streamlit", "run", "app.py", "--server.port", "8501", "--server.address", "0.0.0.0", "--server.headless", "true" `
    -WorkingDirectory (Join-Path $ROOT_DIR "frontend") `
    -RedirectStandardOutput $frontendOut `
    -RedirectStandardError $frontendErr `
    -PassThru

# Health check helper
function Wait-ForHealth($url, $name, $proc, $errLog, $timeoutSec = 30) {
    for ($i = 0; $i -lt $timeoutSec; $i++) {
        try {
            $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
            if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 400) {
                Write-Host "    ✓ $name is healthy ($url)" -ForegroundColor Green
                return $true
            }
        } catch {}
        Start-Sleep -Seconds 1
    }
    Write-Host "    ❌ $name failed health check after $timeoutSec seconds ($url)" -ForegroundColor Red
    if (Test-Path $errLog) {
        Get-Content $errLog -Tail 20 | ForEach-Object { Write-Host "       $_" -ForegroundColor Red }
    }
    return $false
}

Write-Host "Checking service health..." -ForegroundColor Yellow
$h1 = Wait-ForHealth "http://127.0.0.1:8001/health" "Banking Service" $bankingProc $bankingErr
$h2 = Wait-ForHealth "http://127.0.0.1:8002/health" "AI Service" $aiProc $aiErr
$h3 = Wait-ForHealth "http://127.0.0.1:8501/_stcore/health" "Frontend Web App" $frontendProc $frontendErr

if (-not ($h1 -and $h2 -and $h3)) {
    Write-Host "One or more services failed to start. Stopping..." -ForegroundColor Red
    if ($frontendProc -and -not $frontendProc.HasExited) { Stop-Process -Id $frontendProc.Id -Force -ErrorAction SilentlyContinue }
    if ($aiProc -and -not $aiProc.HasExited) { Stop-Process -Id $aiProc.Id -Force -ErrorAction SilentlyContinue }
    if ($bankingProc -and -not $bankingProc.HasExited) { Stop-Process -Id $bankingProc.Id -Force -ErrorAction SilentlyContinue }
    exit 1
}

Write-Host ""
Write-Host "========================================================================" -ForegroundColor Cyan
Write-Host "🎉 ALL LOCAL BANKING AI PLATFORM SERVICES ARE UP AND RUNNING!" -ForegroundColor Green
Write-Host "========================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  🌐 Streamlit Web UI:        http://localhost:8501" -ForegroundColor Yellow
Write-Host "  🏦 Core Banking API:        http://localhost:8001 (Docs: http://localhost:8001/docs)"
Write-Host "  🤖 AI Chat Service API:     http://localhost:8002 (Docs: http://localhost:8002/docs)"
Write-Host ""
Write-Host "  🔑 Pre-Seeded Testing Accounts:"
Write-Host "     • Admin Account:    admin@bank.local    / Admin@Bank2024!    (PIN: 9999)"
Write-Host "     • Customer Account: customer@bank.local / Customer@Bank2024! (PIN: 1234)"
Write-Host "     • Bank Account:     XXXXXX0400          / Balance: ₹1,00,000.00"
Write-Host "     • Credit Card:      VISA ending 4321    / Limit: ₹2,00,000.00"
Write-Host ""
Write-Host "  [Press Ctrl+C to stop all servers and exit]" -ForegroundColor Yellow
Write-Host "========================================================================" -ForegroundColor Cyan
Write-Host ""

try {
    while ($true) {
        Start-Sleep -Seconds 2
        if ($bankingProc.HasExited -or $aiProc.HasExited -or $frontendProc.HasExited) {
            Write-Host "One of the services terminated unexpectedly." -ForegroundColor Red
            break
        }
    }
} finally {
    Write-Host "🛑 Shutting down local servers..." -ForegroundColor Yellow
    if ($frontendProc -and -not $frontendProc.HasExited) { Stop-Process -Id $frontendProc.Id -Force -ErrorAction SilentlyContinue }
    if ($aiProc -and -not $aiProc.HasExited) { Stop-Process -Id $aiProc.Id -Force -ErrorAction SilentlyContinue }
    if ($bankingProc -and -not $bankingProc.HasExited) { Stop-Process -Id $bankingProc.Id -Force -ErrorAction SilentlyContinue }
    Write-Host "✓ All servers stopped." -ForegroundColor Green
}
