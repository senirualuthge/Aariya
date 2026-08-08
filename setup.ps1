# AI Girl - Fixv2 Setup Script
# Run this script to set up the server environment

Write-Host "=== AI Girl Fixv2 Setup ===" -ForegroundColor Cyan

# Check Python version
Write-Host "`nChecking Python version..." -ForegroundColor Yellow
python --version

# Install Python dependencies
Write-Host "`nInstalling Python dependencies..." -ForegroundColor Yellow
pip install -r server/requirements.txt

# Run database migrations
Write-Host "`nRunning database migrations..." -ForegroundColor Yellow
python run_migrations.py

# Check if Node.js is installed
Write-Host "`nChecking Node.js..." -ForegroundColor Yellow
node --version

# Install Node.js dependencies (if needed)
if (Test-Path "package.json") {
    Write-Host "`nInstalling Node.js dependencies..." -ForegroundColor Yellow
    npm install
}

Write-Host "`n=== Setup Complete! ===" -ForegroundColor Green
Write-Host "`nTo start the server, run:" -ForegroundColor Cyan
Write-Host "  python server/main.py" -ForegroundColor White
Write-Host "`nTo start the client (if needed), run:" -ForegroundColor Cyan
Write-Host "  npm run dev" -ForegroundColor White
