#!/bin/bash

# Playwright MCP Agent - Quick Start Script

set -e

echo "=================================="
echo "Playwright MCP Agent Setup"
echo "=================================="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if Ollama is installed
echo -n "Checking Ollama... "
if ! command -v ollama &> /dev/null; then
    echo -e "${RED}✗${NC}"
    echo ""
    echo "Ollama is not installed. Please install it from:"
    echo "  https://ollama.ai"
    exit 1
fi
echo -e "${GREEN}✓${NC}"

# Check if Ollama is running and has qwen2.5 model
echo -n "Checking Ollama status... "
if ! curl -s http://localhost:11434/api/tags &> /dev/null; then
    echo -e "${YELLOW}⚠${NC}"
    echo ""
    echo "Ollama is not running. Starting Ollama..."
    ollama serve &
    sleep 2
else
    echo -e "${GREEN}✓${NC}"
fi

echo -n "Checking qwen2.5 model... "
if ollama list | grep -q "qwen2.5"; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗${NC}"
    echo ""
    echo "qwen2.5 model not found. Pulling model..."
    echo "This may take a while (several GB download)..."
    ollama pull qwen2.5
fi

# Check Python
echo -n "Checking Python 3.11+... "
PYTHON_CMD=""
for candidate in python3.12 python3.11 python3; do
    if command -v "$candidate" &> /dev/null; then
        if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' &> /dev/null; then
            PYTHON_CMD="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo -e "${RED}✗${NC}"
    echo "Python 3.11+ is required. Please install Python 3.11 or higher."
    exit 1
fi

PYTHON_VERSION=$($PYTHON_CMD --version | cut -d' ' -f2)
echo -e "${GREEN}✓${NC} (v$PYTHON_VERSION via $PYTHON_CMD)"

# Check Node.js
echo -n "Checking Node.js... "
if ! command -v node &> /dev/null; then
    echo -e "${RED}✗${NC}"
    echo "Node.js is required. Please install Node.js 18 or higher."
    exit 1
fi
NODE_VERSION=$(node --version)
echo -e "${GREEN}✓${NC} ($NODE_VERSION)"

echo ""
echo "=================================="
echo "Installing Dependencies"
echo "=================================="
echo ""

SETUP_MARKER=".setup_complete"

# Install Python dependencies
if [ -d "venv" ]; then
    if [ ! -x "venv/bin/python" ] || ! venv/bin/python -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' &> /dev/null; then
        echo "Existing virtual environment is incompatible. Recreating with $PYTHON_CMD..."
        rm -rf venv
        rm -f "$SETUP_MARKER"
    fi
fi

if [ ! -d "venv" ]; then
    echo "Creating Python virtual environment with $PYTHON_CMD..."
    "$PYTHON_CMD" -m venv venv
fi

echo "Activating virtual environment..."
source venv/bin/activate

# Check if dependencies are installed
if [ -f "$SETUP_MARKER" ] && [ requirements.txt -nt "$SETUP_MARKER" ]; then
    echo "requirements.txt changed since last setup. Reinstalling dependencies..."
    rm -f "$SETUP_MARKER"
fi

if [ ! -f "$SETUP_MARKER" ]; then
    echo "First-time setup detected. Installing dependencies..."
    
    echo "Installing Python packages..."
    pip install -q -r requirements.txt
    
    echo "Installing Playwright browsers..."
    export PLAYWRIGHT_BROWSERS_PATH="$(pwd)/.playwright-browsers"
    playwright install chromium
    
    # Install Node dependencies
    echo ""
    echo "Installing Bridge Server dependencies..."
    cd bridge_server
    npm install --silent
    cd ..
    
    echo ""
    echo "Installing UI dependencies..."
    cd ui
    npm install --silent
    cd ..
    
    # Mark setup as complete
    touch "$SETUP_MARKER"
    echo "✓ Setup complete! Next run will be faster."
else
    echo "Dependencies already installed. Skipping installation..."
    echo "(To reinstall, delete .setup_complete file)"
    export PLAYWRIGHT_BROWSERS_PATH="$(pwd)/.playwright-browsers"
fi

echo ""
echo -e "${GREEN}✓ Setup complete!${NC}"
echo ""
echo "=================================="
echo "Starting Services"
echo "=================================="
echo ""

echo "Starting Bridge Server (Node.js + Python MCP)..."
cd bridge_server
npm start &
BRIDGE_PID=$!
cd ..

# Wait for bridge to start
echo "Waiting for bridge server to initialize..."
for i in {1..30}; do
    if curl -s http://localhost:3001/health &> /dev/null; then
        echo -e "${GREEN}✓ Bridge server ready${NC}"
        break
    fi
    sleep 1
done

echo ""
echo "Starting UI (Vite)..."
cd ui
npm run dev &
UI_PID=$!
cd ..

echo ""
echo "=================================="
echo -e "${GREEN}All services started!${NC}"
echo "=================================="
echo ""
echo "Open your browser to:"
echo -e "${GREEN}http://localhost:5173${NC}"
echo ""
echo "Press Ctrl+C to stop all services"
echo ""

# Trap Ctrl+C and cleanup
trap "echo ''; echo 'Stopping services...'; kill $BRIDGE_PID $UI_PID 2>/dev/null; exit" INT

# Wait for processes
wait
