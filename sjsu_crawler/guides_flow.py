"""Guides flow: fetch Research Guides list (by subject/course/type), optional full-content and downloads."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from playwright.async_api import async_playwright, Page

from .config import Config
from .db import init_schema, upsert_guide
from .models import GuideRecord
from .paths import guides_json_path, get_output_dir, download_dir_for

logger = logging.getLogger(__name__)

# Selectors and URL patterns for LibGuides / research guides
GUIDES_LIST_SELECTORS = [
    '[data-guide-id]',
    '.s-lg-guide',
    '.guide-card',
    'a[href*="/guides/"]',
    'a[href*="libguides"]',
]
GUIDES_URL_PATTERNS = ("/guides/", "libguides", "research-guides")
MAIN_CONTENT_SELECTOR = "#s-lg-content"


async def _extract_guides_list(page: Page, base_url: str) -> list[tuple[str, str]]:
    """Extract (url, title) pairs from current page using multiple strategies."""
    results: list[tuple[str, str]] = []
    seen_urls: set[str] = set()

    def norm(href: str) -> str:
        u = urljoin(base_url, href)
        u = u.split("#")[0].rstrip("/") or u
        return u

    # Strategy 1: Links that look like guide pages (raw string so \/ in JS regex is not a Python escape)
    links = await page.evaluate(
        r"""(baseUrl) => {
        const out = [];
        const base = baseUrl.replace(/\/$/, '');
        for (const a of document.querySelectorAll('a[href]')) {
            const href = a.href;
            const text = (a.innerText || '').trim();
            if (!href || !text) continue;
            if (href.includes('/guides/') || href.includes('libguides') || href.includes('research-guides')) {
                let u = href.split('#')[0].replace(/\/$/, '') || href;
                if (u.startsWith('/')) u = base + u;
                out.push({ url: u, title: text.slice(0, 500) });
            }
        }
        return out;
    }""",
        base_url,
    )
    for item in links:
        url = (item.get("url") or "").strip()
        title = (item.get("title") or "").strip()
        if url and url not in seen_urls and any(p in url for p in GUIDES_URL_PATTERNS):
            seen_urls.add(url)
            results.append((url, title or url))

    # Strategy 2: Card/guide elements with links inside
    for sel in ['[data-guide-id]', '.s-lg-guide', '.guide-card']:
        try:
            els = await page.query_selector_all(sel)
            for el in els:
                a = await el.query_selector("a[href]")
                if not a:
                    continue
                href = await a.get_attribute("href")
                title = await a.inner_text()
                if href:
                    url = norm(href)
                    if url not in seen_urls and any(p in url for p in GUIDES_URL_PATTERNS):
                        seen_urls.add(url)
                        results.append((url, (title or "").strip()[:500] or url))
        except Exception as e:
            logger.debug("Selector %s failed: %s", sel, e)

    return results


async def _extract_full_content(page: Page) -> tuple[str, list[dict], list[str]]:
    """Extract full text, sections, and links from #s-lg-content."""
    full_text = ""
    sections: list[dict] = []
    links_out: list[str] = []

    try:
        root = await page.query_selector(MAIN_CONTENT_SELECTOR)
        if not root:
            root = await page.query_selector("body")
        if not root:
            return "", [], []

        full_text = await root.evaluate("el => (el && el.innerText) ? el.innerText.replace(/\\s+/g, ' ').trim() : ''")
        full_text = re.sub(r"\s+", " ", (full_text or "")).strip()

        sections = await root.evaluate(
            """(el) => {
            if (!el) return [];
            const boxes = el.querySelectorAll('.s-lib-box');
            if (!boxes.length) return [];
            const out = [];
            for (const box of boxes) {
                const h = box.querySelector('h2, h3, h4, h5, [class*="title"]');
                out.push({
                    title: h ? h.innerText.trim() : '',
                    text: box.innerText.trim().slice(0, 2000)
                });
            }
            return out;
        }""",
            root,
        )

        links_out = await root.evaluate(
            """(el) => {
            if (!el) return [];
            const seen = new Set();
            const out = [];
            for (const a of el.querySelectorAll('a[href]')) {
                const href = a.href;
                if (href && !seen.has(href)) { seen.add(href); out.push(href); }
            }
            return out;
        }""",
            root,
        )
    except Exception as e:
        logger.warning("Full content extraction failed: %s", e)

    return full_text, sections or [], links_out or []


async def _download_pdf_or_doc(
    page: Page,
    url: str,
    download_dir: Path,
    polite_delay_ms: int,
) -> str:
    """Try to download PDF or document from a result page; return local path or empty."""
    # Optional: use page.goto(result_url) and look for PDF / Full text / Download links, then trigger download
    # For now we only handle direct PDF links; full implementation can follow links on the page
    path = ""
    try:
        if url.lower().endswith(".pdf"):
            async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                r = await client.get(url)
                if r.status_code == 200 and "pdf" in (r.headers.get("content-type") or "").lower():
                    name = Path(urlparse(url).path).name or "document.pdf"
                    safe = re.sub(r'[<>:"/\\|?*]', "_", name)[:120]
                    dest = download_dir / safe
                    dest.write_bytes(r.content)
                    path = str(dest)
        await asyncio.sleep(polite_delay_ms / 1000)
    except Exception as e:
        logger.debug("Download failed for %s: %s", url, e)
    return path


async def _fetch_one_guide_full(
    page: Page,
    url: str,
    title: str,
    query: str,
    query_type: str,
    config: Config,
    download_dir: Path | None,
) -> GuideRecord:
    """Visit guide URL and extract full content; optionally download PDFs."""
    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(config.polite_delay_ms / 1000)
        full_text, sections, links_out = await _extract_full_content(page)
        download_path = ""
        if download_dir:
            for link in links_out:
                if ".pdf" in link.lower() or "download" in link.lower() or "fulltext" in link.lower():
                    download_path = await _download_pdf_or_doc(page, link, download_dir, config.polite_delay_ms)
                    if download_path:
                        break
        return GuideRecord(
            url=url,
            title=title,
            query=query,
            query_type=query_type,
            fetched_at=fetched_at,
            full_content=full_text,
            sections=sections,
            links_out=links_out,
        )
    except Exception as e:
        logger.warning("Failed to fetch guide %s: %s", url, e)
        return GuideRecord(
            url=url,
            title=title,
            query=query,
            query_type=query_type,
            fetched_at=fetched_at,
            status="error",
            error_msg=str(e),
        )


async def run_guides(
    config: Config,
    query: str = "all",
    query_type: str = "all",
    full_content: bool = False,
    no_db: bool = False,
    download_attachments: bool = True,
) -> list[GuideRecord]:
    """
    Fetch Research Guides list; optionally visit each for full content and downloads.
    Always writes output/guides_<query>.json. Upserts to research_guides when Postgres enabled and not no_db.
    """
    base = config.library_base_url.rstrip("/")
    start_url = f"{base}/research-guides"
    out_path = guides_json_path(query)
    download_dir = download_dir_for("guides_downloads") if download_attachments and full_content else None

    records: list[GuideRecord] = []
    fetched_at = datetime.now(timezone.utc).isoformat()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=config.headless)
        ctx_opts = {"ignore_https_errors": True} if config.ignore_https_errors else {}
        context = await browser.new_context(**ctx_opts)
        page = await context.new_page()

        try:
            await page.goto(start_url, wait_until="domcontentloaded", timeout=30_000)
            await asyncio.sleep(config.polite_delay_ms / 1000)

            # Optional: follow "See all subject guides" if present
            try:
                all_link = await page.query_selector('a[href*="guides"], a:has-text("See all subject guides")')
                if all_link:
                    href = await all_link.get_attribute("href")
                    if href and "guides" in href:
                        u = urljoin(base, href)
                        await page.goto(u, wait_until="domcontentloaded", timeout=30_000)
                        await asyncio.sleep(config.polite_delay_ms / 1000)
            except Exception:
                pass

            guide_tuples = await _extract_guides_list(page, base)
            if not guide_tuples:
                logger.warning("No guides found on %s; check selectors", page.url)

            for url, title in guide_tuples:
                if full_content:
                    rec = await _fetch_one_guide_full(
                        page, url, title, query, query_type, config, download_dir
                    )
                else:
                    rec = GuideRecord(
                        url=url,
                        title=title,
                        query=query,
                        query_type=query_type,
                        fetched_at=fetched_at,
                    )
                records.append(rec)

        finally:
            if not config.headless:
                await asyncio.sleep(2)
            await browser.close()

    # Write JSON
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump([r.to_dict() for r in records], f, ensure_ascii=False, indent=2)
    logger.info("Wrote %s (%d guides)", out_path, len(records))

    # Postgres
    if config.postgres.enabled and not no_db:
        import asyncpg
        conn = await asyncpg.connect(config.postgres.url)
        await init_schema(conn)
        try:
            for r in records:
                try:
                    await upsert_guide(conn, r)
                except Exception as e:
                    logger.exception("upsert_guide failed for %s: %s", r.url, e)
        finally:
            await conn.close()
        logger.info("Upserted %d guides to research_guides", len(records))

    return records
