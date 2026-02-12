"""FastMCP server with all browser automation and research tools."""

from fastmcp import FastMCP
from mcp_server.tools import navigation, extraction, search, arxiv_tools, ieee_tools

# Create MCP server
mcp = FastMCP("playwright-browser-agent")


# Register navigation tools
@mcp.tool()
async def browser_launch(
    headless: bool = False,
    viewport_width: int = 1920,
    viewport_height: int = 1080
) -> str:
    """Launch Chromium browser. Call this before any browser-based tools.
    
    Args:
        headless: Run browser in headless mode (no UI)
        viewport_width: Browser viewport width in pixels
        viewport_height: Browser viewport height in pixels
    """
    return await navigation.browser_launch({
        "headless": headless,
        "viewport_width": viewport_width,
        "viewport_height": viewport_height
    })


@mcp.tool()
async def navigate(url: str, wait_until: str = "domcontentloaded") -> str:
    """Navigate to a URL.
    
    Args:
        url: The URL to navigate to
        wait_until: When to consider navigation complete (load, domcontentloaded, networkidle)
    """
    return await navigation.navigate({"url": url, "wait_until": wait_until})


@mcp.tool()
async def click(selector: str) -> str:
    """Click an element on the page.
    
    Args:
        selector: CSS selector of the element to click
    """
    return await navigation.click({"selector": selector})


@mcp.tool()
async def fill(selector: str, value: str) -> str:
    """Fill an input field with text.
    
    Args:
        selector: CSS selector of the input element
        value: Text to fill into the input
    """
    return await navigation.fill({"selector": selector, "value": value})


@mcp.tool()
async def browser_close() -> str:
    """Close the browser and cleanup resources."""
    return await navigation.browser_close({})


# Register extraction tools
@mcp.tool()
async def get_content(format: str = "markdown") -> str:
    """Extract FULL content from the current page. Returns original content without truncation.
    
    Args:
        format: Output format - text, markdown, or html
    """
    return await extraction.get_content({"format": format})


@mcp.tool()
async def extract_table(selector: str = "table", format: str = "json") -> str:
    """Extract data from an HTML table.
    
    Args:
        selector: CSS selector for the table element
        format: Output format - json or csv
    """
    return await extraction.extract_table({"selector": selector, "format": format})


@mcp.tool()
async def screenshot(path: str = "screenshot.png", full_page: bool = False) -> str:
    """Capture a screenshot of the current page.
    
    Args:
        path: Filename for the screenshot
        full_page: Capture the entire scrollable page
    """
    return await extraction.screenshot({"path": path, "full_page": full_page})


@mcp.tool()
async def execute_script(script: str) -> str:
    """Execute JavaScript on the current page.
    
    Args:
        script: JavaScript code to execute
    """
    return await extraction.execute_script({"script": script})


# Register search tools
@mcp.tool()
async def search_web(query: str, engine: str = "google", max_results: int = 10) -> str:
    """Search the web and return FULL results (titles, URLs, snippets).
    
    Args:
        query: Search query
        engine: Search engine to use (google, bing, duckduckgo)
        max_results: Maximum number of results to return
    """
    return await search.search_web({
        "query": query,
        "engine": engine,
        "max_results": max_results
    })


@mcp.tool()
async def wait_for_element(selector: str, timeout: int = 30000) -> str:
    """Wait for an element to appear on the page.
    
    Args:
        selector: CSS selector to wait for
        timeout: Timeout in milliseconds
    """
    return await search.wait_for_element({"selector": selector, "timeout": timeout})


@mcp.tool()
async def scroll_page(direction: str = "down", amount: int = 500) -> str:
    """Scroll the page in specified direction.
    
    Args:
        direction: Scroll direction (up or down)
        amount: Scroll amount in pixels
    """
    return await search.scroll_page({"direction": direction, "amount": amount})


# Register arXiv tools
@mcp.tool()
async def arxiv_search(query: str, category: str = None, max_results: int = 10) -> str:
    """Search arXiv for research papers. Returns FULL metadata for all results.
    
    Args:
        query: Search query
        category: arXiv category filter (e.g., cs.CV, cs.AI, cs.LG)
        max_results: Maximum number of results
    """
    return await arxiv_tools.arxiv_search({
        "query": query,
        "category": category,
        "max_results": max_results
    })


@mcp.tool()
async def arxiv_get_paper(paper_id: str) -> str:
    """Get FULL metadata for a specific arXiv paper.
    
    Args:
        paper_id: arXiv paper ID (e.g., 2301.12345)
    """
    return await arxiv_tools.arxiv_get_paper({"paper_id": paper_id})


@mcp.tool()
async def arxiv_download_pdf(paper_id: str) -> str:
    """Download PDF for an arXiv paper.
    
    Args:
        paper_id: arXiv paper ID to download
    """
    return await arxiv_tools.arxiv_download_pdf({"paper_id": paper_id})


@mcp.tool()
async def arxiv_get_recent(category: str, max_results: int = 10, days: int = 7) -> str:
    """Get recent papers from an arXiv category.
    
    Args:
        category: arXiv category (e.g., cs.CV)
        max_results: Maximum number of papers
        days: Number of days to look back
    """
    return await arxiv_tools.arxiv_get_recent({
        "category": category,
        "max_results": max_results,
        "days": days
    })


# Register IEEE tools
@mcp.tool()
async def ieee_search(query: str, max_results: int = 10) -> str:
    """Search IEEE Xplore for research papers. Returns FULL results.
    
    Args:
        query: Search query
        max_results: Maximum number of results
    """
    return await ieee_tools.ieee_search({"query": query, "max_results": max_results})


@mcp.tool()
async def ieee_get_paper(url: str) -> str:
    """Get FULL metadata for a specific IEEE paper.
    
    Args:
        url: IEEE Xplore paper URL
    """
    return await ieee_tools.ieee_get_paper({"url": url})


@mcp.tool()
async def ieee_download_pdf(url: str) -> str:
    """Download PDF for an IEEE paper (if accessible).
    
    Args:
        url: IEEE Xplore paper URL
    """
    return await ieee_tools.ieee_download_pdf({"url": url})


# Run the server
if __name__ == "__main__":
    mcp.run()
