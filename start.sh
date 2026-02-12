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
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗${NC}"
    echo "Python 3 is required. Please install Python 3.11 or higher."
    exit 1
fi
PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
echo -e "${GREEN}✓${NC} (v$PYTHON_VERSION)"

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

# Install Python dependencies
if [ ! -d "venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv venv
fi

echo "Activating virtual environment..."
source venv/bin/activate

echo "Installing Python packages..."
pip install -q -r requirements.txt

echo "Installing Playwright browsers..."
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
