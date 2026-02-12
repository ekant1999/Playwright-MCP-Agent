# Test Flows – Playwright MCP Agent

## Quick API tests (no UI)

With the **bridge server** running (`cd bridge_server && node server.js`):

```bash
./test_flows.sh
```

This checks:

- **arXiv search** – `arxiv_search("machine learning", max_results=2)`
- **arXiv get paper** – `arxiv_get_paper("2306.04338")`
- **arXiv download PDF** – `arxiv_download_pdf("2306.04338")` → file in `mcp_server/downloads/`
- **Health** – `GET /health`
- **Tools list** – `GET /tools`

---

## Full flows (via UI at http://localhost:5173)

Use these prompts in the chat to trigger each flow. The agent will call the tools in sequence.

### 1. Web search
**Prompt:** `Search the web for "Python tutorials" and return the first 5 results with title and URL.`

**Expected tools:** `browser_launch` → `search_web` (and optionally `navigate` + `get_content` if you ask for page content).

---

### 2. News
**Prompt:** `Get the latest tech news from one major site. Return the full article content.`

**Expected tools:** `browser_launch` → `search_web` → `navigate` → `get_content`.

---

### 3. Weather
**Prompt:** `What's the weather in London?`

**Expected tools:** `browser_launch` → `search_web` → `navigate` → `get_content`.

---

### 4. IEEE
**Prompt:** `Search IEEE for papers on "quantum computing" and return the first 5 results.`

**Expected tools:** `browser_launch` → `ieee_search`.

For one paper’s details:  
`Get the full details and abstract for this IEEE paper: [paste URL from results].`

**Expected tools:** `ieee_get_paper(url)`.

For PDF (if you have access):  
`Download the PDF for this IEEE paper: [URL].`

**Expected tools:** `ieee_download_pdf(url)` (may return “subscription required” for many papers).

---

### 5. arXiv
**Prompt:** `Find 3 recent arXiv papers on "large language models" and give full metadata and abstracts.`

**Expected tools:** `arxiv_search`.

**Prompt:** `Get full metadata for arXiv paper 2306.04338.`

**Expected tools:** `arxiv_get_paper`.

**Prompt:** `Download the PDF for arXiv paper 2306.04338.`

**Expected tools:** `arxiv_download_pdf` → file in **Downloaded Files** panel and in `mcp_server/downloads/`.

---

### 6. Screenshot
**Prompt:** `Go to https://example.com and take a full-page screenshot.`

**Expected tools:** `browser_launch` → `navigate` → `screenshot(full_page=true)`.

Check **Downloaded Files** for the image.

---

### 7. Content (text / markdown)
**Prompt:** `Open https://example.com and return the full page content as plain text.`

**Expected tools:** `browser_launch` → `navigate` → `get_content(format="text")`.

For markdown:  
`Open https://example.com and return the page content as markdown.`

**Expected tools:** `get_content(format="markdown")`.

---

## Browser requirement (Mac M1/M2)

Flows that use the browser (web search, news, weather, IEEE, screenshot, get_content) need Chromium. If you see **“Browser not launched”** or **“Executable doesn't exist”**:

1. **Use project browser path and install Chromium:**
   ```bash
   cd playwright-mcp-agent
   source venv/bin/activate
   PLAYWRIGHT_BROWSERS_PATH="$(pwd)/.playwright-browsers" playwright install chromium
   ```

2. **Restart the bridge** so the MCP server gets `PLAYWRIGHT_BROWSERS_PATH` (the bridge sets it automatically to `project/.playwright-browsers`).

3. On **Apple Silicon**, if the wrong architecture is installed (e.g. x64 only), run the install from an **arm64** shell so Playwright downloads arm64 Chromium:
   ```bash
   arch -arm64 bash -c 'source venv/bin/activate && PLAYWRIGHT_BROWSERS_PATH="$(pwd)/.playwright-browsers" playwright install chromium'
   ```
   (Requires network; if it fails, use the x64 build and ensure Rosetta is available.)

---

## Verification checklist

| Flow           | Tool(s) used                          | How to verify                          |
|----------------|----------------------------------------|----------------------------------------|
| Web search     | browser_launch, search_web            | Chat shows titles/URLs/snippets         |
| News           | browser_launch, search_web, navigate, get_content | Chat shows full article text     |
| Weather        | browser_launch, search_web, navigate, get_content | Chat shows forecast text        |
| IEEE search    | browser_launch, ieee_search            | Chat shows paper list                  |
| IEEE get paper | ieee_get_paper                         | Chat shows abstract, DOI, etc.        |
| IEEE download  | ieee_download_pdf                      | Downloaded Files + `mcp_server/downloads/` |
| arXiv search   | arxiv_search                           | Chat shows papers + abstracts          |
| arXiv get paper| arxiv_get_paper                        | Chat shows full metadata               |
| arXiv download | arxiv_download_pdf                     | Downloaded Files + `mcp_server/downloads/` |
| Screenshot     | browser_launch, navigate, screenshot   | Downloaded Files has image             |
| Content (text) | browser_launch, navigate, get_content  | Chat shows full page text/markdown     |

Activity Log (right panel) shows each tool call and ✓/✗. Downloaded Files lists PDFs and screenshots; use **Refresh** after a download.
