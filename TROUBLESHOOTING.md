# Troubleshooting Guide - Playwright MCP Agent

## Common Issues and Solutions

---

### 1. Ollama Connection Failed

**Symptoms:**
- UI shows "Ollama not running" error
- Red ✗ next to Ollama status

**Solutions:**

```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# If not running, start Ollama
ollama serve

# In a new terminal, verify it's working
ollama list
```

**If model is missing:**
```bash
ollama pull qwen2.5
```

**Alternative port:**
If Ollama is running on a different port, edit `ui/src/config.js`:
```javascript
export const OLLAMA_URL = 'http://localhost:YOUR_PORT';
```

---

### 2. Bridge Server Not Connected

**Symptoms:**
- UI shows "Bridge Server not connected"
- Red ✗ next to Bridge status
- Console shows "Connection refused" on port 3001

**Solutions:**

```bash
# Check if bridge server is running
curl http://localhost:3001/health

# If not, start it
cd bridge_server
npm start

# Check for errors in the terminal output
```

**Common causes:**

**A. Python not found:**
```bash
# Verify Python version
python3 --version  # Should be 3.11+

# If using a different Python path, set environment variable
export PYTHON_PATH=/usr/local/bin/python3
cd bridge_server && npm start
```

**B. Python dependencies not installed:**
```bash
cd ..  # Go to project root
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**C. Port 3001 already in use:**
```bash
# Find what's using port 3001
lsof -i :3001

# Kill the process or change the port in bridge_server/server.js
# Change: const PORT = 3002;
```

---

### 3. Browser Launch Failed

**Symptoms:**
- Tool execution fails with "Browser launch error"
- Activity log shows error for `browser_launch`

**Solutions:**

```bash
# Activate Python environment
source venv/bin/activate

# Reinstall Playwright browsers
playwright install chromium

# If still failing, install system dependencies (Linux)
playwright install-deps chromium
```

**On macOS with M1/M2:**
```bash
# Install Rosetta 2 if needed
softwareupdate --install-rosetta

# Reinstall Playwright
pip uninstall playwright
pip install playwright
playwright install chromium
```

---

### 4. MCP Tools Not Loading

**Symptoms:**
- Bridge server shows "0 tools loaded"
- UI shows empty tools sidebar

**Solutions:**

```bash
# Check Python MCP server logs
cd bridge_server
npm start

# Look for Python errors in the output
# Common issue: FastMCP not installed
```

**Reinstall FastMCP:**
```bash
source venv/bin/activate
pip uninstall fastmcp
pip install "fastmcp>=2.2.0,<3.0.0"
```

**Test MCP server directly:**
```bash
source venv/bin/activate
python3 -m mcp_server.server
# Should show MCP protocol messages
```

---

### 5. Search Engines Blocking Requests

**Symptoms:**
- `search_web` returns CAPTCHA or access denied
- Error: "Access blocked"

**Solutions:**

**A. Try a different search engine:**
```
Instead of: search_web("AI news", engine="google")
Try: search_web("AI news", engine="duckduckgo")
```

**B. Wait and retry:**
- Google/Bing may temporarily block automated requests
- Wait 5-10 minutes and try again

**C. Use headed browser (less likely to be blocked):**
```
browser_launch(headless=false)
```

---

### 6. IEEE Xplore Access Issues

**Symptoms:**
- `ieee_search` works but `ieee_download_pdf` fails
- Error: "PDF requires IEEE subscription"

**Solutions:**

**This is expected behavior.** IEEE papers often require:
- Institutional access (university/company subscription)
- Individual IEEE membership
- Pay-per-article purchase

**Workaround:**
1. Use `ieee_get_paper(url)` to get paper metadata
2. Access the PDF through your institution's proxy
3. Or download manually if you have access

**For freely accessible papers:**
- Some IEEE papers are open access and will download successfully
- Conference papers are sometimes freely available

---

### 7. arXiv Download Slow/Timeout

**Symptoms:**
- `arxiv_download_pdf` takes very long or times out
- Large PDFs fail to download

**Solutions:**

```bash
# Increase timeout in mcp_server/tools/arxiv_tools.py
# Find this line and increase timeout:
async with httpx.AsyncClient(timeout=60.0) as client:
# Change to:
async with httpx.AsyncClient(timeout=120.0) as client:
```

**Or retry:**
- arXiv servers may be slow during peak hours
- Try again later

---

### 8. UI Not Loading (Vite Errors)

**Symptoms:**
- Blank page at http://localhost:5173
- Console shows module errors

**Solutions:**

```bash
# Clear Vite cache and reinstall
cd ui
rm -rf node_modules package-lock.json dist
npm install
npm run dev
```

**If port 5173 is in use:**
```bash
# Vite will auto-select next available port
# Check terminal output for actual port
```

---

### 9. Tool Execution Timeout

**Symptoms:**
- Tool calls hang and never complete
- Activity log shows "pending" forever

**Solutions:**

**A. Check if browser is stuck:**
```bash
# Kill all Chromium processes
pkill -f chromium

# Restart bridge server
cd bridge_server
npm start
```

**B. Increase timeouts:**

Edit `mcp_server/tools/navigation.py`:
```python
# Find navigate() function
response = await page.goto(
    input_data.url,
    wait_until=input_data.wait_until,
    timeout=120000  # Increase from 60000 to 120000
)
```

---

### 10. "Reached maximum tool-call iterations"

**Symptoms:**
- Agent stops after many tool calls
- Message: "Reached maximum tool-call iterations"

**Cause:**
- Agent is stuck in a loop or task is too complex

**Solutions:**

**A. Simplify the query:**
```
Instead of: "Get content from 10 different news sites"
Try: "Get content from 3 news sites"
```

**B. Increase iteration limit:**

Edit `ui/src/services/ollama.js`:
```javascript
const MAX_ITERATIONS = 15;  // Increase to 20 or 25
```

**C. Break task into smaller parts:**
```
Step 1: "Search for AI news"
Step 2: "Navigate to the first result and get content"
```

---

### 11. Markdown Not Rendering

**Symptoms:**
- Chat shows raw markdown instead of formatted text
- Links, headers not styled

**Solutions:**

```bash
# Reinstall react-markdown
cd ui
npm uninstall react-markdown
npm install react-markdown@9.0.1

# Clear browser cache
# In browser: Ctrl/Cmd + Shift + R
```

---

### 12. Files Not Showing in File Manager

**Symptoms:**
- PDFs downloaded but not visible in UI
- File manager shows "No files yet"

**Solutions:**

```bash
# Check if files exist
ls -la mcp_server/downloads/

# If files exist, check bridge server endpoint
curl http://localhost:3001/files

# Restart bridge server if needed
cd bridge_server
npm start
```

---

### 13. CORS Errors in Browser Console

**Symptoms:**
- Console shows "CORS policy" errors
- Requests to bridge server fail

**Solutions:**

**Check bridge server CORS settings** in `bridge_server/server.js`:
```javascript
app.use(cors({
  origin: 'http://localhost:5173',  // Match your UI port
  credentials: true
}));
```

**If UI is on a different port:**
```javascript
app.use(cors({
  origin: ['http://localhost:5173', 'http://localhost:5174'],
  credentials: true
}));
```

---

### 14. Memory Issues / High CPU

**Symptoms:**
- System slows down
- Browser becomes unresponsive

**Solutions:**

```bash
# Close browser when done
# In chat, tell the agent: "Close the browser"

# Or manually kill processes
pkill -f chromium
```

**Reduce memory usage:**

Edit `mcp_server/browser_manager.py`:
```python
self._browser = await self._playwright.chromium.launch(
    headless=True,  # Use headless mode
    args=[
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',  # Add this
        '--disable-gpu'  # Add this
    ]
)
```

---

### 15. Model Response Too Slow

**Symptoms:**
- Long wait times for responses
- Agent takes 30+ seconds per message

**Solutions:**

**A. Use a smaller model:**
```bash
# Pull smaller model
ollama pull qwen2.5:7b  # Instead of 14b or 32b
```

**B. Check GPU usage:**
```bash
# Verify Ollama is using GPU
ollama ps

# If not using GPU, reinstall Ollama with CUDA support (NVIDIA)
# Or use Metal (macOS M1/M2)
```

**C. Reduce context:**
- Start a new conversation (clear old messages)
- Use more specific queries (less tool calls needed)

---

## Debug Mode

### Enable Verbose Logging

**Bridge Server:**
```bash
cd bridge_server
DEBUG=* npm start
```

**Playwright:**
```bash
cd bridge_server
DEBUG=pw:api npm start
```

**MCP Server:**
Add to `mcp_server/server.py`:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

---

## Health Checks

Run these commands to verify system status:

```bash
# 1. Check Ollama
curl http://localhost:11434/api/tags

# 2. Check Bridge
curl http://localhost:3001/health

# 3. Check Tools
curl http://localhost:3001/tools | jq '.tools | length'
# Should output: 22

# 4. Test Ollama inference
ollama run qwen2.5 "Hello"

# 5. Check Python environment
source venv/bin/activate
python3 -c "import fastmcp, playwright, arxiv; print('OK')"
```

---

## Getting Help

If issues persist:

1. **Check logs:**
   - Bridge server terminal output
   - Browser console (F12)
   - Python errors in bridge terminal

2. **Verify versions:**
   ```bash
   python3 --version  # 3.11+
   node --version     # 18+
   ollama --version
   ```

3. **Clean install:**
   ```bash
   # Remove everything and start fresh
   rm -rf venv node_modules ui/node_modules bridge_server/node_modules
   ./start.sh
   ```

4. **Test components individually:**
   - Test Ollama: `ollama run qwen2.5 "test"`
   - Test MCP: `python3 -m mcp_server.server`
   - Test Bridge: `curl http://localhost:3001/health`
   - Test UI: Open http://localhost:5173

---

## Known Limitations

1. **IEEE PDFs:** Most require institutional access
2. **Search Rate Limits:** Google/Bing may temporarily block
3. **Large Files:** PDFs >100MB may timeout
4. **Headless Detection:** Some sites detect headless browsers
5. **Dynamic Content:** Heavy JavaScript sites may not load fully

---

## Best Practices

1. **Close browser when done:** Saves memory
2. **Use specific queries:** Reduces tool calls
3. **Try DuckDuckGo first:** Less blocking than Google
4. **arXiv for papers:** Don't use browser for arXiv
5. **Restart periodically:** If running for hours

---

Need more help? Check:
- `README.md` - Full documentation
- `QUICKSTART.md` - Quick reference
- `PROJECT_SUMMARY.md` - Architecture overview
