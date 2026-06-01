# Activate venv and run tests with coverage
.\.venv\Scripts\Activate.ps1
pytest --cov=src --cov-report=term-missing -v
