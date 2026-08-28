#!/bin/bash
# CGK Linens Discord Bot Launcher (macOS)
# Created by Aljay Leodones for CGK Linens

cd "$(dirname "$0")"

echo "=========================================="
echo " Starting CGK Linens Discord Bot"
echo " Created by Aljay Leodones"
echo "=========================================="

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "[1/3] Creating Python virtual environment..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "Error: Failed to create virtual environment. Ensure Python 3 is installed."
        read -p "Press [Enter] to exit..."
        exit 1
    fi
fi

# Activate virtual environment
source venv/bin/activate

# Ensure dependencies are installed
echo "[2/3] Checking dependencies..."
pip install -r requirements.txt --quiet

# Launch bot
echo "[3/3] Launching bot..."
python3 main.py

# Keep terminal open if bot stops
echo ""
echo "Bot process has stopped."
read -p "Press [Enter] to close this window..."
