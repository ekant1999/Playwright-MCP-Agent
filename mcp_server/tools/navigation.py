"""Navigation tools for Playwright browser."""

import json
from mcp_server.browser_manager import BrowserManager
from mcp_server.schemas import (
    BrowserLaunchInput,
    NavigateInput,
    ClickInput,
    FillInput
)
from mcp_server.utils.errors import format_error


async def browser_launch(arguments: dict) -> str:
    """Launch Chromium browser via Playwright."""
    try:
        input_data = BrowserLaunchInput(**arguments)
        manager = await BrowserManager.get_instance()
        
        result = await manager.launch(
            headless=input_data.headless,
            viewport_width=input_data.viewport_width,
            viewport_height=input_data.viewport_height
        )
        
        return json.dumps(result, indent=2)
    
    except Exception as e:
        return format_error("browser_launch", e)


async def navigate(arguments: dict) -> str:
    """Navigate to a URL."""
    try:
        input_data = NavigateInput(**arguments)
        manager = await BrowserManager.get_instance()
        page = await manager.ensure_page()
        
        # Navigate to URL
        response = await page.goto(
            input_data.url,
            wait_until=input_data.wait_until,
            timeout=60000
        )
        
        # Get page info
        title = await page.title()
        url = page.url
        status = response.status if response else "unknown"
        
        result = {
            "status": "success",
            "title": title,
            "url": url,
            "http_status": status,
            "message": f"Successfully navigated to {url}"
        }
        
        return json.dumps(result, indent=2)
    
    except Exception as e:
        return format_error("navigate", e, "Check if the URL is valid and accessible.")


async def click(arguments: dict) -> str:
    """Click an element on the page."""
    try:
        input_data = ClickInput(**arguments)
        manager = await BrowserManager.get_instance()
        page = await manager.ensure_page()
        
        # Wait for element and click
        await page.wait_for_selector(input_data.selector, timeout=10000)
        await page.click(input_data.selector)
        
        result = {
            "status": "success",
            "message": f"Successfully clicked element: {input_data.selector}",
            "selector": input_data.selector
        }
        
        return json.dumps(result, indent=2)
    
    except Exception as e:
        return format_error(
            "click",
            e,
            "Make sure the selector is correct and the element is visible and clickable."
        )


async def fill(arguments: dict) -> str:
    """Fill an input field with text."""
    try:
        input_data = FillInput(**arguments)
        manager = await BrowserManager.get_instance()
        page = await manager.ensure_page()
        
        # Wait for element and fill
        await page.wait_for_selector(input_data.selector, timeout=10000)
        await page.fill(input_data.selector, input_data.value)
        
        result = {
            "status": "success",
            "message": f"Successfully filled element: {input_data.selector}",
            "selector": input_data.selector,
            "value_length": len(input_data.value)
        }
        
        return json.dumps(result, indent=2)
    
    except Exception as e:
        return format_error(
            "fill",
            e,
            "Make sure the selector points to an input, textarea, or contenteditable element."
        )


async def browser_close(arguments: dict) -> str:
    """Close the browser and cleanup resources."""
    try:
        manager = await BrowserManager.get_instance()
        result = await manager.close()
        
        return json.dumps(result, indent=2)
    
    except Exception as e:
        return format_error("browser_close", e)
