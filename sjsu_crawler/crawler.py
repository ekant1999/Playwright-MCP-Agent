from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Callable
from datetime import datetime, timezone
from urllib.parse import urldefrag, urlparse, urlunparse

from playwright.async_api import async_playwright

from .config import Config
from .models import PageRecord

logger = logging.getLogger(__name__)


def _normalize_url(raw: str) -> str:
    url, _ = urldefrag(raw)
    parsed = urlparse(url)
    normalized = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        path=parsed.path.rstrip("/") or "/",
    )
    return urlunparse(normalized)


async def crawl(
    config: Config,
    extract_fn: Callable,
) -> AsyncGenerator[PageRecord, None]:
    start_norm = _normalize_url(config.start_url)
    stack: list[tuple[str, str | None, int]] = [(start_norm, None, 0)]
    visited: set[str] = set()
    page_count = 0

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=config.headless)
        page = await browser.new_page()
        try:
            while stack and page_count < config.max_pages:
                url, parent_url, depth = stack.pop()

                if url in visited:
                    continue
                visited.add(url)

                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                    await asyncio.sleep(config.polite_delay_ms / 1000)
                    record = await extract_fn(page, url, parent_url, depth)
                except Exception as exc:
                    logger.error("failed to crawl %s: %s", url, exc)
                    record = PageRecord(
                        url=url,
                        parent_url=parent_url,
                        depth=depth,
                        crawled_at=datetime.now(timezone.utc).isoformat(),
                        status="error",
                        error_msg=str(exc),
                    )

                page_count += 1
                yield record

                if record.status != "ok":
                    continue

                if config.max_depth != -1 and depth >= config.max_depth:
                    continue

                for link in record.links_out:
                    norm = _normalize_url(link)
                    if norm.startswith(config.scope_prefix) and norm not in visited:
                        stack.append((norm, url, depth + 1))
        finally:
            await browser.close()
