# Playwright MCP Agent

An LLM-driven agent that uses Playwright MCP tools and a local Qwen model (via Ollama) to autonomously browse the web, fetch data, and search research papers. The LLM decides which tools to call based on natural-language requests and returns ORIGINAL content without summarization.

## Features

- **22 Playwright MCP Tools** for browser automation, content extraction, and web search
- **arXiv Integration** - Search, retrieve metadata, and download research papers
- **IEEE Xplore Integration** - Search and access IEEE research papers
- **Autonomous Tool-Calling Loop** - LLM chains multiple tools to complete complex tasks
- **Original Content Policy** - Returns full, unmodified content from web pages
- **Modern React UI** with real-time activity logging and file management

## Architecture

```
┌─────────────────┐
│   React UI      │  ← User interface (port 5173)
│   (Vite)        │
└────────┬────────┘
         │
         ↓ HTTP
┌─────────────────┐
│  Bridge Server  │  ← Express.js (port 3001)
│   (Node.js)     │
└────────┬────────┘
         │
         ↓ stdio MCP
┌─────────────────┐
│   MCP Server    │  ← FastMCP + Playwright (Python)
│   (Python)      │
└─────────────────┘

         ↑
         │ API calls
         ↓
┌─────────────────┐
│  Ollama Server  │  ← Qwen 2.5 model (port 11434)
└─────────────────┘
```

## Tech Stack

- **Backend**: Python 3.11+, FastMCP, Playwright, BeautifulSoup4, httpx, arxiv
- **Bridge**: Node.js, Express, @modelcontextprotocol/sdk
- **Frontend**: React 18, Vite, Tailwind CSS, react-markdown
- **LLM**: Ollama with qwen2.5 model

## Available Tools (22 total)

### Navigation (5 tools)
- `browser_launch` - Launch Chromium browser
- `navigate` - Navigate to URL
- `click` - Click element
- `fill` - Fill input field
- `browser_close` - Close browser

### Extraction (4 tools)
- `get_content` - Extract full page content (text/markdown/html)
- `extract_table` - Extract HTML table data (JSON/CSV)
- `screenshot` - Capture screenshot
- `execute_script` - Run JavaScript on page

### Search (3 tools)
- `search_web` - Search Google/Bing/DuckDuckGo
- `wait_for_element` - Wait for element to appear
- `scroll_page` - Scroll page up/down

### arXiv Research (4 tools)
- `arxiv_search` - Search arXiv papers
- `arxiv_get_paper` - Get paper metadata
- `arxiv_download_pdf` - Download paper PDF
- `arxiv_get_recent` - Get recent papers in category

### IEEE Research (3 tools)
- `ieee_search` - Search IEEE Xplore
- `ieee_get_paper` - Get paper metadata
- `ieee_download_pdf` - Download paper PDF (if accessible)

## Installation

### Prerequisites

1. **Python 3.11+**
2. **Node.js 18+**
3. **Ollama** - [Install from ollama.ai](https://ollama.ai)

### Step 1: Install Ollama and Pull Model

```bash
# Install Ollama from https://ollama.ai

# Pull the Qwen 2.5 model (choose size based on your hardware)
ollama pull qwen2.5          # 7B (recommended)
# or
ollama pull qwen2.5:14b      # 14B (requires more VRAM)

# Start Ollama server (usually starts automatically)
ollama serve
```

### Step 2: Install Python Dependencies

```bash
cd playwright-mcp-agent

# Create virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
```

### Step 3: Install Bridge Server Dependencies

```bash
cd bridge_server
npm install
```

### Step 4: Install UI Dependencies

```bash
cd ../ui
npm install
```

## Running the Application

You need to run three services in separate terminals:

### Terminal 1: Ollama (if not already running)

```bash
ollama serve
```

### Terminal 2: Bridge Server (starts Python MCP server automatically)

```bash
cd bridge_server
npm start
```

You should see:
```
✓ Bridge server running on http://localhost:3001
✓ MCP connected with 22 tools
```

### Terminal 3: React UI

```bash
cd ui
npm run dev
```

Then open **http://localhost:5173** in your browser.

## Usage Examples

### 1. Get News

```
Get the latest AI news from top sources
```

The agent will:
1. Launch browser
2. Search for "AI news"
3. Navigate to the first result
4. Extract full article content
5. Return the original content

### 2. Weather

```
What's the weather in Tokyo?
```

The agent will:
1. Launch browser
2. Search for "weather Tokyo"
3. Navigate to weather page
4. Extract weather information
5. Return full forecast

### 3. arXiv Papers

```
Find recent papers on large language models from the last 7 days
```

The agent will:
1. Search arXiv for "large language models"
2. Return full list with titles, authors, abstracts, and PDF links

```
Download the paper with ID 2301.12345
```

The agent will:
1. Fetch paper metadata
2. Download PDF to `mcp_server/downloads/`
3. Return download confirmation with file path

### 4. IEEE Papers

```
Search IEEE for papers on neural networks
```

The agent will:
1. Launch browser
2. Search IEEE Xplore
3. Extract full results with metadata
4. Return all papers found

### 5. Web Search

```
Search for latest trends in quantum computing and get content from the top 3 results
```

The agent will:
1. Launch browser
2. Search Google
3. Navigate to each of the top 3 results
4. Extract full content from each page
5. Return all content

## System Prompt Behavior

The agent follows these rules (defined in `ui/src/config.js`):

- **NEVER summarize** content from tools
- **Return ORIGINAL content** exactly as received
- Only add minimal framing (e.g., "Here is the content from [url]:")
- Show full errors and suggest fixes
- Execute tool call chains autonomously

## Tool-Call Loop

The agent can make up to 15 sequential tool calls to complete a task. For example:

```
User: "Get latest AI news"
  ↓
1. browser_launch()
2. search_web(query="AI news")
3. navigate(url=<first result>)
4. get_content(format="markdown")
  ↓
Returns: Full article content
```

This happens automatically — the LLM decides which tools to call and when.

## File Downloads

Downloaded files (PDFs, screenshots) are saved to:
```
mcp_server/downloads/
```

You can view and download them from the UI's **File Manager** panel.

## Configuration

Edit `ui/src/config.js` to customize:

- `OLLAMA_URL` - Ollama server URL (default: http://localhost:11434)
- `BRIDGE_URL` - Bridge server URL (default: http://localhost:3001)
- `MODEL` - Ollama model name (default: qwen2.5)
- `SYSTEM_PROMPT` - Agent behavior instructions

## Troubleshooting

### Ollama Connection Failed

```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Start Ollama
ollama serve
```

### Bridge Server Not Connected

```bash
# Check bridge server logs
cd bridge_server
npm start

# Verify Python environment
python3 -m pip list | grep fastmcp
```

### Browser Launch Failed

```bash
# Reinstall Playwright browsers
playwright install chromium
```

### IEEE/Google Blocking Requests

Some sites may block automated access. If you see CAPTCHA or access denied:
- Try again later
- Use a different search engine (DuckDuckGo is less restrictive)
- For IEEE downloads, access through your institution

## Development

### Project Structure

```
playwright-mcp-agent/
├── mcp_server/              # Python MCP server
│   ├── server.py            # FastMCP entry point
│   ├── browser_manager.py   # Singleton browser manager
│   ├── schemas.py           # Pydantic input models
│   ├── tools/               # Tool implementations
│   │   ├── navigation.py
│   │   ├── extraction.py
│   │   ├── search.py
│   │   ├── arxiv_tools.py
│   │   └── ieee_tools.py
│   ├── utils/               # Utilities
│   │   ├── parser.py        # HTML parsing
│   │   ├── file_manager.py  # File operations
│   │   └── errors.py        # Error formatting
│   └── downloads/           # Downloaded files
│
├── bridge_server/           # Node.js HTTP bridge
│   ├── server.js            # Express server
│   └── package.json
│
└── ui/                      # React frontend
    ├── src/
    │   ├── App.jsx          # Main app
    │   ├── config.js        # Configuration
    │   ├── components/      # UI components
    │   └── services/        # API services
    └── package.json
```

### Adding New Tools

1. **Define schema** in `mcp_server/schemas.py`:
```python
class MyToolInput(BaseModel):
    param: str = Field(description="Parameter description")
```

2. **Implement tool** in appropriate file under `mcp_server/tools/`:
```python
async def my_tool(arguments: dict) -> str:
    try:
        input_data = MyToolInput(**arguments)
        # Tool logic here
        return json.dumps(result, indent=2)
    except Exception as e:
        return format_error("my_tool", e)
```

3. **Register tool** in `mcp_server/server.py`:
```python
@mcp.tool()
async def my_tool(param: str) -> str:
    """Tool description for LLM"""
    return await tools.my_tool({"param": param})
```

4. Restart bridge server to load new tool.

## Performance

- **Ollama inference**: Depends on model size and hardware
  - qwen2.5:7b - Fast on consumer GPUs (RTX 3060+)
  - qwen2.5:14b - Requires 16GB+ VRAM
- **Browser operations**: 2-5 seconds per page load
- **arXiv API**: < 1 second per request
- **Tool-call loop**: Can take 30-60 seconds for complex multi-step tasks

## License

MIT

## Credits

Built with:
- [FastMCP](https://github.com/jlowin/fastmcp) - MCP server framework
- [Playwright](https://playwright.dev) - Browser automation
- [Ollama](https://ollama.ai) - Local LLM inference
- [Model Context Protocol](https://modelcontextprotocol.io) - Tool integration standard

## Support

For issues or questions:
1. Check the Troubleshooting section
2. Review bridge server logs
3. Verify all services are running (Ollama, bridge, UI)
4. Check that qwen2.5 model is installed: `ollama list`

---

**Important**: This agent returns ORIGINAL content from web pages. Make sure you have permission to scrape content from the sites you access.
