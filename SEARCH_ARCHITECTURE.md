# Web Search Architecture

## Overview

The `search_web` tool uses a **multi-layer, fault-tolerant architecture** to deliver reliable search results. Instead of relying on a single fragile approach, it chains multiple strategies together — each one acting as a fallback for the previous.

---

## The Problem (Before)

The original search had a single path:

```
User query → Open Playwright browser → Navigate to Google → Scrape with CSS selectors → Return results
```

This broke frequently because:

| Issue | Impact |
|---|---|
| Incomplete user-agent string | Google/Bing detected the browser as a bot |
| `navigator.webdriver = true` | Playwright's default flag instantly identified automation |
| Single CSS selector set per engine | Any HTML change on Google/Bing/DDG returned zero results |
| No fallback between engines | If Google blocked us, the whole search failed |
| `networkidle` wait strategy | Hung indefinitely on search engines that stream resources |
| No cookie consent handling | Consent banners covered the actual search results |
| No CAPTCHA detection | Silently returned empty results when blocked |

---

## The Solution (After)

```
User query
    │
    ▼
┌─────────────────────────────────────────┐
│  TIER 1: DuckDuckGo HTML-Lite (httpx)   │  ← No browser needed, ~1.2s
│  GET html.duckduckgo.com/html/?q=...    │
│  Parse with BeautifulSoup               │
└──────────────┬──────────────────────────┘
               │
          Results? ── YES ──► Return results
               │
               NO
               │
               ▼
┌─────────────────────────────────────────┐
│  TIER 2: Browser-Based Search           │  ← Requires browser_launch
│                                         │
│  For each engine in fallback order:     │
│    1. Navigate to search URL            │
│    2. Dismiss cookie consent banners    │
│    3. Check for CAPTCHA / blocks        │
│    4. Try selector strategy 1           │
│    5. Try selector strategy 2           │
│    6. Try selector strategy 3           │
│    7. No results? → Next engine         │
└──────────────┬──────────────────────────┘
               │
          Results? ── YES ──► Return results
               │
               NO
               │
               ▼
        Return "no_results" with
        diagnostic message
```

---

## Tools & Libraries Used

### httpx (Async HTTP Client)

**What it is:** A modern, async-capable HTTP client for Python.

**Why we used it:** To make direct HTTP requests to DuckDuckGo's HTML-lite endpoint (`html.duckduckgo.com/html/`) without needing a browser at all. This is dramatically faster (~1.2s vs 5-10s) and avoids all browser fingerprinting issues.

**Where it's used:** `_search_duckduckgo_lite()` in `mcp_server/tools/search.py`

```python
async with httpx.AsyncClient(headers=_HTTPX_HEADERS, follow_redirects=True, timeout=20.0) as client:
    resp = await client.get(url)
```

### BeautifulSoup + lxml (HTML Parsing)

**What it is:** BeautifulSoup is an HTML/XML parser. lxml is its fast C-based parsing backend.

**Why we used it:** To extract search results (titles, URLs, snippets) from the raw HTML returned by DuckDuckGo lite. Unlike browser-based scraping, this works on static HTML — no JavaScript execution needed.

**Where it's used:** `_search_duckduckgo_lite()` in `mcp_server/tools/search.py`

```python
soup = BeautifulSoup(resp.text, "lxml")
for item in soup.select("div.result.results_links"):
    title_el = item.select_one("a.result__a")
    snippet_el = item.select_one("a.result__snippet")
```

### Playwright (Browser Automation)

**What it is:** A browser automation framework that controls Chromium, Firefox, or WebKit.

**Why we used it:** As the Tier 2 fallback — when httpx-based search fails, we fall back to actually opening a browser and navigating to search engines. This handles cases where JavaScript rendering is required.

**Where it's used:** `_browser_search_engine()` in `mcp_server/tools/search.py` and the entire `browser_manager.py`

```python
await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
results = await _extract_with_strategies(page, config["strategies"], max_results)
```

---

## Key Design Decisions

### 1. Why DuckDuckGo HTML-Lite as Primary?

DuckDuckGo offers a special endpoint at `html.duckduckgo.com/html/` that serves a **server-rendered, JavaScript-free HTML page**. This was chosen because:

- **No bot detection** — DDG doesn't use CAPTCHAs or aggressive fingerprinting
- **Stable HTML structure** — The lite page layout has remained consistent for years
- **No browser required** — A simple HTTP GET + HTML parse is all that's needed
- **Fast** — ~1.2 seconds vs 5-10 seconds for browser-based search
- **Reliable** — Works even if Playwright or the browser is not installed

### 2. Why Multiple Selector Strategies?

Search engines (especially Google) frequently change their HTML class names and structure. Instead of one selector set that breaks when the site updates, each engine has 2-3 strategies:

```
Google Strategy 1: div.g → h3 → a → .VwiC3b         (standard layout)
Google Strategy 2: div[data-hveid] div.g → h3 → ...  (alternate container)
Google Strategy 3: [data-hveid] → h3 → a[href^=http]  (broadest match)
```

The system tries them in order and uses the first one that returns results.

### 3. Why Automatic Engine Fallback?

If Google shows a CAPTCHA, the old system just failed. Now it automatically rotates:

```python
_FALLBACK_ORDER = {
    "google":     ["google", "bing", "duckduckgo"],
    "bing":       ["bing", "google", "duckduckgo"],
    "duckduckgo": ["duckduckgo", "bing", "google"],
}
```

The user's preferred engine is tried first, but if blocked, the next engine in line is attempted automatically.

### 4. Why Stealth JavaScript Injection?

Playwright sets `navigator.webdriver = true` by default, which is the #1 signal websites use to detect automation. Our stealth script (injected via `context.add_init_script()`) patches this along with other fingerprint leaks:

```javascript
Object.defineProperty(navigator, 'webdriver', { get: () => false });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
window.chrome = { runtime: {} };
```

### 5. Why `domcontentloaded` Instead of `networkidle`?

The old code used `wait_until="networkidle"` which waits until no network requests fire for 500ms. Search engines continuously load analytics, ads, and tracking pixels, so `networkidle` would often hang until the 30s timeout. `domcontentloaded` fires as soon as the HTML is parsed, and we follow it with a 2-second delay for dynamic content — much more predictable.

---

## Files Modified

| File | What Changed |
|---|---|
| `mcp_server/browser_manager.py` | Full user-agent, stealth JS injection, anti-automation Chrome flags, locale/timezone |
| `mcp_server/tools/search.py` | Complete rewrite — httpx primary path, multi-strategy selectors, engine fallback, CAPTCHA detection, cookie consent dismissal |
| `mcp_server/server.py` | Updated `search_web` docstring to reflect new architecture |

---

## Backwards Compatibility

All changes are fully backwards-compatible:

- The `search_web` tool accepts the same parameters: `query`, `engine`, `max_results`
- The response JSON format is the same: `status`, `query`, `engine`, `results_count`, `results`
- One new field added: `source` (e.g., `"duckduckgo-lite (httpx)"` or `"google (browser)"`) to indicate which strategy produced the results
- No new dependencies — `httpx`, `beautifulsoup4`, and `lxml` were already in `requirements.txt`
