from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from playwright.async_api import Page

from .models import PageRecord

logger = logging.getLogger(__name__)


async def extract(
    page: Page,
    url: str,
    parent_url: str | None,
    depth: int,
) -> PageRecord:
    crawled_at = datetime.now(timezone.utc).isoformat()

    title = await _safe(page, _extract_title, "title")
    meta_description = await _safe(page, _extract_meta_description, "meta_description")
    full_text = await _safe(page, _extract_full_text, "full_text")
    headings = await _safe(page, _extract_headings, "headings") or []
    sections = await _safe(page, _extract_sections, "sections") or []
    paragraphs: list[str] = []
    if not sections:
        paragraphs = await _safe(page, _extract_paragraphs, "paragraphs") or []
    tables = await _safe(page, _extract_tables, "tables") or []
    links_out = await _safe(page, _extract_links, "links_out") or []
    images = await _safe(page, _extract_images, "images") or []

    return PageRecord(
        url=url,
        parent_url=parent_url,
        depth=depth,
        crawled_at=crawled_at,
        title=title or "",
        meta_description=meta_description or "",
        full_text=full_text or "",
        headings=headings,
        sections=sections,
        paragraphs=paragraphs,
        tables=tables,
        links_out=links_out,
        images=images,
    )


async def _safe(page: Page, fn, label: str):
    try:
        return await fn(page)
    except Exception:
        logger.warning("extraction step '%s' failed for %s", label, page.url, exc_info=True)
        return None


async def _extract_title(page: Page) -> str:
    return (await page.title()).strip()


async def _extract_meta_description(page: Page) -> str:
    return await page.evaluate(
        """() => {
            const el = document.querySelector('meta[name="description"]');
            return el ? (el.getAttribute('content') || '') : '';
        }"""
    )


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _main_content_script(field: str) -> str:
    """JS to resolve main content root (LibGuides center column) or body. Never null."""
    return """
    (() => {
        const main = document.querySelector('#s-lg-content') || document.querySelector('[role="main"]') || document.querySelector('.s-lg-content-col') || document.body || document.documentElement;
        const root = main || document.body || document.documentElement;
    """ + field + """
    })();
    """


async def _extract_full_text(page: Page) -> str:
    raw = await page.evaluate(
        _main_content_script("""
        return root.innerText || '';
        """)
    )
    return _normalize_whitespace(raw or "")


async def _extract_headings(page: Page) -> list[dict]:
    return await page.evaluate(
        _main_content_script("""
        const out = [];
        for (const el of root.querySelectorAll('h1, h2, h3, h4')) {
            const level = parseInt(el.tagName[1], 10);
            const text = el.innerText.trim();
            if (text) out.push({level, text});
        }
        return out;
        """)
    )


async def _extract_sections(page: Page) -> list[dict]:
    return await page.evaluate(
        _main_content_script("""
        const boxes = root.querySelectorAll('.s-lib-box');
        if (!boxes.length) return [];
        const sections = [];
        for (const box of boxes) {
            const heading = box.querySelector('h2, h3, h4, h5, [class*="title"]');
            const title = heading ? heading.innerText.trim() : '';
            const text = box.innerText.trim();
            const links = [];
            for (const a of box.querySelectorAll('a[href]')) {
                const href = a.href;
                const context = a.closest('p, li, div');
                links.push({
                    href,
                    text: a.innerText.trim(),
                    context: context ? context.innerText.trim().slice(0, 300) : ''
                });
            }
            sections.push({title, text, links});
        }
        return sections;
        """)
    )


async def _extract_paragraphs(page: Page) -> list[str]:
    return await page.evaluate(
        _main_content_script("""
        const out = [];
        for (const el of root.querySelectorAll('p, li')) {
            const t = el.innerText.trim();
            if (t) out.push(t);
        }
        return out;
        """)
    )


async def _extract_tables(page: Page) -> list[dict]:
    return await page.evaluate(
        _main_content_script("""
        const tables = [];
        for (const table of root.querySelectorAll('table')) {
            const headers = [];
            for (const th of table.querySelectorAll('th')) {
                headers.push(th.innerText.trim());
            }
            const rows = [];
            for (const tr of table.querySelectorAll('tbody tr, tr')) {
                const cells = [];
                let hasData = false;
                for (const td of tr.querySelectorAll('td')) {
                    cells.push(td.innerText.trim());
                    hasData = true;
                }
                if (hasData) rows.push(cells);
            }
            tables.push({headers, rows});
        }
        return tables;
        """)
    )


async def _extract_links(page: Page) -> list[str]:
    return await page.evaluate(
        """() => {
            const seen = new Set();
            const out = [];
            for (const a of document.querySelectorAll('a[href]')) {
                const href = a.href;
                if (href && !seen.has(href)) {
                    seen.add(href);
                    out.push(href);
                }
            }
            return out;
        }"""
    )


async def _extract_images(page: Page) -> list[dict]:
    return await page.evaluate(
        """() => {
            const out = [];
            for (const img of document.querySelectorAll('img')) {
                const src = img.src;
                if (src) out.push({src, alt: img.alt || ''});
            }
            return out;
        }"""
    )
