"""Web search and page interaction tools."""

import json
from urllib.parse import quote_plus
from mcp_server.browser_manager import BrowserManager
from mcp_server.schemas import (
    SearchWebInput,
    WaitForElementInput,
    ScrollPageInput
)
from mcp_server.utils.errors import format_error


async def search_web(arguments: dict) -> str:
    """Search the web using specified search engine."""
    try:
        input_data = SearchWebInput(**arguments)
        manager = await BrowserManager.get_instance()
        page = await manager.ensure_page()
        
        # Build search URL
        query_encoded = quote_plus(input_data.query)
        
        if input_data.engine == "google":
            search_url = f"https://www.google.com/search?q={query_encoded}"
            result_selector = "div.g"
            title_selector = "h3"
            link_selector = "a"
            snippet_selector = ".VwiC3b"
        elif input_data.engine == "bing":
            search_url = f"https://www.bing.com/search?q={query_encoded}"
            result_selector = "li.b_algo"
            title_selector = "h2"
            link_selector = "a"
            snippet_selector = ".b_caption p"
        else:  # duckduckgo
            search_url = f"https://duckduckgo.com/?q={query_encoded}"
            result_selector = "article[data-testid='result']"
            title_selector = "h2"
            link_selector = "a"
            snippet_selector = "[data-result='snippet']"
        
        # Navigate to search page
        await page.goto(search_url, wait_until="networkidle", timeout=30000)
        
        # Wait for results
        await page.wait_for_selector(result_selector, timeout=15000)
        
        # Extract search results
        results = await page.evaluate(f"""
            (maxResults) => {{
                const resultElements = document.querySelectorAll('{result_selector}');
                const results = [];
                
                for (let i = 0; i < Math.min(resultElements.length, maxResults); i++) {{
                    const elem = resultElements[i];
                    
                    const titleElem = elem.querySelector('{title_selector}');
                    const linkElem = elem.querySelector('{link_selector}');
                    const snippetElem = elem.querySelector('{snippet_selector}');
                    
                    if (titleElem && linkElem) {{
                        results.push({{
                            title: titleElem.textContent.trim(),
                            url: linkElem.href,
                            snippet: snippetElem ? snippetElem.textContent.trim() : ''
                        }});
                    }}
                }}
                
                return results;
            }}
        """, input_data.max_results)
        
        result = {
            "status": "success",
            "query": input_data.query,
            "engine": input_data.engine,
            "results_count": len(results),
            "results": results
        }
        
        return json.dumps(result, indent=2)
    
    except Exception as e:
        return format_error(
            "search_web",
            e,
            "The search engine may have changed its layout or blocked the request. Try a different engine."
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
            f"Element '{input_data.selector}' did not appear within {input_data.timeout}ms. Try increasing the timeout."
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
