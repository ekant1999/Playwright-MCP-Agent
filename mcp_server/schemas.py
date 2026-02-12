"""Pydantic schemas for tool input validation."""

from pydantic import BaseModel, Field
from typing import Optional, Literal


# Navigation tool schemas
class BrowserLaunchInput(BaseModel):
    headless: bool = Field(default=False, description="Launch browser in headless mode")
    viewport_width: int = Field(default=1920, description="Browser viewport width")
    viewport_height: int = Field(default=1080, description="Browser viewport height")


class NavigateInput(BaseModel):
    url: str = Field(description="URL to navigate to")
    wait_until: Literal["load", "domcontentloaded", "networkidle"] = Field(
        default="domcontentloaded",
        description="When to consider navigation complete"
    )


class ClickInput(BaseModel):
    selector: str = Field(description="CSS selector of element to click")


class FillInput(BaseModel):
    selector: str = Field(description="CSS selector of input element")
    value: str = Field(description="Text value to fill")


# Extraction tool schemas
class GetContentInput(BaseModel):
    format: Literal["text", "markdown", "html"] = Field(
        default="markdown",
        description="Output format for page content"
    )
    selector: Optional[str] = Field(
        default=None,
        description="CSS selector to extract content from a specific element. "
        "If not provided, auto-detects the main content area."
    )
    wait_for_content: bool = Field(
        default=True,
        description="Wait for dynamic content to finish loading before extraction"
    )
    wait_timeout: int = Field(
        default=5000,
        description="Maximum time (ms) to wait for content to be ready"
    )
    scroll_to_load: bool = Field(
        default=False,
        description="Scroll down the page to trigger lazy-loaded content before extraction"
    )
    include_metadata: bool = Field(
        default=False,
        description="Include page metadata (author, date, description, etc.) in the response"
    )


class ExtractTableInput(BaseModel):
    selector: str = Field(default="table", description="CSS selector for table element")
    format: Literal["json", "csv"] = Field(default="json", description="Output format")


class ScreenshotInput(BaseModel):
    path: str = Field(default="screenshot.png", description="Filename for screenshot")
    full_page: bool = Field(default=False, description="Capture full scrollable page")


class ExecuteScriptInput(BaseModel):
    script: str = Field(description="JavaScript code to execute")


# Search tool schemas
class SearchWebInput(BaseModel):
    query: str = Field(description="Search query")
    engine: Literal["google", "bing", "duckduckgo"] = Field(
        default="google",
        description="Search engine to use"
    )
    max_results: int = Field(default=10, description="Maximum number of results")


class WaitForElementInput(BaseModel):
    selector: str = Field(description="CSS selector to wait for")
    timeout: int = Field(default=30000, description="Timeout in milliseconds")


class ScrollPageInput(BaseModel):
    direction: Literal["up", "down"] = Field(default="down", description="Scroll direction")
    amount: int = Field(default=500, description="Scroll amount in pixels")


# arXiv tool schemas
class ArxivSearchInput(BaseModel):
    query: str = Field(description="Search query for arXiv papers")
    category: Optional[str] = Field(default=None, description="arXiv category (e.g., cs.CV, cs.AI)")
    max_results: int = Field(default=10, description="Maximum number of results")


class ArxivGetPaperInput(BaseModel):
    paper_id: str = Field(description="arXiv paper ID (e.g., 2301.12345)")


class ArxivDownloadPdfInput(BaseModel):
    paper_id: str = Field(description="arXiv paper ID to download")


class ArxivGetRecentInput(BaseModel):
    category: str = Field(description="arXiv category (e.g., cs.CV)")
    max_results: int = Field(default=10, description="Maximum number of papers")
    days: int = Field(default=7, description="Number of days to look back")


# IEEE tool schemas
class IeeeSearchInput(BaseModel):
    query: str = Field(description="Search query for IEEE papers")
    max_results: int = Field(default=10, description="Maximum number of results")


class IeeeGetPaperInput(BaseModel):
    url: str = Field(description="IEEE Xplore paper URL")


class IeeeDownloadPdfInput(BaseModel):
    url: str = Field(description="IEEE Xplore paper URL to download PDF from")
