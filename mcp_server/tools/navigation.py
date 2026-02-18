"""Navigation tools for Playwright browser."""

from __future__ import annotations

import json
import logging
from mcp_server.browser_manager import BrowserManager
from mcp_server.schemas import (
    BrowserLaunchInput,
    NavigateInput,
    ClickInput,
    FillInput
)
from mcp_server.utils.errors import format_error

logger = logging.getLogger(__name__)

# Cloudflare challenge detection signals
_CHALLENGE_TITLES = {"just a moment...", "attention required", "checking your browser"}


async def _detect_and_wait_challenge(page, max_wait_ms: int = 20000) -> dict | None:
    """Detect Cloudflare/bot challenges after navigation and wait through them.

    Returns challenge info dict if a challenge was detected, None otherwise.
    """
    try:
        title = (await page.title()).lower()
        is_challenge = any(signal in title for signal in _CHALLENGE_TITLES)

        if not is_challenge:
            # Quick JS check for challenge elements
            is_challenge = await page.evaluate("""
                () => {
                    const el = document.querySelector(
                        '#challenge-running, #cf-challenge-running, ' +
                        '.cf-browser-verification, #challenge-stage, ' +
                        '#turnstile-wrapper, [id*="challenge"]'
                    );
                    const bodyText = (document.body && document.body.innerText) || '';
                    return !!el ||
                           bodyText.includes('Checking your browser') ||
                           bodyText.includes('Verify you are human') ||
                           bodyText.includes('Enable JavaScript and cookies');
                }
            """)

        if not is_challenge:
            return None

        logger.info("Cloudflare/bot challenge detected — waiting for auto-resolution...")

        # Import here to avoid circular deps
        from mcp_server.utils.readability import wait_through_challenge
        result = await wait_through_challenge(page, max_wait_ms=max_wait_ms)

        if result.get("resolved"):
            logger.info("Challenge resolved after %dms", result.get("waited_ms", 0))
            # Wait for the real page to load after challenge resolution
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass
        else:
            logger.warning("Challenge did NOT resolve within %dms", max_wait_ms)

        return result

    except Exception as e:
        logger.debug("Challenge detection failed: %s", e)
        return None


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
    """Navigate to a URL with automatic Cloudflare challenge handling."""
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

        # Check for Cloudflare/bot challenge and auto-wait
        challenge_info = await _detect_and_wait_challenge(page)

        # Re-read title/url after potential challenge resolution
        if challenge_info and challenge_info.get("resolved"):
            title = await page.title()
            url = page.url

        # Check for blocked pages (paywall, ad-blocker wall, etc.)
        blocked_info = None
        try:
            from mcp_server.utils.readability import detect_blocked_page
            blocked_info = await detect_blocked_page(page)
        except Exception:
            pass

        result = {
            "status": "success",
            "title": title,
            "url": url,
            "http_status": status,
            "message": f"Successfully navigated to {url}"
        }

        if challenge_info:
            result["challenge"] = challenge_info

        if blocked_info and blocked_info.get("is_blocked"):
            signals = blocked_info.get("signals", [])
            result["warning"] = (
                f"Page may be blocked by: {', '.join(signals)}. "
                "Content extraction may return incomplete results."
            )

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
