"""Singleton browser manager for Playwright."""

import os
from pathlib import Path
from typing import Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright


# Realistic Chrome user-agent (kept current)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

# JavaScript to mask Playwright/automation fingerprints
_STEALTH_JS = """
() => {
    // Remove webdriver flag
    Object.defineProperty(navigator, 'webdriver', { get: () => false });

    // Realistic plugins array
    Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5],
    });

    // Realistic languages
    Object.defineProperty(navigator, 'languages', {
        get: () => ['en-US', 'en'],
    });

    // Hide automation-related Chrome properties
    window.chrome = { runtime: {} };

    // Patch permissions query
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters);
}
"""


def _find_chromium_executable() -> Optional[str]:
    """Find Chromium executable when PLAYWRIGHT_BROWSERS_PATH has x64 on arm64 Mac."""
    browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if not browsers_path or not os.path.isdir(browsers_path):
        return None
    base = Path(browsers_path)
    # Prefer full Chrome for Testing (works headless with --headless)
    for pattern in [
        "chromium-*/chrome-mac-x64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
        "chromium-*/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
        "chromium_headless_shell-*/chrome-headless-shell-mac-x64/chrome-headless-shell",
        "chromium_headless_shell-*/chrome-headless-shell-mac-arm64/chrome-headless-shell",
    ]:
        for p in base.glob(pattern):
            if p.is_file() and os.access(p, os.X_OK):
                return str(p)
    return None


class BrowserManager:
    """Singleton manager for Playwright browser instance."""
    
    _instance: Optional['BrowserManager'] = None
    _playwright: Optional[Playwright] = None
    _browser: Optional[Browser] = None
    _context: Optional[BrowserContext] = None
    _page: Optional[Page] = None
    _headless: bool = False
    _viewport_width: int = 1920
    _viewport_height: int = 1080
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    async def get_instance(cls) -> 'BrowserManager':
        """Get or create the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    async def launch(
        self,
        headless: bool = False,
        viewport_width: int = 1920,
        viewport_height: int = 1080
    ) -> dict:
        """Launch the browser if not already running."""
        if self._browser is not None and self._page is not None:
            return {
                "status": "already_running",
                "message": "Browser is already launched and ready.",
                "url": self._page.url if self._page else "about:blank"
            }
        
        self._headless = headless
        self._viewport_width = viewport_width
        self._viewport_height = viewport_height
        
        # Start Playwright
        self._playwright = await async_playwright().start()
        
        # Prefer explicit executable when set (e.g. project .playwright-browsers)
        launch_options = {
            "headless": headless,
            "args": [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-blink-features=AutomationControlled',
                '--disable-infobars',
            ]
        }
        executable = _find_chromium_executable()
        if executable:
            launch_options["executable_path"] = executable
        
        # Launch Chromium
        self._browser = await self._playwright.chromium.launch(**launch_options)
        
        # Create context with realistic fingerprint
        self._context = await self._browser.new_context(
            viewport={'width': viewport_width, 'height': viewport_height},
            user_agent=DEFAULT_USER_AGENT,
            locale='en-US',
            timezone_id='America/New_York',
            java_script_enabled=True,
        )
        
        # Inject stealth script into every new page automatically
        await self._context.add_init_script(_STEALTH_JS)
        
        self._page = await self._context.new_page()
        
        return {
            "status": "launched",
            "message": f"Browser launched successfully ({'headless' if headless else 'headed'} mode).",
            "viewport": f"{viewport_width}x{viewport_height}"
        }
    
    async def ensure_page(self) -> Page:
        """Get the current page or raise an error if browser not launched."""
        if self._page is None:
            raise RuntimeError(
                "Browser not launched. Please call browser_launch first."
            )
        return self._page
    
    def is_running(self) -> bool:
        """Check if browser is currently running."""
        return self._browser is not None and self._page is not None
    
    async def close(self) -> dict:
        """Close the browser and cleanup resources."""
        if self._browser is None:
            return {
                "status": "not_running",
                "message": "Browser is not running."
            }
        
        # Close browser
        await self._browser.close()
        
        # Stop Playwright
        if self._playwright:
            await self._playwright.stop()
        
        # Reset instance variables
        self._browser = None
        self._page = None
        self._playwright = None
        
        return {
            "status": "closed",
            "message": "Browser closed successfully."
        }
