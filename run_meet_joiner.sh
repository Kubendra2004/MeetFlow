#!/bin/bash
# ==============================================================================
# Linux Startup Script for Google Meet Auto-Joiner & VTU Diary
# Automatically detects current directory and executes the Python bot.
# ==============================================================================

# Get the directory of this script (works even if run from elsewhere)
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "======================================================"
echo " Starting Google Meet Bot & VTU Diary Auto-Fill (Linux)"
echo "======================================================"
echo "Checking dependencies..."

# If you use a virtual environment on Linux, uncomment the next line:
# source venv/bin/activate

# Execute the main bot script
python3 meet_joiner.py

echo ""
echo "Done! The VTU diary process runs automatically upon conclusion."
# The pause allows you to read the output before the terminal closes
read -n 1 -s -r -p "Press any key to close..."
echo ""
