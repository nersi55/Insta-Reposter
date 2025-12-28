#!/bin/bash

# Script to run Video_bot.py in its virtual environment

# Check if virtual environment exists
if [ ! -d "venv_video_bot" ]; then
    echo "❌ Virtual environment not found!"
    echo "Please run setup_video_bot.sh first"
    exit 1
fi

# Activate virtual environment
echo "🔌 Activating virtual environment..."
source venv_video_bot/bin/activate

# Check if .env file exists
if [ ! -f .env ]; then
    echo "❌ .env file not found!"
    echo "Please create .env file from .env.example and fill in your values."
    deactivate
    exit 1
fi

# Check if credentials.json exists
if [ ! -f credentials.json ]; then
    echo "⚠️  Warning: credentials.json not found!"
    echo "Video bot may not work without Google Sheets credentials."
fi

# Run the bot
echo "🤖 Starting Video Bot..."
python Video_bot.py

# Deactivate virtual environment when script exits
deactivate

