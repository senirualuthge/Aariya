#!/bin/bash
# AI Girl - Fixv2 Setup Script
# Run this script to set up the server environment

echo -e "\033[36m=== AI Girl Fixv2 Setup ===\033[0m"

# Check Python version
echo -e "\n\033[33mChecking Python version...\033[0m"
python3 --version || python --version

# Set up virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo -e "\n\033[33mCreating virtual environment...\033[0m"
    python3 -m venv venv || python -m venv venv
fi

echo -e "\n\033[33mActivating virtual environment...\033[0m"
source venv/bin/activate

# Install Python dependencies
echo -e "\n\033[33mInstalling Python dependencies...\033[0m"
pip install -r server/requirements.txt

# Run database migrations
echo -e "\n\033[33mRunning database migrations...\033[0m"
python run_migrations.py

# Check if Node.js is installed
echo -e "\n\033[33mChecking Node.js...\033[0m"
node --version

# Install Node.js dependencies (if needed)
if [ -f "package.json" ]; then
    echo -e "\n\033[33mInstalling Node.js dependencies...\033[0m"
    npm install
fi

echo -e "\n\033[32m=== Setup Complete! ===\033[0m"
echo -e "\n\033[36mTo start the server, run:\033[0m"
echo -e "  ./run_cli.sh or ./run_gui.sh"
