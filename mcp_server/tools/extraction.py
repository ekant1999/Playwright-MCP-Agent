"""Content extraction tools for Playwright browser.

Provides robust, multi-strategy content extraction:
1. Cloudflare / bot-challenge detection and auto-wait-through
2. Content stabilization waiting (waits for JS hydration to complete)
3. Smart lazy-load scrolling (only when initial extraction is insufficient)
4. JavaScript-based extraction (Readability-inspired, runs in-browser)
5. BeautifulSoup-based extraction (server-side fallback)
6. Content quality validation with intelligent retry
7. Rich metadata extraction (author, date, description, etc.)
"""

from __future__ import annotations

import json
import csv
import logging
from io import StringIO

from mcp_server.browser_manager import BrowserManager
from mcp_server.schemas import (
    GetContentInput,
    ExtractTableInput,
    ScreenshotInput,
    ExecuteScriptInput,
)
from mcp_server.utils.errors import format_error
from mcp_server.utils.parser import html_to_text, html_to_markdown, extract_main_content
from mcp_server.utils.readability import (
    extract_with_js,
    wait_for_stable_content,
    detect_challenge,
    detect_blocked_page,
    wait_through_challenge,
    scroll_to_load,
    extract_metadata_only,
)
from mcp_server.utils.file_manager import file_manager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

_MIN_GOOD_CONTENT_LENGTH = 200   # chars — minimum for "usable" content
_MIN_ARTICLE_CONTENT_LENGTH = 800  # chars — minimum for a full article
_MIN_USABLE_CONTENT_LENGTH = 50  # chars — bare minimum


# ---------------------------------------------------------------------------
# Content quality helpers
# ---------------------------------------------------------------------------

def _content_quality(text: str) -> str:
    """Assess content quality: 'good', 'short', 'usable', or 'poor'."""
    length = len(text.strip())
    if length >= _MIN_ARTICLE_CONTENT_LENGTH:
        return "good"
    elif length >= _MIN_GOOD_CONTENT_LENGTH:
        return "short"
    elif length >= _MIN_USABLE_CONTENT_LENGTH:
        return "usable"
    return "poor"


# ---------------------------------------------------------------------------
# Article-page detection
# ---------------------------------------------------------------------------

async def _looks_like_article(page) -> bool:
    """Heuristic check: does the page look like a news/blog article?

    Used to decide whether short content warrants a scroll-retry.
    Non-article pages (forms, dashboards, search results) should not
    be penalised by extra wait time.

    Returns True if at least 2 of these signals are present:
    - <article> tag exists
    - Schema.org article metadata (articleBody, NewsArticle, BlogPosting)
    - Open Graph type is "article"
    - <meta name="author"> or published_time meta exists
    - URL path has date-like segments (/2025/01/, etc.) or slug-like segments
    """
    try:
        return await page.evaluate("""
            () => {
                let signals = 0;

                // Signal 1: <article> tag
                if (document.querySelector('article')) signals++;

                // Signal 2: Schema.org article markup
                if (document.querySelector('[itemprop="articleBody"]') ||
                    document.querySelector('[itemtype*="Article"]') ||
                    document.querySelector('[itemtype*="NewsArticle"]') ||
                    document.querySelector('[itemtype*="BlogPosting"]') ||
                    document.querySelector('script[type="application/ld+json"]')) {
                    try {
                        const ldScripts = document.querySelectorAll('script[type="application/ld+json"]');
                        for (const s of ldScripts) {
                            const data = JSON.parse(s.textContent || '{}');
                            const t = (data['@type'] || '').toLowerCase();
                            if (t.includes('article') || t.includes('newsarticle') ||
                                t.includes('blogposting') || t.includes('reportagenewsarticle')) {
                                signals++;
                                break;
                            }
                        }
                    } catch(e) {}
                }

                // Signal 3: og:type = article
                const ogType = document.querySelector('meta[property="og:type"]');
                if (ogType && (ogType.content || '').toLowerCase() === 'article') signals++;

                // Signal 4: Author or published_time meta
                if (document.querySelector('meta[name="author"]') ||
                    document.querySelector('meta[property="article:published_time"]') ||
                    document.querySelector('time[datetime]') ||
                    document.querySelector('[itemprop="author"]') ||
                    document.querySelector('[itemprop="datePublished"]')) {
                    signals++;
                }

                // Signal 5: URL pattern (date-like: /2025/01/ or slug: /some-slug-here)
                const path = window.location.pathname;
                if (/\\/\\d{4}\\/\\d{1,2}/.test(path)) signals++;
                else if (/\\/[a-z0-9-]{15,}/.test(path)) signals++; // long slug

                return signals >= 2;
            }
        """)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Main extraction: get_content
# ---------------------------------------------------------------------------

async def get_content(arguments: dict) -> str:
    """Extract page content with multi-strategy approach.

    Architecture: EXTRACT FIRST, then scroll/retry only if needed.

    This ensures fast extraction for simple pages (forms, dashboards,
    search results) while still capturing full content on lazy-loading
    article pages.

    Flow:
    1. Detect and wait through Cloudflare/bot challenges
    2. Wait for content to STABILIZE (stop growing — not just appear)
    3. Dismiss consent banners (fast, low timeout)
    4. Run dual extraction (JS + BeautifulSoup)
    5. IF content is short AND page looks like an article:
       a. Scroll to trigger lazy content
       b. Try "Read more" / "Continue reading" buttons
       c. Re-extract and compare
    6. If scroll_to_load was explicitly requested, always scroll
    7. Detect original source URL for news aggregators
    8. Build and return response
    """
    try:
        input_data = GetContentInput(**arguments)
        manager = await BrowserManager.get_instance()
        page = await manager.ensure_page()

        extraction_method = "unknown"
        metadata = {}
        challenge_info = {}

        # --- Step 0: Reject blank page ---
        # If the browser is on about:blank, there is nothing to extract.
        # Call navigate(url) first, then get_content().
        current_url = (page.url or "").strip()
        if not current_url or current_url in ("about:blank", "about:srcdoc"):
            return json.dumps({
                "status": "no_page",
                "url": current_url or "about:blank",
                "title": "",
                "content": "",
                "content_length": 0,
                "message": (
                    "No page is loaded. The browser is on a blank page. "
                    "You must call navigate(url) first with the article URL, "
                    "then call get_content() to extract the page content."
                ),
            }, indent=2)

        # --- Step 1: Cloudflare / bot-challenge detection ---
        is_challenge = await detect_challenge(page)
        if is_challenge:
            logger.info("Challenge page detected — waiting for resolution...")
            challenge_info = await wait_through_challenge(page, max_wait_ms=20000)
            if challenge_info.get("resolved"):
                logger.info("Challenge resolved after %dms",
                            challenge_info.get("waited_ms", 0))
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
            else:
                logger.warning("Challenge did NOT resolve within timeout")

        # --- Step 1b: Dismiss consent banners (fast) ---
        await _dismiss_consent_banners(page)

        # --- Step 1c: Detect blocked pages ---
        block_info = await detect_blocked_page(page)
        if block_info.get("is_blocked"):
            signals = block_info.get("signals", [])
            logger.warning("Blocked page detected: %s", signals)

            if "consent_wall" in signals:
                await _dismiss_consent_banners(page)
                block_info = await detect_blocked_page(page)

            if block_info.get("is_blocked"):
                signal_str = ", ".join(block_info.get("signals", ["unknown"]))
                return json.dumps({
                    "status": "blocked",
                    "url": page.url,
                    "title": await page.title(),
                    "block_type": signal_str,
                    "content": "",
                    "content_length": 0,
                    "message": (
                        f"Page is blocked by: {signal_str}. "
                        "The site requires manual intervention (disable ad-blocker, "
                        "accept cookies, login, or subscribe). The full article content "
                        "is not accessible to automated extraction."
                    ),
                }, indent=2)

        # --- Step 2: Wait for content stabilization ---
        if input_data.wait_for_content:
            wait_result = await wait_for_stable_content(
                page,
                timeout_ms=input_data.wait_timeout,
                stable_window_ms=1500,
            )
            logger.debug("Content stabilization result: %s", wait_result)

        # --- Step 3: If user explicitly requested scroll, do it now ---
        if input_data.scroll_to_load:
            await scroll_to_load(page)
            await wait_for_stable_content(page, timeout_ms=3000, stable_window_ms=800)

        # --- Step 4: Custom selector extraction (if provided) ---
        if input_data.selector:
            try:
                await page.wait_for_selector(input_data.selector, timeout=10000)
                custom_html = await page.evaluate(
                    "(sel) => { const el = document.querySelector(sel); "
                    "return el ? el.innerHTML : null; }",
                    input_data.selector,
                )
                if custom_html and len(custom_html.strip()) >= _MIN_USABLE_CONTENT_LENGTH:
                    content = _format_content(custom_html, input_data.format)
                    extraction_method = f"custom_selector({input_data.selector})"
                    if input_data.include_metadata:
                        metadata = await extract_metadata_only(page)
                    return await _build_response(
                        page, content, input_data.format, extraction_method,
                        metadata,
                        include_metadata=input_data.include_metadata,
                        challenge_info=challenge_info,
                    )
            except Exception as e:
                logger.debug("Custom selector '%s' failed: %s",
                             input_data.selector, e)

        # --- Step 5: First dual extraction ---
        best_html, extraction_method, metadata = await _dual_extract(page)
        content = _format_content(best_html, input_data.format)
        quality = _content_quality(content)

        # --- Step 5b: For article-like pages with borderline length (800–2500 chars),
        # scroll and re-extract once. Sites like MSN split article body with ads or
        # lazy-load below-fold; scrolling can reveal full content.
        if (
            not input_data.selector
            and quality == "good"
            and 800 <= len(content) <= 2500
            and await _looks_like_article(page)
        ):
            logger.info(
                "Article with %d chars — scrolling to load any below-fold content...",
                len(content),
            )
            await _expand_read_more(page)
            await scroll_to_load(page)
            await wait_for_stable_content(
                page, timeout_ms=3000, stable_window_ms=1000,
            )
            scroll_html, scroll_method, scroll_meta = await _dual_extract(page)
            scroll_content = _format_content(scroll_html, input_data.format)
            if len(scroll_content) > len(content) * 1.1:
                best_html = scroll_html
                extraction_method = scroll_method + " (retry-scroll-article)"
                metadata = scroll_meta
                content = scroll_content
                quality = _content_quality(content)
                logger.info("Scroll retry improved article: %d chars", len(content))

        # --- Step 6: Smart retry for any below-"good" content ---
        # ANY page with < 800 chars likely has missing content:
        #   - AJAX-loaded data not yet rendered (weather, dashboards)
        #   - Lazy-loaded article sections
        #   - JS-hydrated content (React/Next.js/Vue SPAs)
        #
        # Strategy:
        #   1. Wait for network to settle (catches AJAX responses)
        #   2. Wait for content stabilization (catches JS rendering)
        #   3. Re-extract — if better, use it
        #   4. If still poor, try scroll + "Read more" buttons
        if quality != "good" and not input_data.selector:
            logger.info(
                "Quality '%s' (%d chars) — waiting for network + re-extracting...",
                quality, len(content),
            )

            # Phase 1: Wait for network idle (AJAX responses)
            # This is the key fix for JS-rendered pages like weather sites.
            # Short timeout to avoid hanging on websocket/long-poll pages.
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass  # Timeout is fine — some pages never reach networkidle

            # Phase 2: Wait for content to stabilize after AJAX renders
            await wait_for_stable_content(
                page, timeout_ms=5000, stable_window_ms=1500,
            )

            # Phase 3: Re-extract
            retry_html, retry_method, retry_meta = await _dual_extract(page)
            retry_content = _format_content(retry_html, input_data.format)

            if len(retry_content) > len(content) * 1.1:
                best_html = retry_html
                extraction_method = retry_method + " (retry-network)"
                metadata = retry_meta
                content = retry_content
                quality = _content_quality(content)
                logger.info("Network-wait retry improved: %d chars", len(content))

            # Phase 4: If still insufficient, try scroll + expand
            if quality != "good":
                await _expand_read_more(page)
                await scroll_to_load(page)
                await wait_for_stable_content(
                    page, timeout_ms=3000, stable_window_ms=1000,
                )

                r2_html, r2_method, r2_meta = await _dual_extract(page)
                r2_content = _format_content(r2_html, input_data.format)

                if len(r2_content) > len(content) * 1.1:
                    best_html = r2_html
                    extraction_method = r2_method + " (retry-scroll)"
                    metadata = r2_meta
                    content = r2_content
                    quality = _content_quality(content)
                    logger.info("Scroll retry improved: %d chars", len(content))

        # Get metadata if not already obtained
        if input_data.include_metadata and not metadata:
            metadata = await extract_metadata_only(page)

        # --- Step 7: Detect original source for news aggregators ---
        original_source = None
        if quality != "good":
            original_source = await _detect_original_source(page)

        resp = await _build_response(
            page, content, input_data.format, extraction_method, metadata,
            quality=quality,
            include_metadata=input_data.include_metadata,
            challenge_info=challenge_info,
        )

        if original_source:
            try:
                resp_data = json.loads(resp)
                resp_data["original_source_url"] = original_source
                resp_data["hint"] = (
                    "This page appears to be a news aggregator showing a summary. "
                    f"The original article may be at: {original_source} — "
                    "navigate there for the full content."
                )
                resp = json.dumps(resp_data, indent=2)
            except Exception:
                pass

        return resp

    except Exception as e:
        return format_error("get_content", e)


# ---------------------------------------------------------------------------
# Consent banner dismissal (fast — 200ms timeout per selector)
# ---------------------------------------------------------------------------

async def _dismiss_consent_banners(page) -> None:
    """Try to dismiss common cookie consent and GDPR banners.

    Uses a short 200ms visibility timeout per selector to avoid
    wasting time on pages without banners. Total worst-case overhead
    is ~3 seconds instead of 15+.
    """
    consent_selectors = [
        # Generic consent buttons (most common first)
        "button:has-text('Accept all')",
        "button:has-text('Accept All')",
        "button:has-text('Accept cookies')",
        "button:has-text('I agree')",
        "button:has-text('Got it')",
        "button:has-text('OK')",
        # Attribute-based
        "button[id*='accept']",
        "button[class*='accept']",
        # CMP frameworks
        "[data-testid='accept-button']",
        "button.cmp-button_button--acceptAll",
        ".qc-cmp-button:first-child",
        # Google / Bing
        "button#L2AGLb",
        "button#bnp_btn_accept",
    ]
    for sel in consent_selectors:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=200):
                await btn.click(timeout=2000)
                await page.wait_for_timeout(300)
                return
        except Exception:
            continue


# ---------------------------------------------------------------------------
# "Read more" / "Continue reading" expansion (fast)
# ---------------------------------------------------------------------------

async def _expand_read_more(page) -> None:
    """Click 'Read more' / 'Continue reading' buttons to reveal full content.

    Only checks a focused set of selectors with short timeouts.
    """
    read_more_selectors = [
        # Text-based (generic — works on any site)
        "button:has-text('Read more')",
        "button:has-text('Continue reading')",
        "button:has-text('Show more')",
        "a:has-text('Read more')",
        "a:has-text('Continue reading')",
        "a:has-text('Read full article')",
        # Class-based (common patterns)
        "[class*='read-more']",
        "[class*='readMore']",
        "[class*='continue-reading']",
        "[class*='show-more']",
        "[class*='showMore']",
        # Data attributes
        "[data-testid='read-more']",
        "[data-testid='continue-reading']",
    ]
    for sel in read_more_selectors:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=200):
                await btn.click(timeout=2000)
                await page.wait_for_timeout(800)
                logger.debug("Clicked 'Read more': %s", sel)
                return
        except Exception:
            continue


# ---------------------------------------------------------------------------
# Original source detection (generic — no hardcoded domains)
# ---------------------------------------------------------------------------

async def _detect_original_source(page) -> str | None:
    """Detect the original article URL on news aggregator pages.

    Generic approach using structural signals only:
    1. Check if canonical URL or og:url points to a different domain
    2. Look for source attribution links near article headers
    3. Check for "View original" / "Read on [source]" link patterns
    """
    try:
        source_url = await page.evaluate("""
            () => {
                const host = window.location.hostname.toLowerCase();

                // Strategy 1: canonical/og:url pointing to a different domain
                const canonical = document.querySelector('link[rel="canonical"]');
                if (canonical && canonical.href) {
                    try {
                        const cUrl = new URL(canonical.href, window.location.origin);
                        if (cUrl.hostname !== host &&
                            cUrl.hostname !== 'www.' + host &&
                            host !== 'www.' + cUrl.hostname) {
                            return canonical.href;
                        }
                    } catch(e) {}
                }
                const ogUrl = document.querySelector('meta[property="og:url"]');
                if (ogUrl && ogUrl.content) {
                    try {
                        const oUrl = new URL(ogUrl.content);
                        if (oUrl.hostname !== host &&
                            oUrl.hostname !== 'www.' + host &&
                            host !== 'www.' + oUrl.hostname) {
                            return ogUrl.content;
                        }
                    } catch(e) {}
                }

                // Strategy 2: Source/provider attribution links
                const sourceSelectors = [
                    'a[data-t="source"]',
                    'a[class*="source"]',
                    'a[class*="provider"]',
                    'a[class*="origin"]',
                    'a[rel="author"][href^="http"]',
                ];
                for (const sel of sourceSelectors) {
                    const el = document.querySelector(sel);
                    if (el && el.href) {
                        try {
                            const sUrl = new URL(el.href);
                            if (sUrl.hostname !== host &&
                                !sUrl.hostname.includes('microsoft.com') &&
                                !sUrl.hostname.includes('google.com') &&
                                !sUrl.hostname.includes('apple.com')) {
                                return el.href;
                            }
                        } catch(e) {}
                    }
                }

                // Strategy 3: "View original" / "Read on" links
                const allLinks = document.querySelectorAll('a');
                for (const link of allLinks) {
                    const text = (link.textContent || '').trim().toLowerCase();
                    if ((text.includes('view original') ||
                         text.includes('read on') ||
                         text.includes('original article') ||
                         text.includes('full article') ||
                         text.includes('source:')) && link.href) {
                        try {
                            const lUrl = new URL(link.href);
                            if (lUrl.hostname !== host) {
                                return link.href;
                            }
                        } catch(e) {}
                    }
                }

                return null;
            }
        """)
        return source_url
    except Exception as e:
        logger.debug("Original source detection failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Dual extraction logic
# ---------------------------------------------------------------------------

async def _dual_extract(page) -> tuple[str, str, dict]:
    """Run both JS and BeautifulSoup extraction, pick the best.

    Returns: (best_html, extraction_method, metadata)
    """
    # JS-based extraction
    js_result = await extract_with_js(page)
    js_html = js_result.get("html") if js_result.get("success") else None
    js_metadata = js_result.get("metadata", {}) if js_result.get("success") else {}

    # BeautifulSoup-based extraction
    page_html = await page.content()
    bs_html = extract_main_content(page_html)
    bs_text = html_to_text(bs_html)

    # Use text_length (from textContent) for JS — this includes hidden text
    # (e.g. "Read More" collapsed content) for accurate comparison.
    # Falls back to len(text) if text_length is not available.
    js_len = js_result.get("text_length", 0) if js_result.get("success") else 0
    if js_len == 0 and js_result.get("success"):
        js_text = js_result.get("text", "")
        js_len = len(js_text.strip())
    bs_len = len(bs_text.strip())

    # Pick best: prefer whichever has significantly more content
    # Use a 30% threshold to avoid flip-flopping on small differences
    if js_len > bs_len * 1.3 and js_len >= _MIN_GOOD_CONTENT_LENGTH:
        return (
            js_html,
            f"js_readability ({js_result.get('method', 'unknown')})",
            js_metadata,
        )

    if bs_len > js_len * 1.3 and bs_len >= _MIN_GOOD_CONTENT_LENGTH:
        return bs_html, "beautifulsoup_scoring", {}

    # Similar lengths — prefer JS (captures dynamic content better)
    if js_len >= _MIN_GOOD_CONTENT_LENGTH:
        return (
            js_html,
            f"js_readability ({js_result.get('method', 'unknown')})",
            js_metadata,
        )

    if bs_len >= _MIN_GOOD_CONTENT_LENGTH:
        return bs_html, "beautifulsoup_scoring", {}

    # Both below "good" threshold — return whichever is larger
    if js_len >= bs_len and js_html:
        return (
            js_html,
            f"js_readability ({js_result.get('method', 'fallback')})",
            js_metadata,
        )

    return bs_html, "beautifulsoup_fallback", {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_content(html: str, fmt: str) -> str:
    """Convert HTML to the requested format."""
    if fmt == "html":
        return html
    elif fmt == "text":
        return html_to_text(html)
    else:  # markdown
        return html_to_markdown(html)


async def _build_response(
    page,
    content: str,
    fmt: str,
    extraction_method: str,
    metadata: dict,
    quality: str = "good",
    include_metadata: bool = False,
    challenge_info: dict | None = None,
) -> str:
    """Build the JSON response for get_content."""
    title = await page.title()
    url = page.url

    result = {
        "status": "success",
        "url": url,
        "title": title,
        "format": fmt,
        "extraction_method": extraction_method,
        "content_quality": quality,
        "content": content,
        "content_length": len(content),
    }

    if quality in ("poor", "short"):
        result["warning"] = (
            "Extracted content is shorter than expected. The page may require "
            "JavaScript rendering, login, or has anti-scraping measures. "
            "Try using execute_script for custom extraction, or increase wait_timeout."
        )

    if challenge_info:
        result["challenge_info"] = challenge_info

    if include_metadata and metadata:
        result["metadata"] = metadata

    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# Table extraction
# ---------------------------------------------------------------------------

async def extract_table(arguments: dict) -> str:
    """Extract HTML table data with improved robustness."""
    try:
        input_data = ExtractTableInput(**arguments)
        manager = await BrowserManager.get_instance()
        page = await manager.ensure_page()

        # Wait for table to appear
        try:
            await page.wait_for_selector(input_data.selector, timeout=10000)
        except Exception:
            return format_error(
                "extract_table",
                Exception("Table not found within timeout"),
                f"No table found with selector: {input_data.selector}. "
                "The page might still be loading or the selector may be wrong.",
            )

        # Extract table data using JavaScript
        table_data = await page.evaluate("""
            (selector) => {
                const table = document.querySelector(selector);
                if (!table) return null;

                const rows = [];
                const allRows = table.querySelectorAll('tr');

                for (const row of allRows) {
                    const cells = [];
                    for (const cell of row.querySelectorAll('th, td')) {
                        cells.push({
                            text: cell.textContent.trim(),
                            is_header: cell.tagName.toLowerCase() === 'th',
                            colspan: cell.colSpan || 1,
                            rowspan: cell.rowSpan || 1,
                        });
                    }
                    if (cells.length > 0) {
                        rows.push(cells);
                    }
                }

                return {
                    rows: rows,
                    caption: table.querySelector('caption') ?
                             table.querySelector('caption').textContent.trim() : null,
                };
            }
        """, input_data.selector)

        if not table_data or not table_data.get("rows"):
            return format_error(
                "extract_table",
                Exception("Table is empty"),
                f"Table found with selector '{input_data.selector}' but contains no rows.",
            )

        raw_rows = table_data["rows"]

        # Flatten to simple text arrays
        text_rows = [[cell["text"] for cell in row] for row in raw_rows]

        # Format output
        if input_data.format == "csv":
            output = StringIO()
            writer = csv.writer(output)
            writer.writerows(text_rows)
            formatted_data = output.getvalue()
        else:  # json
            has_headers = raw_rows and all(c["is_header"] for c in raw_rows[0])
            if has_headers and len(text_rows) > 1:
                headers = text_rows[0]
                data_rows = text_rows[1:]
                formatted_data = [dict(zip(headers, row)) for row in data_rows]
            else:
                formatted_data = text_rows

        result = {
            "status": "success",
            "format": input_data.format,
            "rows": len(text_rows),
            "data": formatted_data,
        }

        if table_data.get("caption"):
            result["caption"] = table_data["caption"]

        return json.dumps(result, indent=2)

    except Exception as e:
        return format_error("extract_table", e)


# ---------------------------------------------------------------------------
# Screenshot
# ---------------------------------------------------------------------------

async def screenshot(arguments: dict) -> str:
    """Capture a screenshot of the current page."""
    try:
        input_data = ScreenshotInput(**arguments)
        manager = await BrowserManager.get_instance()
        page = await manager.ensure_page()

        screenshot_bytes = await page.screenshot(full_page=input_data.full_page)
        file_info = file_manager.save_file(screenshot_bytes, input_data.path)

        result = {
            "status": "success",
            "message": "Screenshot captured successfully",
            "full_page": input_data.full_page,
            **file_info,
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        return format_error("screenshot", e)


# ---------------------------------------------------------------------------
# Execute JavaScript
# ---------------------------------------------------------------------------

async def execute_script(arguments: dict) -> str:
    """Execute JavaScript on the current page."""
    try:
        input_data = ExecuteScriptInput(**arguments)
        manager = await BrowserManager.get_instance()
        page = await manager.ensure_page()

        script_result = await page.evaluate(input_data.script)

        result = {
            "status": "success",
            "result": script_result,
            "result_type": type(script_result).__name__,
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        return format_error(
            "execute_script",
            e,
            "Make sure the JavaScript code is valid and safe to execute.",
        )
