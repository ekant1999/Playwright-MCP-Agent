<img width="1705" height="627" alt="image" src="https://github.com/user-attachments/assets/76d36bd1-9bce-4893-a78f-62e672491f92" /># Playwright MCP Agent

Scraping and data extraction using **Playwright** (browser automation). Two ways to run: **SJSU Crawler** (CLI) and **MCP Server** (Playwright tools for extraction).

---

## Scraping Techniques

### SJSU Crawler (LibGuides + Primo)

- **Crawl**: Stack-based DFS over LibGuides. For each URL: `page.goto(url)` → extract in-browser → follow in-scope links. Content is taken from the main column only (`#s-lg-content` or `body`): title, meta description, full text, headings, `.s-lib-box` sections, paragraphs, tables, links, images. Output: one `PageRecord` per page.
- **Guides**: Fetches the Research Guides list from the library site; optionally `--full-content` to crawl each guide (same extraction as above) and download linked resources.
- **Search**: Browser-based OneSearch (Primo). Playwright opens Primo (or library homepage), finds the search input (including in iframes), submits the query, then extracts the result list (titles, links, metadata) from the DOM. Optional PDF download.

### MCP Server (generic extraction)

Playwright is used to load the page, then:

1. **Challenge handling**: Detect Cloudflare/bot challenges and wait through them.
2. **Stable content**: Wait for JS hydration before extracting.
3. **Lazy load**: Scroll when initial content is too short (e.g. article pages).
4. **Extraction**: In-browser JS (Readability-style) or server-side BeautifulSoup; main content + metadata (author, date, description).
5. **Tables**: `extract_table` parses HTML tables to JSON/CSV.

Tools: `get_content` (text/markdown/HTML), `extract_table`, `screenshot`, `execute_script`. Used by the agent (bridge + UI) for arbitrary URLs.

---

## Playwright for Data Extraction

| Where | How Playwright is used |
|-------|------------------------|
| **SJSU crawl** | `crawler.py` launches Chromium; `extractor.py` runs in browser context: restricts to `#s-lg-content`, then evaluates selectors for title, sections, tables, links, images. Yields structured `PageRecord`s. |
| **SJSU search** | `search_flow.py` navigates to Primo, locates search input (page + iframes), fills and submits; parses result list from the loaded DOM. |
| **MCP extraction** | `mcp_server/tools/extraction.py`: navigate via `browser_manager`, then `get_content` / `extract_table` use in-page JS and/or server-side parsing. |

All runs are headless Chromium unless configured otherwise (`config.yaml` for SJSU, env for MCP).

---

## How to Run

**From project root**, with Python env that has dependencies and Playwright installed (`pip install -r requirements.txt`, `playwright install chromium`).

### SJSU Crawler (CLI)

```bash
# Full-site DFS crawl → JSON and/or Postgres (crawl_pages)
python3 -m sjsu_crawler crawl
python3 -m sjsu_crawler --config sjsu_crawler/config.yaml crawl

# Research Guides list → output/guides_<query>.json and/or research_guides
python3 -m sjsu_crawler guides
python3 -m sjsu_crawler guides --query all --full-content --no-db

# OneSearch (Primo) → output/search_<query>.json and/or library_search_results
python3 -m sjsu_crawler search "your query"
python3 -m sjsu_crawler search "machine learning" --scope "San Jose State Collections" --download-dir search_pdfs --no-db
```

Global option `--config` must come **before** the subcommand.

### MCP Server (agent + Playwright extraction)

To use Playwright extraction tools via the agent (browser launch, navigate, get_content, extract_table, etc.):

1. **Ollama**: `ollama serve` and `ollama pull qwen2.5`
2. **Bridge**: `cd bridge_server && npm install && npm start`
3. **UI**: `cd ui && npm install && npm run dev` → open http://localhost:5173

The agent then calls Playwright tools (including extraction) based on natural-language requests.

---

## What to Expect

### SJSU Crawler

| Command | Output (when enabled) | Postgres table (when enabled) |
|--------|------------------------|--------------------------------|
| `crawl` | JSON array at `config.output_json` | `crawl_pages` (upsert by scope_prefix + url) |
| `guides` | `output/guides_<query>.json` | `research_guides` |
| `search` | `output/search_<query>.json` | `library_search_results` |

- Re-runs **upsert** (no duplicate rows); timestamps (`crawled_at` / `fetched_at`) show last run.
- PDFs from search: under `output/<download-dir>/` when `--download-dir` is set.
- Config: `sjsu_crawler/config.yaml` (start_url, scope_prefix, max_depth, max_pages, postgres, output_json, etc.).

### MCP extraction

- Downloaded files (e.g. PDFs, screenshots): `mcp_server/downloads/`.
- Extracted content is returned in the agent response (no file path unless the tool writes to downloads).

---

## Requirements

- Python 3.11+
- Playwright + Chromium
- For SJSU Postgres output: `postgres.enabled: true` and valid `postgres.url` in config; tables created on first run.

- <img width="911" height="207" alt="image" src="https://github.com/user-attachments/assets/3c4eb59a-c3f2-4b99-ad07-dd7f0f7a099e" />
<img width="929" height="207" alt="image" src="https://github.com/user-attachments/assets/f98da779-78a8-4ed5-981f-94610458f425" />
<img width="1718" height="509" alt="image" src="https://github.com/user-attachments/assets/d6a51d87-d6b1-4e43-8a8a-a373429f6f6c" />
<img width="1705" height="627" alt="image" src="https://github.com/user-attachments/assets/7591bf23-30d3-4f8d-bc47-0732d953e6cd" />



