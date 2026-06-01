# Phase 0 bootstrap script
# Run once to create venv, install deps, create directories, verify setup

Write-Host "=== UPSC Agent: Environment Bootstrap ===" -ForegroundColor Cyan

# 1. Create virtual environment
Write-Host "`n[1/6] Creating virtual environment..." -ForegroundColor Yellow
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Upgrade pip
Write-Host "[2/6] Upgrading pip..." -ForegroundColor Yellow
python -m pip install --upgrade pip

# 3. Install Phase 1 + dev dependencies
Write-Host "[3/6] Installing dependencies..." -ForegroundColor Yellow
pip install -r requirements/base.txt -r requirements/dev.txt

# 4. Create data directories
Write-Host "[4/6] Creating data directories..." -ForegroundColor Yellow
$dirs = @(
    "UPSC_Agent_Data",
    "UPSC_Agent_Data/vector_store/syllabus_collection",
    "UPSC_Agent_Data/vector_store/pyq_collection",
    "UPSC_Agent_Data/static_assets/pyq/prelims",
    "UPSC_Agent_Data/static_assets/pyq/mains",
    "UPSC_Agent_Data/static_assets/topper_copies",
    "UPSC_Agent_Data/exports",
    "UPSC_Agent_Data/archive",
    "logs"
)
foreach ($dir in $dirs) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
}

# 5. Create .env from template if not exists
Write-Host "[5/6] Checking .env file..." -ForegroundColor Yellow
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "  Created .env from template. Please edit with your API key." -ForegroundColor Red
}

# 6. Verify installation
Write-Host "[6/6] Verifying installation..." -ForegroundColor Yellow
python -c "
import fastapi; print(f'  FastAPI {fastapi.__version__}')
import sqlalchemy; print(f'  SQLAlchemy {sqlalchemy.__version__}')
import pydantic; print(f'  Pydantic {pydantic.__version__}')
import yaml; print(f'  PyYAML {yaml.__version__}')
import pytest; print(f'  Pytest {pytest.__version__}')
import alembic; print(f'  Alembic {alembic.__version__}')
print('  All dependencies verified.')
"

Write-Host "`n=== Bootstrap complete ===" -ForegroundColor Green
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Edit .env with your GOOGLE_API_KEY"
Write-Host "  2. Activate venv: .\.venv\Scripts\Activate.ps1"
Write-Host "  3. Run tests: pytest"
