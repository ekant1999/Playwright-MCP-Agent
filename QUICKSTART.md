# Quick Reference - Playwright MCP Agent

## Quick Start

```bash
# 1. Install Ollama and pull model
ollama pull qwen2.5

# 2. Run the automated setup and start script
./start.sh
```

OR run services manually:

```bash
# Terminal 1: Bridge Server
cd bridge_server && npm start

# Terminal 2: UI
cd ui && npm run dev

# Terminal 3: (Optional) Ollama if not running
ollama serve
```

Then open: **http://localhost:5173**

## Example Queries

### News & Web Content
```
Get the latest AI news from top sources
What's the weather in London?
Search for recent articles about quantum computing
```

### Research Papers (arXiv)
```
Find papers on large language models from the last week
Get the abstract for arXiv paper 2301.12345
Download the PDF for paper 2301.12345
Search for recent papers in cs.CV category
```

### Research Papers (IEEE)
```
Search IEEE for papers on neural networks
Get details for this IEEE paper: [paste URL]
Find IEEE papers on quantum computing published this year
```

### Multi-Step Tasks
```
Search for top 3 articles about climate change and extract full content from each
Find recent arXiv papers on transformers and download the top 3 PDFs
Get weather forecasts for Tokyo, London, and New York
```

## Tool Categories

### Browser Control
- `browser_launch` - Start browser (headless or headed)
- `navigate` - Go to URL
- `click` - Click element by CSS selector
- `fill` - Fill input field
- `browser_close` - Close browser

### Content Extraction
- `get_content` - Get page content (text/markdown/html)
- `extract_table` - Extract table data as JSON/CSV
- `screenshot` - Take page screenshot
- `execute_script` - Run custom JavaScript

### Web Search
- `search_web` - Google/Bing/DuckDuckGo search
- `wait_for_element` - Wait for element to load
- `scroll_page` - Scroll up/down

### arXiv Research
- `arxiv_search` - Search papers by query/category
- `arxiv_get_paper` - Get paper metadata by ID
- `arxiv_download_pdf` - Download paper PDF
- `arxiv_get_recent` - Get recent papers in category

### IEEE Research
- `ieee_search` - Search IEEE Xplore
- `ieee_get_paper` - Get paper details by URL
- `ieee_download_pdf` - Download PDF (if accessible)

## Common Issues

### "Ollama not running"
```bash
ollama serve
# or check if it's already running
curl http://localhost:11434/api/tags
```

### "qwen2.5 model not found"
```bash
ollama pull qwen2.5
# or for larger model
ollama pull qwen2.5:14b
```

### "Bridge server not connected"
```bash
# Check Python environment
source venv/bin/activate
python3 -m pip install -r requirements.txt

# Restart bridge
cd bridge_server && npm start
```

### "Browser launch failed"
```bash
# Reinstall Playwright
source venv/bin/activate
playwright install chromium
```

### IEEE/Google blocks access
- Try DuckDuckGo: agent will auto-retry
- Wait a few minutes and try again
- For IEEE downloads, use institutional access

## API Endpoints (Bridge Server)

```
GET  /health              - Health check
GET  /tools               - List all tools
POST /tools/call          - Execute a tool
GET  /files               - List downloaded files
GET  /files/:filename     - Download a file
```

## Configuration Files

- `ui/src/config.js` - Frontend config (Ollama URL, model, system prompt)
- `bridge_server/server.js` - Bridge server port and MCP config
- `requirements.txt` - Python dependencies
- `bridge_server/package.json` - Node dependencies

## File Locations

- **Downloaded files**: `mcp_server/downloads/`
- **Python MCP server**: `mcp_server/server.py`
- **Bridge server**: `bridge_server/server.js`
- **UI**: `ui/src/App.jsx`

## System Prompt Rules

The agent follows these rules (cannot be overridden by user):

1. **NEVER summarize** - Return original content exactly as received
2. **No paraphrasing** - Content from tools must be verbatim
3. **Minimal framing** - Only add "Here is the content from [source]:"
4. **Full errors** - Show complete error messages with suggestions
5. **Chain tools** - Execute multiple tools to complete tasks

## Performance Tips

1. **Use arXiv tools directly** - Don't need browser for arXiv
2. **Specify formats** - Use `format="markdown"` for better readability
3. **Close browser** - Call `browser_close` when done to free resources
4. **Smaller model** - Use `qwen2.5:7b` for faster responses
5. **Specific queries** - More specific queries = better tool selection

## Development

### Add a new tool

1. Define schema in `mcp_server/schemas.py`
2. Implement in `mcp_server/tools/[category].py`
3. Register in `mcp_server/server.py`
4. Restart bridge server

### Modify system prompt

Edit `SYSTEM_PROMPT` in `ui/src/config.js`

### Change UI styling

Edit `ui/src/styles/app.css` (Tailwind CSS)

### Debug tool execution

Check bridge server console output or the Activity Log in the UI

## Architecture

```
User Query → React UI → Ollama (LLM) → Bridge Server → MCP Server → Playwright
                  ↑                                          ↓
                  └──────────── Tool Results ────────────────┘
```

The LLM decides which tools to call based on the query. The bridge server executes tools via the MCP protocol and returns results to the LLM, which may call more tools or return the final answer.

## Useful Commands

```bash
# List Ollama models
ollama list

# Check Ollama status
curl http://localhost:11434/api/tags

# Check bridge server
curl http://localhost:3001/health

# View available tools
curl http://localhost:3001/tools

# Rebuild UI
cd ui && npm run build

# Run in production mode
cd ui && npm run preview
```

## Environment Variables

Optional environment variables:

```bash
# Python path (if not in PATH)
export PYTHON_PATH=/usr/local/bin/python3

# Ollama URL (if not localhost)
export OLLAMA_URL=http://your-ollama-server:11434
```

## Support

- Check logs in bridge server terminal
- Enable Playwright debug: `DEBUG=pw:api npm start`
- Verify all services running: Ollama + Bridge + UI
- Test Ollama directly: `ollama run qwen2.5 "Hello"`

---

**Quick Test**: Ask the agent "What tools do you have access to?" to verify everything is working.
