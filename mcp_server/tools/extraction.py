"""Content extraction tools for Playwright browser."""

import json
import csv
from io import StringIO
from mcp_server.browser_manager import BrowserManager
from mcp_server.schemas import (
    GetContentInput,
    ExtractTableInput,
    ScreenshotInput,
    ExecuteScriptInput
)
from mcp_server.utils.errors import format_error
from mcp_server.utils.parser import html_to_text, html_to_markdown, extract_main_content
from mcp_server.utils.file_manager import file_manager


async def get_content(arguments: dict) -> str:
    """Extract page content in specified format."""
    try:
        input_data = GetContentInput(**arguments)
        manager = await BrowserManager.get_instance()
        page = await manager.ensure_page()
        
        # Get page HTML
        html = await page.content()
        
        # Extract main content
        main_html = extract_main_content(html)
        
        # Convert based on format
        if input_data.format == "html":
            content = main_html
        elif input_data.format == "text":
            content = html_to_text(main_html)
        else:  # markdown
            content = html_to_markdown(main_html)
        
        # Get page metadata
        title = await page.title()
        url = page.url
        
        result = {
            "status": "success",
            "url": url,
            "title": title,
            "format": input_data.format,
            "content": content,
            "content_length": len(content)
        }
        
        return json.dumps(result, indent=2)
    
    except Exception as e:
        return format_error("get_content", e)


async def extract_table(arguments: dict) -> str:
    """Extract HTML table data."""
    try:
        input_data = ExtractTableInput(**arguments)
        manager = await BrowserManager.get_instance()
        page = await manager.ensure_page()
        
        # Wait for table
        await page.wait_for_selector(input_data.selector, timeout=10000)
        
        # Extract table data using JavaScript
        table_data = await page.evaluate(f"""
            () => {{
                const table = document.querySelector('{input_data.selector}');
                if (!table) return null;
                
                const rows = Array.from(table.querySelectorAll('tr'));
                return rows.map(row => {{
                    const cells = Array.from(row.querySelectorAll('th, td'));
                    return cells.map(cell => cell.textContent.trim());
                }});
            }}
        """)
        
        if not table_data:
            return format_error(
                "extract_table",
                Exception("Table not found"),
                f"No table found with selector: {input_data.selector}"
            )
        
        # Format output
        if input_data.format == "csv":
            output = StringIO()
            writer = csv.writer(output)
            writer.writerows(table_data)
            formatted_data = output.getvalue()
        else:  # json
            # First row as headers if it looks like headers
            if table_data and len(table_data) > 1:
                headers = table_data[0]
                rows = table_data[1:]
                formatted_data = [
                    dict(zip(headers, row)) for row in rows
                ]
            else:
                formatted_data = table_data
        
        result = {
            "status": "success",
            "format": input_data.format,
            "rows": len(table_data),
            "data": formatted_data
        }
        
        return json.dumps(result, indent=2)
    
    except Exception as e:
        return format_error("extract_table", e)


async def screenshot(arguments: dict) -> str:
    """Capture a screenshot of the current page."""
    try:
        input_data = ScreenshotInput(**arguments)
        manager = await BrowserManager.get_instance()
        page = await manager.ensure_page()
        
        # Capture screenshot
        screenshot_bytes = await page.screenshot(full_page=input_data.full_page)
        
        # Save to file
        file_info = file_manager.save_file(screenshot_bytes, input_data.path)
        
        result = {
            "status": "success",
            "message": "Screenshot captured successfully",
            "full_page": input_data.full_page,
            **file_info
        }
        
        return json.dumps(result, indent=2)
    
    except Exception as e:
        return format_error("screenshot", e)


async def execute_script(arguments: dict) -> str:
    """Execute JavaScript on the current page."""
    try:
        input_data = ExecuteScriptInput(**arguments)
        manager = await BrowserManager.get_instance()
        page = await manager.ensure_page()
        
        # Execute script
        script_result = await page.evaluate(input_data.script)
        
        result = {
            "status": "success",
            "result": script_result,
            "result_type": type(script_result).__name__
        }
        
        return json.dumps(result, indent=2)
    
    except Exception as e:
        return format_error(
            "execute_script",
            e,
            "Make sure the JavaScript code is valid and safe to execute."
        )
