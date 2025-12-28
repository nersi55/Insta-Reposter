#!/bin/bash

# Script to set up virtual environment for Video_bot.py

echo "🚀 Setting up Video Bot environment..."

# Check for Python 3.13 (required for pydantic-core compatibility)
if command -v python3.13 &> /dev/null; then
    PYTHON_CMD="python3.13"
    echo "✅ Found Python 3.13"
elif command -v python3.12 &> /dev/null; then
    PYTHON_CMD="python3.12"
    echo "✅ Found Python 3.12"
elif command -v python3.11 &> /dev/null; then
    PYTHON_CMD="python3.11"
    echo "✅ Found Python 3.11"
else
    PYTHON_CMD="python3"
    echo "⚠️  Using default python3 (may cause issues with pydantic-core if Python 3.14+)"
fi

# Load Rust environment if available (needed for building some packages)
if [ -f "$HOME/.cargo/env" ]; then
    source "$HOME/.cargo/env"
fi

# Create virtual environment
echo "📦 Creating virtual environment 'venv_video_bot' with $PYTHON_CMD..."
$PYTHON_CMD -m venv venv_video_bot

# Activate virtual environment
echo "✅ Activating virtual environment..."
source venv_video_bot/bin/activate

# Upgrade pip
echo "⬆️  Upgrading pip..."
pip install --upgrade pip setuptools wheel

# Install dependencies
echo "📥 Installing dependencies from requirements.txt..."
pip install -r requirements.txt

# Check if .env file exists
if [ ! -f .env ]; then
    echo "⚠️  .env file not found!"
    echo "📝 Creating .env.example file..."
    echo "Please copy .env.example to .env and fill in your values."
    if [ ! -f .env.example ]; then
        cat > .env.example << EOF
# Instagram Graph API
ACCESS_TOKEN=your_access_token_here
INSTAGRAM_ACCOUNT_ID=your_instagram_account_id_here

# Gemini API
GEMINI_API_KEY=your_gemini_api_key_here

# Post Interval (in minutes)
POST_INTERVAL_MINUTES=1
EOF
    fi
else
    echo "✅ .env file found!"
fi

# Check if credentials.json exists
if [ ! -f credentials.json ]; then
    echo "⚠️  credentials.json not found!"
    echo "Please add your Google Service Account credentials.json file."
fi

echo ""
echo "✨ Setup complete!"
echo ""
echo "To activate the environment, run:"
echo "  source venv_video_bot/bin/activate"
echo ""
echo "To run Video_bot.py:"
echo "  python Video_bot.py"
echo ""
echo "To deactivate the environment:"
echo "  deactivate"

