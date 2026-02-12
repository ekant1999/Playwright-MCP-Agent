"""Content extraction tools for Playwright browser.

Provides robust, multi-strategy content extraction:
1. Smart waiting for dynamic content to fully render
2. Optional lazy-load scrolling to trigger deferred content
3. JavaScript-based extraction (Readability-inspired, runs in-browser)
4. BeautifulSoup-based extraction (server-side fallback)
5. Content quality validation with automatic fallback
6. Rich metadata extraction (author, date, description, etc.)
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
    wait_for_content,
    scroll_to_load,
    extract_metadata_only,
)
from mcp_server.utils.file_manager import file_manager

logger = logging.getLogger(__name__)

# Minimum thresholds for content quality
_MIN_GOOD_CONTENT_LENGTH = 100   # chars to consider extraction "good"
_MIN_USABLE_CONTENT_LENGTH = 30  # chars to consider extraction "usable"


# ---------------------------------------------------------------------------
# Content quality helpers
# ---------------------------------------------------------------------------

def _content_quality(text: str) -> str:
    """Assess content quality: 'good', 'usable', or 'poor'."""
    length = len(text.strip())
    if length >= _MIN_GOOD_CONTENT_LENGTH:
        return "good"
    elif length >= _MIN_USABLE_CONTENT_LENGTH:
        return "usable"
    return "poor"


def _pick_best_content(js_text: str | None, bs_text: str | None) -> tuple[str, str]:
    """Pick the best content from JS-based and BS-based extraction.
    
    Returns (best_text, method) where method is 'js' or 'beautifulsoup'.
    Prefers the longer, higher-quality result.
    """
    js_len = len((js_text or "").strip())
    bs_len = len((bs_text or "").strip())
    
    # If one is clearly better (>50% more content), prefer it
    if js_len > bs_len * 1.5 and js_len >= _MIN_GOOD_CONTENT_LENGTH:
        return js_text, "js"
    if bs_len > js_len * 1.5 and bs_len >= _MIN_GOOD_CONTENT_LENGTH:
        return bs_text, "beautifulsoup"
    
    # If both are good, prefer JS (captures dynamic content)
    if js_len >= _MIN_GOOD_CONTENT_LENGTH:
        return js_text, "js"
    if bs_len >= _MIN_GOOD_CONTENT_LENGTH:
        return bs_text, "beautifulsoup"
    
    # If both are poor, return whichever has more
    if js_len >= bs_len:
        return js_text or "", "js"
    return bs_text or "", "beautifulsoup"


# ---------------------------------------------------------------------------
# Main extraction: get_content
# ---------------------------------------------------------------------------

async def get_content(arguments: dict) -> str:
    """Extract page content with multi-strategy approach.
    
    Flow:
    1. Wait for content to be ready (loading indicators gone)
    2. Optionally scroll to trigger lazy-loaded content
    3. Run JS-based extraction (Readability) in the browser
    4. Run BeautifulSoup-based extraction (server-side)
    5. Pick the best result; validate quality
    6. Convert to requested format
    7. Attach metadata if requested
    """
    try:
        input_data = GetContentInput(**arguments)
        manager = await BrowserManager.get_instance()
        page = await manager.ensure_page()

        extraction_method = "unknown"
        metadata = {}

        # --- Step 1: Smart wait for content readiness ---
        if input_data.wait_for_content:
            wait_result = await wait_for_content(page, timeout_ms=input_data.wait_timeout)
            logger.debug("Content wait result: %s", wait_result)

        # --- Step 2: Optional lazy-load scroll ---
        if input_data.scroll_to_load:
            await scroll_to_load(page)

        # --- Step 3: Custom selector extraction (if provided) ---
        if input_data.selector:
            try:
                await page.wait_for_selector(input_data.selector, timeout=10000)
                custom_html = await page.evaluate(
                    "(sel) => { const el = document.querySelector(sel); return el ? el.innerHTML : null; }",
                    input_data.selector,
                )
                if custom_html and len(custom_html.strip()) >= _MIN_USABLE_CONTENT_LENGTH:
                    content = _format_content(custom_html, input_data.format)
                    extraction_method = f"custom_selector({input_data.selector})"
                    if input_data.include_metadata:
                        metadata = await extract_metadata_only(page)
                    return _build_response(
                        page, content, input_data.format, extraction_method, metadata,
                        include_metadata=input_data.include_metadata,
                    )
            except Exception as e:
                logger.debug("Custom selector '%s' failed: %s", input_data.selector, e)
                # Fall through to automatic extraction

        # --- Step 4: JS-based extraction (primary for dynamic pages) ---
        js_result = await extract_with_js(page)
        js_html = js_result.get("html") if js_result.get("success") else None
        js_text = js_result.get("text", "") if js_result.get("success") else ""
        js_metadata = js_result.get("metadata", {}) if js_result.get("success") else {}

        # --- Step 5: BeautifulSoup-based extraction (server-side fallback) ---
        page_html = await page.content()
        bs_html = extract_main_content(page_html)
        bs_text = html_to_text(bs_html)

        # --- Step 6: Pick best content ---
        if _content_quality(js_text) == "good":
            # JS extraction worked well — use it
            best_html = js_html
            extraction_method = f"js_readability ({js_result.get('method', 'unknown')})"
            metadata = js_metadata
        elif _content_quality(bs_text) == "good":
            # BS extraction worked — use it
            best_html = bs_html
            extraction_method = "beautifulsoup_scoring"
        else:
            # Both mediocre — pick the longer one
            if len(js_text) >= len(bs_text) and js_html:
                best_html = js_html
                extraction_method = f"js_readability ({js_result.get('method', 'fallback')})"
                metadata = js_metadata
            else:
                best_html = bs_html
                extraction_method = "beautifulsoup_fallback"

        # Get metadata if not already obtained
        if input_data.include_metadata and not metadata:
            metadata = await extract_metadata_only(page)

        # --- Step 7: Format output ---
        content = _format_content(best_html, input_data.format)

        # --- Step 8: Content quality warning ---
        quality = _content_quality(content)

        return _build_response(
            page, content, input_data.format, extraction_method, metadata,
            quality=quality,
            include_metadata=input_data.include_metadata,
        )

    except Exception as e:
        return format_error("get_content", e)


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

    if quality == "poor":
        result["warning"] = (
            "Extracted content is very short. The page may require JavaScript "
            "rendering, login, or has anti-scraping measures. Try using "
            "execute_script for custom extraction."
        )

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

        # Extract table data using JavaScript (handles complex tables better)
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
            # Detect header row (first row with all th cells)
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
