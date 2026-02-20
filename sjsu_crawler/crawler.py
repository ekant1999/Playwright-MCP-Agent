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


def _normalize_url(raw: str | bytes) -> str:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    url, _ = urldefrag(raw)
    parsed = urlparse(url)
    # Coerce to str in case urlparse returned bytes (e.g. under some Python/env)
    scheme = parsed.scheme if isinstance(parsed.scheme, str) else (parsed.scheme or b"").decode("utf-8", errors="replace")
    netloc = parsed.netloc if isinstance(parsed.netloc, str) else (parsed.netloc or b"").decode("utf-8", errors="replace")
    path = parsed.path if isinstance(parsed.path, str) else (parsed.path or b"").decode("utf-8", errors="replace")
    normalized = parsed._replace(
        scheme=scheme.lower(),
        netloc=netloc.lower(),
        path=path.rstrip("/") or "/",
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
        ctx_opts = {"ignore_https_errors": True} if config.ignore_https_errors else {}
        context = await browser.new_context(**ctx_opts)
        page = await context.new_page()
        try:
            while stack and (config.max_pages == -1 or page_count < config.max_pages):
                url, parent_url, depth = stack.pop()

                if url in visited:
                    continue
                visited.add(url)

                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                    await asyncio.sleep(config.polite_delay_ms / 1000)
                    final_url = page.url
                    if not final_url.startswith(config.scope_prefix):
                        record = PageRecord(
                            url=url,
                            parent_url=parent_url,
                            depth=depth,
                            crawled_at=datetime.now(timezone.utc).isoformat(),
                            status="error",
                            error_msg=f"Redirected outside scope to {final_url}",
                        )
                    else:
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
                    if not norm.startswith(config.scope_prefix) or norm in visited:
                        continue
                    if any(s in norm for s in config.skip_url_contains):
                        continue
                    stack.append((norm, url, depth + 1))
        finally:
            if not config.headless:
                logger.info("Keeping browser open for 5s (headless=false)...")
                await asyncio.sleep(5)
            await browser.close()
