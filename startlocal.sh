#!/usr/bin/env bash
# ==============================================================================
# Local Banking AI Platform - Local Testing Environment Setup & Server Runner
# ==============================================================================
# Sets up virtual environment, installs all dependencies, runs database
# migrations, seeds demo data, and starts Banking, AI, and Frontend servers.
# ==============================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT_DIR}"

echo "========================================================================"
echo "🏦 Local Banking AI Platform - Local Environment Setup & Runner"
echo "========================================================================"

# ------------------------------------------------------------------------------
# 1. Check Python installation (>= 3.11 required)
# ------------------------------------------------------------------------------
PYTHON_BIN=""
if command -v python3 &>/dev/null; then
    PYTHON_BIN="python3"
elif command -v python &>/dev/null; then
    PYTHON_BIN="python"
else
    echo "❌ Error: Python 3 is not installed or not in PATH."
    exit 1
fi

PY_VERSION="$($PYTHON_BIN -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_MAJOR="$($PYTHON_BIN -c 'import sys; print(sys.version_info.major)')"
PY_MINOR="$($PYTHON_BIN -c 'import sys; print(sys.version_info.minor)')"

if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]); then
    echo "❌ Error: Python 3.11+ is required. Found Python $PY_VERSION."
    exit 1
fi
echo "✓ Detected Python $PY_VERSION ($PYTHON_BIN)"

# ------------------------------------------------------------------------------
# 2. Setup Virtual Environment
# ------------------------------------------------------------------------------
VENV_DIR="${ROOT_DIR}/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 Creating virtual environment in .venv..."
    $PYTHON_BIN -m venv "$VENV_DIR"
fi

# Activate virtual environment (handle Windows Git Bash and Unix paths)
if [ -f "${VENV_DIR}/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "${VENV_DIR}/bin/activate"
elif [ -f "${VENV_DIR}/Scripts/activate" ]; then
    # shellcheck disable=SC1091
    source "${VENV_DIR}/Scripts/activate"
fi
echo "✓ Activated virtual environment ($VENV_DIR)"

# ------------------------------------------------------------------------------
# 3. Environment Configuration (.env)
# ------------------------------------------------------------------------------
if [ ! -f "${ROOT_DIR}/.env" ]; then
    echo "⚙️ Creating .env from .env.example..."
    cp "${ROOT_DIR}/.env.example" "${ROOT_DIR}/.env"
fi

# Export local development testing defaults
export APP_ENV="${APP_ENV:-development}"
export LOG_LEVEL="${LOG_LEVEL:-INFO}"
export LOG_FORMAT="${LOG_FORMAT:-json}"

mkdir -p "${ROOT_DIR}/data/uploads" "${ROOT_DIR}/data/vectorstore"

# Ensure absolute SQLite paths for local processes
export BANKING_DATABASE_URL="sqlite:///${ROOT_DIR}/data/banking.db"
export AI_DATABASE_URL="sqlite:///${ROOT_DIR}/data/ai.db"
export LANGGRAPH_CHECKPOINT_DB="${ROOT_DIR}/data/checkpoints.db"
export AI_UPLOAD_DIR="${ROOT_DIR}/data/uploads"
export AI_VECTOR_STORE_PATH="${ROOT_DIR}/data/vectorstore"

# Service endpoints for local host execution
export BANKING_SERVICE_URL="http://localhost:8001/api/v1"
export AI_BANKING_SERVICE_URL="http://localhost:8001/api/v1"
export BANKING_API_BASE_URL="http://localhost:8001/api/v1"
export BANKING_API_URL="http://localhost:8001/api/v1"
export AI_API_URL="http://localhost:8002/api/v1"
export CORS_ORIGINS="http://localhost:8501,http://127.0.0.1:8501"

# ------------------------------------------------------------------------------
# 4. Install Dependencies
# ------------------------------------------------------------------------------
echo "📦 Installing project packages..."
python -m pip install --quiet --upgrade pip

echo "  -> Installing common library (banking-common)..."
python -m pip install --quiet -e "${ROOT_DIR}/common"

echo "  -> Installing Core Banking Service..."
python -m pip install --quiet -e "${ROOT_DIR}/banking_service"

echo "  -> Installing AI Chat Service..."
python -m pip install --quiet -e "${ROOT_DIR}/ai_service"

echo "  -> Installing Frontend requirements..."
python -m pip install --quiet -r "${ROOT_DIR}/frontend/requirements.txt"

# ------------------------------------------------------------------------------
# 5. Database Migrations & Fixture Seeding
# ------------------------------------------------------------------------------
ALEMBIC_BIN="alembic"
if [ -f "${VENV_DIR}/bin/alembic" ]; then
    ALEMBIC_BIN="${VENV_DIR}/bin/alembic"
elif [ -f "${VENV_DIR}/Scripts/alembic.exe" ]; then
    ALEMBIC_BIN="${VENV_DIR}/Scripts/alembic.exe"
fi

echo "🔄 Running database migrations..."
(
    cd "${ROOT_DIR}/banking_service"
    "$ALEMBIC_BIN" upgrade head
)
(
    cd "${ROOT_DIR}/ai_service"
    "$ALEMBIC_BIN" upgrade head
)

echo "🌱 Seeding demo fixtures (admin, customer, accounts, loans, cards)..."
(
    cd "${ROOT_DIR}/banking_service"
    python -m app.seed
)

# ------------------------------------------------------------------------------
# 6. Process Management & Cleanup Traps
# ------------------------------------------------------------------------------
BANKING_PID=""
AI_PID=""
FRONTEND_PID=""

cleanup() {
    echo ""
    echo "🛑 Shutting down local servers..."
    if [ -n "$FRONTEND_PID" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
        echo "  • Stopping Frontend (PID: $FRONTEND_PID)..."
        kill "$FRONTEND_PID" 2>/dev/null || true
    fi
    if [ -n "$AI_PID" ] && kill -0 "$AI_PID" 2>/dev/null; then
        echo "  • Stopping AI Service (PID: $AI_PID)..."
        kill "$AI_PID" 2>/dev/null || true
    fi
    if [ -n "$BANKING_PID" ] && kill -0 "$BANKING_PID" 2>/dev/null; then
        echo "  • Stopping Banking Service (PID: $BANKING_PID)..."
        kill "$BANKING_PID" 2>/dev/null || true
    fi
    echo "✓ All servers stopped."
}
trap cleanup EXIT INT TERM

# ------------------------------------------------------------------------------
# 7. Start Services
# ------------------------------------------------------------------------------
echo "🚀 Starting servers..."

# Start Banking Service (port 8001)
(
    cd "${ROOT_DIR}/banking_service"
    uvicorn app.main:app --host 0.0.0.0 --port 8001 --log-level warning
) &
BANKING_PID=$!
echo "  • Banking Service started (PID: $BANKING_PID)"

# Wait for Banking Service health
for i in $(seq 1 30); do
    if python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')" &>/dev/null; then
        echo "    ✓ Banking Service is healthy on port 8001"
        break
    fi
    sleep 1
    if [ "$i" -eq 30 ]; then
        echo "❌ Banking service failed to become healthy within 30s"
        exit 1
    fi
done

# Start AI Service (port 8002)
(
    cd "${ROOT_DIR}/ai_service"
    uvicorn app.main:app --host 0.0.0.0 --port 8002 --log-level warning
) &
AI_PID=$!
echo "  • AI Chat Service started (PID: $AI_PID)"

# Wait for AI Service health
for i in $(seq 1 30); do
    if python -c "import urllib.request; urllib.request.urlopen('http://localhost:8002/health')" &>/dev/null; then
        echo "    ✓ AI Service is healthy on port 8002"
        break
    fi
    sleep 1
    if [ "$i" -eq 30 ]; then
        echo "❌ AI service failed to become healthy within 30s"
        exit 1
    fi
done

# Start Streamlit Frontend (port 8501)
(
    cd "${ROOT_DIR}/frontend"
    streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
) &
FRONTEND_PID=$!
echo "  • Frontend Web App started (PID: $FRONTEND_PID)"

# Wait for Frontend health
for i in $(seq 1 30); do
    if python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" &>/dev/null; then
        echo "    ✓ Frontend Web App is healthy on port 8501"
        break
    fi
    sleep 1
    if [ "$i" -eq 30 ]; then
        echo "❌ Frontend failed to become healthy within 30s"
        exit 1
    fi
done

echo ""
echo "========================================================================"
echo "🎉 ALL LOCAL BANKING AI PLATFORM SERVICES ARE UP AND RUNNING!"
echo "========================================================================"
echo ""
echo "  🌐 Streamlit Web UI:        http://localhost:8501"
echo "  🏦 Core Banking API:        http://localhost:8001 (Docs: http://localhost:8001/docs)"
echo "  🤖 AI Chat Service API:     http://localhost:8002 (Docs: http://localhost:8002/docs)"
echo ""
echo "  🔑 Pre-Seeded Testing Accounts:"
echo "     • Admin Account:    admin@bank.local    / Admin@Bank2024!    (PIN: 9999)"
echo "     • Customer Account: customer@bank.local / Customer@Bank2024! (PIN: 1234)"
echo "     • Bank Account:     XXXXXX0400          / Balance: ₹1,00,000.00"
echo "     • Credit Card:      VISA ending 4321    / Limit: ₹2,00,000.00"
echo ""
echo "  [Press Ctrl+C to stop all servers and exit]"
echo "========================================================================"
echo ""

wait
