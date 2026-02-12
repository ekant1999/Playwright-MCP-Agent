"""Web search and page interaction tools.

Strategy for reliable search:
1. Primary: DuckDuckGo HTML-lite via httpx (no browser needed, very stable)
2. Fallback: Browser-based search with updated selectors + multiple
   selector strategies per engine + automatic engine fallback
3. CAPTCHA / block detection with clear error messages
4. Retry logic with configurable attempts
"""

import json
import logging
from urllib.parse import quote_plus
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from mcp_server.browser_manager import BrowserManager
from mcp_server.schemas import (
    SearchWebInput,
    WaitForElementInput,
    ScrollPageInput,
)
from mcp_server.utils.errors import format_error

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HTTPX_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}

# Engine-specific selector configurations.
# Each engine lists *multiple* selector strategies (tried in order) so that
# if the site's HTML changes we still have a fallback.
_ENGINE_CONFIGS = {
    "google": {
        "url_template": "https://www.google.com/search?q={query}&num={num}&hl=en",
        "strategies": [
            {  # Strategy 1 – standard organic results
                "result": "div.g",
                "title": "h3",
                "link": "a",
                "snippet": ".VwiC3b, [data-sncf], div[style*='-webkit-line-clamp']",
            },
            {  # Strategy 2 – alternate container
                "result": "div[data-hveid] div.g, div.MjjYud div.g",
                "title": "h3",
                "link": "a[href]",
                "snippet": "div[data-sncf], span.st, .VwiC3b",
            },
            {  # Strategy 3 – broader match
                "result": "[data-hveid]",
                "title": "h3",
                "link": "a[href^='http']",
                "snippet": "span, div.VwiC3b",
            },
        ],
    },
    "bing": {
        "url_template": "https://www.bing.com/search?q={query}&count={num}",
        "strategies": [
            {
                "result": "li.b_algo",
                "title": "h2",
                "link": "h2 a",
                "snippet": ".b_caption p, .b_lineclamp2, p",
            },
            {
                "result": "ol#b_results > li",
                "title": "h2",
                "link": "h2 a[href]",
                "snippet": "p",
            },
        ],
    },
    "duckduckgo": {
        "url_template": "https://duckduckgo.com/?q={query}",
        "strategies": [
            {
                "result": "article[data-testid='result']",
                "title": "h2",
                "link": "a[data-testid='result-title-a']",
                "snippet": "[data-result='snippet'], span.kY2IgmnCmOGjharHErah",
            },
            {  # Older layout
                "result": "div.result",
                "title": "h2 a.result__a",
                "link": "a.result__a",
                "snippet": "a.result__snippet",
            },
        ],
    },
}


# ---------------------------------------------------------------------------
# httpx-based DuckDuckGo HTML-lite search (primary, most reliable)
# ---------------------------------------------------------------------------

async def _search_duckduckgo_lite(query: str, max_results: int = 10) -> list[dict]:
    """Search DuckDuckGo HTML-lite version via httpx (no browser required).

    This is the *most reliable* search method because:
    - html.duckduckgo.com serves a minimal, stable HTML page
    - No JavaScript rendering needed
    - Rarely blocked or rate-limited for reasonable usage
    """
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    results: list[dict] = []

    try:
        async with httpx.AsyncClient(
            headers=_HTTPX_HEADERS,
            follow_redirects=True,
            timeout=20.0,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")

        # Each result is inside <div class="result results_links results_links_deep web-result">
        for item in soup.select("div.result.results_links"):
            title_el = item.select_one("a.result__a")
            snippet_el = item.select_one("a.result__snippet")
            if not title_el:
                continue

            href = title_el.get("href", "")
            title = title_el.get_text(strip=True)
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""

            # DDG lite wraps real URLs in a redirect; try to extract the actual URL
            if "/l/?uddg=" in href:
                from urllib.parse import unquote, urlparse, parse_qs
                parsed = urlparse(href)
                qs = parse_qs(parsed.query)
                href = unquote(qs.get("uddg", [href])[0])

            if title and href.startswith("http"):
                results.append({
                    "title": title,
                    "url": href,
                    "snippet": snippet,
                })
            if len(results) >= max_results:
                break

    except Exception as e:
        logger.warning("DuckDuckGo lite search failed: %s", e)

    return results


# ---------------------------------------------------------------------------
# Browser-based search (fallback)
# ---------------------------------------------------------------------------

async def _dismiss_cookie_consent(page) -> None:
    """Try to dismiss common cookie / consent banners."""
    consent_selectors = [
        # Google consent
        "button#L2AGLb",
        "button[aria-label='Accept all']",
        "button:has-text('Accept all')",
        "button:has-text('I agree')",
        # Bing consent
        "button#bnp_btn_accept",
        # Generic
        "button:has-text('Accept')",
        "button:has-text('Got it')",
    ]
    for sel in consent_selectors:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=800):
                await btn.click(timeout=2000)
                await page.wait_for_timeout(500)
                return
        except Exception:
            continue


def _is_blocked(page_text: str) -> bool:
    """Detect CAPTCHA or bot-blocking pages."""
    block_signals = [
        "unusual traffic",
        "are not a robot",
        "captcha",
        "blocked",
        "verify you are human",
        "automated queries",
        "sorry, we can't serve",
        "please verify",
    ]
    lower = page_text.lower()
    return any(signal in lower for signal in block_signals)


async def _extract_with_strategies(page, strategies: list[dict], max_results: int) -> list[dict]:
    """Try multiple CSS-selector strategies on the current page.

    Returns results from the first strategy that yields > 0 results.
    """
    for strategy in strategies:
        try:
            # Wait briefly for the result container
            try:
                await page.wait_for_selector(strategy["result"], timeout=6000)
            except Exception:
                continue

            results = await page.evaluate("""
                ({resultSel, titleSel, linkSel, snippetSel, maxResults}) => {
                    const out = [];
                    const items = document.querySelectorAll(resultSel);
                    for (let i = 0; i < Math.min(items.length, maxResults); i++) {
                        const el = items[i];
                        const titleEl = el.querySelector(titleSel);
                        const linkEl = el.querySelector(linkSel);
                        // Try multiple snippet selectors (comma-separated)
                        let snippet = '';
                        for (const sel of snippetSel.split(',')) {
                            const s = el.querySelector(sel.trim());
                            if (s && s.textContent.trim()) {
                                snippet = s.textContent.trim();
                                break;
                            }
                        }
                        if (titleEl && linkEl && linkEl.href && linkEl.href.startsWith('http')) {
                            out.push({
                                title: titleEl.textContent.trim(),
                                url: linkEl.href,
                                snippet: snippet,
                            });
                        }
                    }
                    return out;
                }
            """, {
                "resultSel": strategy["result"],
                "titleSel": strategy["title"],
                "linkSel": strategy["link"],
                "snippetSel": strategy["snippet"],
                "maxResults": max_results,
            })

            if results:
                return results

        except Exception as e:
            logger.debug("Strategy %s failed: %s", strategy["result"], e)
            continue

    return []


async def _browser_search_engine(engine: str, query: str, max_results: int) -> list[dict]:
    """Run a browser-based search for a single engine. Returns [] on failure."""
    config = _ENGINE_CONFIGS.get(engine)
    if not config:
        return []

    try:
        manager = await BrowserManager.get_instance()
        page = await manager.ensure_page()
    except RuntimeError:
        return []

    query_encoded = quote_plus(query)
    search_url = config["url_template"].format(query=query_encoded, num=max_results)

    try:
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        # Give dynamic content a moment to render
        await page.wait_for_timeout(2000)

        # Handle cookie / consent banners
        await _dismiss_cookie_consent(page)

        # Detect blocks / CAPTCHAs
        body_text = await page.evaluate("document.body.innerText")
        if _is_blocked(body_text):
            logger.warning("Engine '%s' appears to have blocked the request.", engine)
            return []

        results = await _extract_with_strategies(page, config["strategies"], max_results)
        return results

    except Exception as e:
        logger.warning("Browser search on '%s' failed: %s", engine, e)
        return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Engine fallback order used when the requested engine returns nothing.
_FALLBACK_ORDER = {
    "google": ["google", "bing", "duckduckgo"],
    "bing":   ["bing", "google", "duckduckgo"],
    "duckduckgo": ["duckduckgo", "bing", "google"],
}


async def search_web(arguments: dict) -> str:
    """Search the web and return results.

    Execution order:
    1. Try DuckDuckGo HTML-lite via httpx (fastest, no browser needed).
    2. If that fails or returns nothing, try browser-based search with the
       requested engine, then fall back through other engines.
    """
    try:
        input_data = SearchWebInput(**arguments)
        query = input_data.query
        max_results = input_data.max_results
        engine = input_data.engine
        results: list[dict] = []
        source = ""

        # --- Step 1: httpx-based DuckDuckGo lite (primary) ---
        results = await _search_duckduckgo_lite(query, max_results)
        if results:
            source = "duckduckgo-lite (httpx)"
        else:
            # --- Step 2: Browser-based search with fallback ---
            fallback_engines = _FALLBACK_ORDER.get(engine, [engine])
            for eng in fallback_engines:
                results = await _browser_search_engine(eng, query, max_results)
                if results:
                    source = f"{eng} (browser)"
                    break

        # --- Build response ---
        if not results:
            return json.dumps({
                "status": "no_results",
                "query": query,
                "engine": engine,
                "results_count": 0,
                "results": [],
                "message": (
                    "No results found. All search strategies were attempted "
                    "(DuckDuckGo lite + browser-based fallbacks). The search "
                    "engines may be blocking automated requests, or the query "
                    "returned no matches."
                ),
            }, indent=2)

        return json.dumps({
            "status": "success",
            "query": query,
            "engine": engine,
            "source": source,
            "results_count": len(results),
            "results": results,
        }, indent=2)

    except Exception as e:
        return format_error(
            "search_web",
            e,
            "Search failed across all strategies. Please try a different query or engine.",
        )


async def wait_for_element(arguments: dict) -> str:
    """Wait for an element to appear on the page."""
    try:
        input_data = WaitForElementInput(**arguments)
        manager = await BrowserManager.get_instance()
        page = await manager.ensure_page()
        
        # Wait for selector
        await page.wait_for_selector(input_data.selector, timeout=input_data.timeout)
        
        # Check if element is visible
        is_visible = await page.is_visible(input_data.selector)
        
        result = {
            "status": "success",
            "message": f"Element found: {input_data.selector}",
            "selector": input_data.selector,
            "visible": is_visible
        }
        
        return json.dumps(result, indent=2)
    
    except Exception as e:
        return format_error(
            "wait_for_element",
            e,
            f"Element '{arguments.get('selector', '?')}' did not appear within {arguments.get('timeout', 30000)}ms. Try increasing the timeout."
        )


async def scroll_page(arguments: dict) -> str:
    """Scroll the page in specified direction."""
    try:
        input_data = ScrollPageInput(**arguments)
        manager = await BrowserManager.get_instance()
        page = await manager.ensure_page()
        
        # Calculate scroll amount
        scroll_amount = input_data.amount if input_data.direction == "down" else -input_data.amount
        
        # Get current scroll position
        before_position = await page.evaluate("window.pageYOffset")
        
        # Scroll
        await page.evaluate(f"window.scrollBy(0, {scroll_amount})")
        
        # Wait a moment for content to load
        await page.wait_for_timeout(500)
        
        # Get new scroll position
        after_position = await page.evaluate("window.pageYOffset")
        
        # Check if at bottom
        is_at_bottom = await page.evaluate("""
            () => {
                return (window.innerHeight + window.pageYOffset) >= document.body.scrollHeight - 10;
            }
        """)
        
        result = {
            "status": "success",
            "direction": input_data.direction,
            "scroll_amount": input_data.amount,
            "before_position": before_position,
            "after_position": after_position,
            "scrolled": abs(after_position - before_position),
            "at_bottom": is_at_bottom
        }
        
        return json.dumps(result, indent=2)
    
    except Exception as e:
        return format_error("scroll_page", e)
