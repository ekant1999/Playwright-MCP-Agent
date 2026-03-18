"""Search flow: OneSearch (Primo) for articles/books/PDFs; extract results and optional PDF download."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import httpx
from playwright.async_api import async_playwright, Frame, Page

from .config import Config
from .db import init_schema, upsert_search_result
from .extractor import extract
from .models import SearchResultRecord
from .paths import download_dir_for, get_output_dir, search_json_path

logger = logging.getLogger(__name__)

# Primo selectors (Ex Libris Primo discovery UI — try multiple; page may load dynamically)
PRIMO_SEARCH_INPUT_SELECTORS = [
    'input[placeholder*="Search"]',
    'input[name="search"]',
    '#searchBar',
    'input[id*="search"]',
    'input[type="search"]',
    'input[aria-label*="search" i]',
    'prm-search-bar input',
    '.search-input input',
    'input.search-query',
    'input[type="text"]',  # last resort: first visible text input
]
PRIMO_RESULT_ITEM = "prm-brief-result, .prm-brief-result"
PRIMO_FULLDISPLAY_LINK = 'a[href*="fulldisplay"]'

# Library homepage (SJSU) OneSearch bar — used when Primo direct URL doesn’t expose the input
LIBRARY_HOMEPAGE_SEARCH_PLACEHOLDERS = [
    "Search for books, articles, newspapers, theses, and more",
    "Search for books, articles",
    "Search anything",
]


async def _find_search_input_in_frame(frame: Frame, timeout_ms: int = 3000) -> object | None:
    """Try each known selector in the given frame; return first visible input or None."""
    for sel in PRIMO_SEARCH_INPUT_SELECTORS:
        try:
            el = await frame.wait_for_selector(sel, state="visible", timeout=timeout_ms)
            if el:
                return el
        except Exception:
            continue
    return None


async def _find_primo_search_input(page: Page, timeout_ms: int = 5000) -> object | None:
    """Find the Primo search input on the main page or in any iframe. Returns ElementHandle or None."""
    # 1) Main page
    el = await _find_search_input_in_frame(page, timeout_ms=timeout_ms)
    if el:
        return el
    # 2) Any iframe (Primo often embeds the search bar in an iframe)
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        try:
            el = await _find_search_input_in_frame(frame, timeout_ms=2000)
            if el:
                logger.debug("Found Primo search input inside iframe")
                return el
        except Exception:
            continue
    return None


# Primo VE advanced search: container and first search-line input (avoids header/skip inputs)
# Prefer placeholder/role so we don't fill scope or other inputs; pierce shadow DOM via prm-*.
PRIMO_ADVANCED_QUERY_INPUT_SELECTORS = [
    "prm-advanced-search input[placeholder*='search' i]",
    "prm-advanced-search input[placeholder*='term' i]",
    "prm-advanced-search [role='textbox']",
    "prm-advanced-search input[type='text']",
    "prm-advanced-search input",
    "[class*='advanced-search'] input[placeholder*='search' i]",
    "[class*='advanced-search'] input[type='text']",
    "main input[placeholder*='search' i]",
    "main input[placeholder*='term' i]",
    "main [role='textbox']",
    "[role='main'] input[placeholder*='search' i]",
    "input[placeholder*='Enter search' i]",
    "input[placeholder*='search term' i]",
    "input[placeholder*='Search' i]",
    "input[type='text']",  # last resort
]


async def _do_advanced_search(
    page: Page,
    query: str,
    scope: str,
    material_types: list[str],
    primo_url: str,
    polite_delay_ms: int,
) -> bool:
    """
    Navigate to Primo advanced search, fill query and optional scope/material type, submit.
    Returns True if search was submitted successfully.
    """
    try:
        sep = "&" if "?" in primo_url else "?"
        advanced_url = primo_url + sep + "mode=advanced"
        await page.goto(advanced_url, wait_until="load", timeout=30_000)
        await asyncio.sleep(max(2.5, polite_delay_ms / 1000))
        try:
            await page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            pass
        await asyncio.sleep(1.5)

        # First search line: target input inside advanced form only (avoid header/skip inputs)
        query_filled = False
        for sel in PRIMO_ADVANCED_QUERY_INPUT_SELECTORS:
            loc = page.locator(sel).first
            if await loc.count() == 0:
                continue
            try:
                await loc.scroll_into_view_if_needed()
                await asyncio.sleep(100 / 1000)
                if not await loc.is_visible():
                    continue
                await loc.fill("")
                await loc.fill(query)
                await asyncio.sleep(200 / 1000)
                # Verify the input kept our value (skip if we clearly filled the wrong field)
                try:
                    value = await loc.input_value()
                except Exception:
                    value = ""
                if query and not (value or "").strip():
                    continue  # typed but value empty → likely wrong input (e.g. readonly)
                query_filled = True
                logger.debug("Filled advanced query using selector: %s", sel)
                break
            except Exception as e:
                logger.debug("Selector %s failed: %s", sel, e)
                continue
        if not query_filled:
            inp = page.get_by_placeholder(re.compile(r"Enter a search term|search term", re.I)).first
            if await inp.count() > 0 and await inp.is_visible():
                await inp.fill(query)
                query_filled = True
        if not query_filled:
            logger.warning("Could not find or fill advanced search query input")
            return False
        await asyncio.sleep(200 / 1000)

        # Optional: scope — use scope/profile dropdown, not generic text click
        if scope:
            try:
                # Open scope dropdown: combobox or element with "Search for" / "Scope"
                scope_trigger = page.get_by_role("combobox").filter(has_text=re.compile(r"search|scope|for|all", re.I)).first
                if await scope_trigger.count() == 0:
                    scope_trigger = page.get_by_text(re.compile(r"Search for|Search scope|Scope", re.I)).first
                if await scope_trigger.count() > 0:
                    await scope_trigger.scroll_into_view_if_needed()
                    await scope_trigger.click()
                    await asyncio.sleep(400 / 1000)
                    # Select the option matching scope text (e.g. "San Jose State Collections")
                    opt = page.get_by_role("option").filter(has_text=re.compile(re.escape(scope), re.I)).first
                    if await opt.count() == 0:
                        opt = page.get_by_text(scope, exact=False).first
                    if await opt.count() > 0:
                        await opt.click()
                        await asyncio.sleep(200 / 1000)
            except Exception as e:
                logger.debug("Scope selection failed: %s", e)

        # Optional: Material Type — open dropdown and select "Articles", "Book chapters", etc.
        if material_types:
            try:
                # Primo: dropdown is often opened by clicking the value (e.g. "All items"), not the "Material Type" label
                # Try in order: (1) click trigger that shows current value, (2) click "Material Type" label
                mat_section = page.locator("prm-advanced-search").or_(page.locator("[class*='advanced-search']"))
                if await mat_section.count() == 0:
                    mat_section = page
                for idx, label in enumerate(material_types):
                    lbl = label.strip()
                    if not lbl:
                        continue
                    logger.info("Selecting material type: %s", lbl)
                    opened = False
                    # Open dropdown: click the Material Type value trigger (e.g. "All items") inside the section
                    for trigger_text in ["All items", "Material Type"]:
                        trigger = mat_section.get_by_text(trigger_text, exact=False).first
                        if await trigger.count() > 0 and await trigger.is_visible():
                            await trigger.scroll_into_view_if_needed()
                            await asyncio.sleep(150 / 1000)
                            await trigger.click()
                            await asyncio.sleep(600 / 1000)
                            opened = True
                            break
                    if not opened:
                        logger.warning("Material type dropdown trigger not found")
                        continue
                    # Click the option (listbox option or div with exact text)
                    opt = page.get_by_role("option", name=re.compile(re.escape(lbl), re.I)).first
                    if await opt.count() == 0:
                        opt = page.locator("[role='option']").filter(has_text=re.compile(re.escape(lbl), re.I)).first
                    if await opt.count() == 0:
                        opt = page.get_by_text(lbl, exact=True).first
                    if await opt.count() == 0:
                        opt = page.get_by_text(re.compile(re.escape(lbl), re.I)).first
                    if await opt.count() > 0:
                        await opt.scroll_into_view_if_needed()
                        await asyncio.sleep(150 / 1000)
                        await opt.click()
                        await asyncio.sleep(400 / 1000)
                        logger.info("Material type selected: %s", lbl)
                        continue
                    # Fallback: checkbox (e.g. multi-select panel)
                    chk = page.get_by_label(re.compile(re.escape(lbl), re.I)).first
                    if await chk.count() == 0:
                        chk = page.get_by_role("checkbox", name=re.compile(re.escape(lbl), re.I)).first
                    if await chk.count() > 0 and not await chk.is_checked():
                        await chk.check()
                        await asyncio.sleep(300 / 1000)
                        logger.info("Material type checked: %s", lbl)
                    else:
                        logger.warning("Material type option not found: %s", lbl)
            except Exception as e:
                logger.warning("Material type filter failed: %s", e)

        # Click SEARCH button (avoid "Skip To Advanced Search" skip link)
        search_btn = page.get_by_role("button", name=re.compile(r"^Search$", re.I)).first
        if await search_btn.count() == 0:
            search_btn = page.locator("button[type='submit']").first
        if await search_btn.count() == 0:
            search_btn = page.get_by_text("SEARCH", exact=True).first
        if await search_btn.count() == 0:
            search_btn = page.get_by_text(re.compile(r"^SEARCH$", re.I)).first
        if await search_btn.count() == 0:
            logger.warning("Advanced search: SEARCH button not found")
            return False
        await search_btn.scroll_into_view_if_needed()
        await asyncio.sleep(200 / 1000)
        await search_btn.click()
        await page.wait_for_load_state("domcontentloaded")
        # Wait for results (Primo may keep mode=advanced in URL and load results in-page)
        try:
            await page.wait_for_selector(
                f"{PRIMO_RESULT_ITEM}, {PRIMO_FULLDISPLAY_LINK}",
                timeout=15_000,
            )
        except Exception:
            try:
                await page.wait_for_function(
                    "() => !window.location.href.includes('mode=advanced')",
                    timeout=5_000,
                )
            except Exception:
                pass
        await asyncio.sleep(2)
        return True
    except Exception as e:
        logger.warning("Advanced search failed: %s", e)
        return False


async def _find_library_homepage_search(page: Page, library_base_url: str) -> object | None:
    """On library.sjsu.edu, find the OneSearch search box by placeholder text."""
    try:
        await page.goto(library_base_url.rstrip("/") + "/", wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(1.5)
        for placeholder in LIBRARY_HOMEPAGE_SEARCH_PLACEHOLDERS:
            try:
                loc = page.get_by_placeholder(placeholder)
                if await loc.count() > 0:
                    return await loc.first.element_handle()
            except Exception:
                continue
        # Fallback: first visible input in main content
        loc = page.locator("input[type='text'], input[type='search']").first
        if await loc.count() > 0:
            return await loc.element_handle()
    except Exception as e:
        logger.debug("Library homepage search fallback failed: %s", e)
    return None


async def _extract_primo_results(page: Page, query: str, search_type: str, scope: str) -> list[SearchResultRecord]:
    """Extract result list from Primo results page (prm-brief-result or fulldisplay links)."""
    fetched_at = datetime.now(timezone.utc).isoformat()
    records: list[SearchResultRecord] = []
    seen_urls: set[str] = set()

    # Strategy 1: prm-brief-result elements
    try:
        items = await page.query_selector_all(PRIMO_RESULT_ITEM)
        for item in items:
            try:
                link = await item.query_selector("a[href*='fulldisplay'], a[href*='discovery']")
                if not link:
                    link = await item.query_selector("a[href]")
                href = await link.get_attribute("href") if link else None
                if not href:
                    continue
                url = urljoin(page.url, href)
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                title_el = await item.query_selector("h2 a, .item-title a, [class*='title'] a, a")
                title = await title_el.inner_text() if title_el else ""
                title = (title or "").strip()[:1000]

                snippet_el = await item.query_selector(".item-description, [class*='snippet'], p")
                snippet = await snippet_el.inner_text() if snippet_el else ""
                snippet = (snippet or "").strip()[:500]

                records.append(
                    SearchResultRecord(
                        url=url,
                        title=title or url,
                        query=query,
                        search_type=search_type,
                        scope=scope,
                        fetched_at=fetched_at,
                        snippet=snippet,
                    )
                )
            except Exception as e:
                logger.debug("Parse one result failed: %s", e)
    except Exception as e:
        logger.warning("prm-brief-result extraction failed: %s", e)

    # Strategy 2: fallback — any link with fulldisplay
    if not records:
        try:
            links = await page.query_selector_all(PRIMO_FULLDISPLAY_LINK)
            for a in links:
                href = await a.get_attribute("href")
                if not href:
                    continue
                url = urljoin(page.url, href)
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                title = (await a.inner_text() or "").strip()[:1000]
                records.append(
                    SearchResultRecord(
                        url=url,
                        title=title or url,
                        query=query,
                        search_type=search_type,
                        scope=scope,
                        fetched_at=fetched_at,
                    )
                )
        except Exception as e:
            logger.warning("fulldisplay fallback failed: %s", e)

    return records


# Primo fulldisplay page: wait for and extract main content (SPA; may use shadow DOM)
PRIMO_FULLVIEW_SELECTORS = [
    "prm-full-view",
    "[class*='full-view']",
    "[class*='fullView']",
    "prm-full-view-content",
    "[role='main']",
]


async def _extract_primo_fulldisplay_content(page: Page) -> str:
    """Extract main text from a Primo fulldisplay (record) page. Handles SPA and shadow DOM."""
    try:
        # Wait for Primo to render the full view (SPA)
        for sel in PRIMO_FULLVIEW_SELECTORS:
            try:
                await page.wait_for_selector(sel, timeout=6_000)
                break
            except Exception:
                continue
    except Exception:
        pass

    def _get_text_script() -> str:
        return """
        () => {
            const sel = ['prm-full-view', '[class*="full-view"]', '[class*="fullView"]', 'prm-full-view-content', '[role="main"]', 'main', 'body'];
            let root = null;
            for (const s of sel) {
                try {
                    const el = document.querySelector(s);
                    if (el && (el.innerText || el.textContent)) {
                        root = el;
                        break;
                    }
                } catch (e) {}
            }
            root = root || document.body;
            function textFrom(el) {
                if (!el) return '';
                let out = '';
                if (el.shadowRoot) {
                    out += textFrom(el.shadowRoot);
                }
                const walk = (n) => {
                    if (n.nodeType === Node.TEXT_NODE) {
                        const t = n.textContent.trim();
                        if (t) out += t + ' ';
                    } else if (n.nodeType === Node.ELEMENT_NODE && n.tagName !== 'SCRIPT' && n.tagName !== 'STYLE') {
                        if (n.shadowRoot) out += textFrom(n.shadowRoot);
                        for (const c of n.childNodes) walk(c);
                    }
                };
                for (const c of el.childNodes) walk(c);
                return out || (el.innerText || el.textContent || '');
            }
            return textFrom(root).replace(/\\s+/g, ' ').trim();
        }
        """

    try:
        text = await page.evaluate(_get_text_script())
        return (text or "").strip()[:200_000]
    except Exception as e:
        logger.debug("Primo fulldisplay extract script failed: %s", e)
        try:
            raw = await page.evaluate("() => document.body.innerText || ''")
            return re.sub(r"\s+", " ", (raw or "").strip())[:200_000]
        except Exception:
            return ""


# Primo results pagination: "Next" button / link (various UIs)
PRIMO_NEXT_PAGE_SELECTORS = [
    'button[aria-label*="Next" i]',
    'a[aria-label*="Next" i]',
    '[role="button"]:has-text("Next")',
    'button:has-text("Next")',
    'a:has-text("Next")',
    'prm-pagination button:has-text("Next")',
    '.pagination-next',
    '[class*="pagination"] a[rel="next"]',
]
# Max result pages to crawl (avoid infinite loop)
MAX_SEARCH_RESULT_PAGES = 50


def _next_offset_url(current_url: str, page_size: int = 10) -> str | None:
    """Return URL for next page by incrementing offset param, or None if not applicable."""
    parsed = urlparse(current_url)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    if "offset" not in qs:
        qs["offset"] = [str(page_size)]
    else:
        try:
            cur = int(qs["offset"][0])
            qs["offset"] = [str(cur + page_size)]
        except (ValueError, IndexError):
            return None
    new_query = urlencode(qs, doseq=True)
    new = parsed._replace(query=new_query)
    return urlunparse(new)


async def _click_next_results_page(page: Page, polite_delay_ms: int) -> bool:
    """Click Primo 'Next' to go to next results page, or navigate by offset. Returns True if navigated."""
    for sel in PRIMO_NEXT_PAGE_SELECTORS:
        try:
            loc = page.locator(sel).first
            if await loc.count() == 0:
                continue
            if not await loc.is_visible():
                continue
            # Disabled = no next page
            disabled = await loc.get_attribute("disabled")
            if disabled is not None:
                continue
            aria_disabled = await loc.get_attribute("aria-disabled")
            if (aria_disabled or "").lower() == "true":
                continue
            await loc.scroll_into_view_if_needed()
            await asyncio.sleep(200 / 1000)
            await loc.click()
            await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(max(1.0, polite_delay_ms / 1000))
            try:
                await page.wait_for_selector(
                    f"{PRIMO_RESULT_ITEM}, {PRIMO_FULLDISPLAY_LINK}",
                    timeout=12_000,
                )
            except Exception:
                pass
            return True
        except Exception as e:
            logger.debug("Next page selector %s failed: %s", sel, e)
            continue
    # Fallback: navigate by offset (Primo uses offset=0, 10, 20, ...)
    try:
        next_url = _next_offset_url(page.url)
        if next_url and next_url != page.url:
            await page.goto(next_url, wait_until="domcontentloaded", timeout=20_000)
            await asyncio.sleep(max(1.0, polite_delay_ms / 1000))
            try:
                await page.wait_for_selector(
                    f"{PRIMO_RESULT_ITEM}, {PRIMO_FULLDISPLAY_LINK}",
                    timeout=12_000,
                )
            except Exception:
                pass
            return True
    except Exception as e:
        logger.debug("Offset-based next page failed: %s", e)
    return False


async def _do_sjsu_login(page: Page, sjsu_id: str, sjsu_password: str, polite_delay_ms: int) -> bool:
    """If we're on Access to SJSU Resources or Sign In, fill credentials and submit. Returns True if login was attempted."""
    try:
        await asyncio.sleep(1)
        content = await page.content()
        if "Access to SJSU Resources" not in content and "Sign In" not in content and "SJSU ID Number" not in content:
            return False
        # Click "SJSU Student and Employee Login" to get to Sign In form (if we're on the Access page)
        if "Access to SJSU Resources" in content:
            try:
                for role in ("button", "link"):
                    btn = page.get_by_role(role, name=re.compile(r"SJSU Student and Employee Login", re.I))
                    if await btn.count() > 0:
                        await btn.first.click()
                        await page.wait_for_load_state("domcontentloaded")
                        await asyncio.sleep(2)
                        break
            except Exception:
                pass
        # Fill Sign In form: SJSU ID Number and Password (SJSUOne Password)
        try:
            id_loc = page.get_by_label(re.compile(r"SJSU ID Number|ID", re.I))
            pw_loc = page.get_by_label(re.compile(r"Password|SJSUOne", re.I))
            if await id_loc.count() > 0 and await pw_loc.count() > 0:
                await id_loc.first.fill(sjsu_id)
                await pw_loc.first.fill(sjsu_password)
                await asyncio.sleep(polite_delay_ms / 1000)
                await page.get_by_role("button", name=re.compile(r"Sign in|Submit", re.I)).first.click()
                await page.wait_for_load_state("domcontentloaded")
                await asyncio.sleep(2)
                return True
        except Exception as e:
            logger.debug("SJSU Sign In form fill failed: %s", e)
        return False
    except Exception as e:
        logger.debug("SJSU login flow failed: %s", e)
        return False


def _is_license_link(text: str) -> bool:
    """Skip links that are just license/legal, not the resource access."""
    t = (text or "").strip().upper()
    return bool(
        "SHOW LICENSE" in t
        or t == "LICENSE"
        or "VIEW LICENSE" in t
        or "TERMS OF USE" in t
    )


def _get_full_text_availability_section(page: Page):
    """Locator for the Full text availability section (parent of the heading)."""
    return page.get_by_text("Full text availability", exact=False).locator("xpath=./..")


def _is_still_primo_fulldisplay(url: str) -> bool:
    """True if URL is still the Primo fulldisplay page (we have not reached the provider)."""
    return bool(url and "primo.exlibrisgroup.com" in url and "fulldisplay" in url)


def _is_duo_security_page(url: str) -> bool:
    """True if URL is Duo Security 2FA (automation cannot complete push/code)."""
    return bool(url and "duosecurity.com" in url)


async def _count_full_text_resource_links(page: Page) -> int:
    """Number of links in Full text availability section that are not SHOW LICENSE / License."""
    try:
        section = _get_full_text_availability_section(page)
        all_links = section.locator("a[href]")
        n = await all_links.count()
        count = 0
        for i in range(n):
            link = all_links.nth(i)
            try:
                text = await link.inner_text()
                if not _is_license_link(text):
                    count += 1
            except Exception:
                pass
        return count
    except Exception:
        return 0


async def _get_full_text_resource_hrefs(page: Page) -> list[str]:
    """Collect hrefs of non-LICENSE links in Full text availability section (for programmatic navigation)."""
    hrefs: list[str] = []
    try:
        section = _get_full_text_availability_section(page)
        for selector in ['a[href][target="_blank"]', 'a[href]']:
            all_links = section.locator(selector)
            n = await all_links.count()
            for i in range(n):
                link = all_links.nth(i)
                try:
                    text = await link.inner_text()
                    if _is_license_link(text):
                        continue
                    href = await link.get_attribute("href")
                    if href and href.strip() and not href.startswith("#"):
                        full = urljoin(page.url, href)
                        if full not in hrefs:
                            hrefs.append(full)
                except Exception:
                    continue
            if hrefs:
                break
        if not hrefs:
            good = section.locator("a[href]").filter(has_not_text=re.compile(r"SHOW\s+LICENSE|^License$", re.I))
            for i in range(await good.count()):
                try:
                    href = await good.nth(i).get_attribute("href")
                    if href and href.strip() and not href.startswith("#"):
                        full = urljoin(page.url, href)
                        if full not in hrefs:
                            hrefs.append(full)
                except Exception:
                    continue
    except Exception:
        pass
    return hrefs


async def _click_full_text_availability_link(page: Page, link_index: int = 0) -> tuple[Page | None, bool]:
    """
    On a Primo fulldisplay page, open the link_index-th resource link (O'Reilly, Springer, SAGE, etc.) in
    'Full text availability'. Skips "SHOW LICENSE". Prefers opening href in a new page (no reliance on click opening a tab).
    Returns (page_to_use_for_pdf, opened_new_tab). If we're still on Primo fulldisplay, returns (None, False).
    """
    try:
        ctx = page.context
        section = _get_full_text_availability_section(page)

        # Strategy 1: Open the resource href — prefer SAME tab so session/cookies survive redirect chain (login -> provider)
        hrefs = await _get_full_text_resource_hrefs(page)
        if link_index < len(hrefs):
            provider_url = hrefs[link_index]
            if _is_still_primo_fulldisplay(provider_url):
                logger.debug("Resource href is still Primo: %s", provider_url[:80])
            else:
                try:
                    logger.info("Opening provider URL (%d of %d): %s", link_index + 1, len(hrefs), provider_url[:80])
                    # Same-tab first: preserves session through Primo -> SJSU login -> provider redirects
                    await page.goto(provider_url, wait_until="load", timeout=25_000)
                    await asyncio.sleep(3)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=10_000)
                    except Exception:
                        pass
                    await asyncio.sleep(1)
                    if not _is_still_primo_fulldisplay(page.url):
                        logger.info("Reached provider in same tab: %s", page.url[:80])
                        return page, False
                except Exception as e:
                    logger.debug("Same-tab navigation to provider failed: %s", e)
                # Fallback: new tab (in case link requires new window)
                try:
                    new_page = await ctx.new_page()
                    await new_page.goto(provider_url, wait_until="load", timeout=25_000)
                    await asyncio.sleep(3)
                    try:
                        await new_page.wait_for_load_state("networkidle", timeout=8_000)
                    except Exception:
                        pass
                    await asyncio.sleep(1)
                    if not _is_still_primo_fulldisplay(new_page.url):
                        logger.info("Opened provider via new tab: %s", new_page.url[:80])
                        return new_page, True
                    await new_page.close()
                except Exception as e:
                    logger.debug("New-tab navigation to provider failed: %s", e)

        # Strategy 2: Click and rely on new tab or same-tab navigation
        for selector in ['a[href][target="_blank"]', 'a[href]']:
            all_links = section.locator(selector)
            n = await all_links.count()
            idx = 0
            for i in range(n):
                link = all_links.nth(i)
                try:
                    text = await link.inner_text()
                    if _is_license_link(text):
                        continue
                    if idx == link_index:
                        try:
                            async with ctx.expect_page(timeout=15_000) as popup_info:
                                await link.click()
                            new_page = await popup_info.value
                            await new_page.wait_for_load_state("domcontentloaded")
                            await asyncio.sleep(2)
                            if not _is_still_primo_fulldisplay(new_page.url):
                                logger.info("Opened provider page in new tab: %s", new_page.url[:80])
                                return new_page, True
                            await new_page.close()
                        except Exception:
                            await page.wait_for_load_state("domcontentloaded")
                            await asyncio.sleep(2)
                            if not _is_still_primo_fulldisplay(page.url):
                                logger.info("Navigated to provider in same tab: %s", page.url[:80])
                                return page, False
                            logger.debug("Still on Primo after click; link may not navigate to provider")
                        break
                    idx += 1
                except Exception:
                    continue
            else:
                continue
            break
        # Fallback: filter by "not SHOW LICENSE" and take link_index-th
        good_links = section.locator("a[href]").filter(has_not_text=re.compile(r"SHOW\s+LICENSE|^License$", re.I))
        if await good_links.count() > link_index:
            link = good_links.nth(link_index)
            try:
                async with ctx.expect_page(timeout=12_000) as popup_info:
                    await link.click()
                new_page = await popup_info.value
                await new_page.wait_for_load_state("domcontentloaded")
                await asyncio.sleep(2)
                if not _is_still_primo_fulldisplay(new_page.url):
                    return new_page, True
                await new_page.close()
            except Exception:
                await page.wait_for_load_state("domcontentloaded")
                await asyncio.sleep(2)
                if not _is_still_primo_fulldisplay(page.url):
                    return page, False

        # Fallback: link with text like "View full text", "Unlimited user access", "O'Reilly" (only for link_index 0)
        if link_index == 0:
            for name in [
                r"View full text",
                r"Unlimited\s+user\s+access",
                r"Unlimited User Access",
                r"O'Reilly",
                r"Get it",
                r"Full text",
                r"View Online",
            ]:
                loc = page.get_by_role("link", name=re.compile(name, re.I)).first
                if await loc.count() == 0:
                    loc = page.locator("a").filter(has_text=re.compile(name, re.I)).first
                if await loc.count() > 0:
                    try:
                        async with ctx.expect_page(timeout=12_000) as popup_info:
                            await loc.click()
                        new_page = await popup_info.value
                        await new_page.wait_for_load_state("domcontentloaded")
                        await asyncio.sleep(3)
                        if not _is_still_primo_fulldisplay(new_page.url):
                            return new_page, True
                        await new_page.close()
                    except Exception:
                        pass
                    await page.wait_for_load_state("domcontentloaded")
                    await asyncio.sleep(3)
                    if not _is_still_primo_fulldisplay(page.url):
                        return page, False

        # Fallback: ezproxy / login links
        if link_index == 0:
            for sel in ['a[href*="ezproxy"]', 'a[href*="login"]', '[class*="fulltext"] a', '[class*="availability"] a']:
                el = await page.query_selector(sel)
                if el:
                    await el.click()
                    await page.wait_for_load_state("domcontentloaded")
                    await asyncio.sleep(2)
                    if not _is_still_primo_fulldisplay(page.url):
                        return page, False
    except Exception as e:
        logger.debug("Click full-text link failed: %s", e)
    return None, False


async def _try_download_from_result(
    page: Page,
    result_url: str,
    download_dir: Path,
    polite_delay_ms: int,
    sjsu_id: str = "",
    sjsu_password: str = "",
    headless: bool = True,
) -> str:
    """Follow result link; optionally log in as SJSU; click Full text link; try to get PDF."""
    path = ""
    try:
        await page.goto(result_url, wait_until="domcontentloaded", timeout=20_000)
        await asyncio.sleep(polite_delay_ms / 1000)

        # If we have SJSU credentials and we hit a login page, log in
        if sjsu_id and sjsu_password:
            if await _do_sjsu_login(page, sjsu_id, sjsu_password, polite_delay_ms):
                await asyncio.sleep(1)

        # On fulldisplay, try each "Full text availability" resource link (O'Reilly, Springer, etc.) until we get a PDF
        doc_page: Page | None = page
        opened_new_tab = False
        num_links = 0
        is_fulldisplay = "fulldisplay" in result_url or "fulldisplay" in page.url
        if is_fulldisplay:
            num_links = await _count_full_text_resource_links(page)
            if num_links == 0:
                num_links = 1  # try once with fallbacks
                logger.debug("Full text availability section: no resource links found, trying fallbacks")
            else:
                logger.info("Full text availability: %d resource link(s) to try", num_links)
        else:
            num_links = 1  # crawl current page once for PDF
        link_index = 0
        while link_index < num_links:
            if is_fulldisplay:
                logger.info("Trying full-text resource link %d of %d", link_index + 1, num_links)
                doc_page, opened_new_tab = await _click_full_text_availability_link(page, link_index)
            else:
                doc_page, opened_new_tab = page, False
            await asyncio.sleep(polite_delay_ms / 1000)
            if doc_page is None:
                if is_fulldisplay:
                    logger.info(
                        "Did not reach provider page (still on Primo); trying PDF on fulldisplay page",
                    )
                    doc_page = page
                else:
                    link_index += 1
                    continue
            # Duo Security 2FA — in headless mode we skip; in visible browser we wait for user to approve
            if _is_duo_security_page(doc_page.url):
                if headless:
                    logger.info("Duo 2FA required; cannot automate in headless mode. Skipping PDF for this result.")
                    if opened_new_tab and doc_page != page:
                        await doc_page.close()
                    link_index += 1
                    continue
                logger.info("Duo 2FA detected. Approve the push on your phone. Waiting up to 90 seconds...")
                for _ in range(45):
                    await asyncio.sleep(2)
                    if not _is_duo_security_page(doc_page.url):
                        logger.info("Duo completed; continuing with PDF search.")
                        break
                else:
                    logger.info("Duo 2FA not completed in time; skipping PDF for this result.")
                    if opened_new_tab and doc_page != page:
                        await doc_page.close()
                    link_index += 1
                    continue
            # Provider tab may show SJSU login; log in there too if we have credentials
            if sjsu_id and sjsu_password and doc_page:
                if await _do_sjsu_login(doc_page, sjsu_id, sjsu_password, polite_delay_ms):
                    await asyncio.sleep(1)
            # Login may redirect to Duo — wait for user to complete if browser is visible
            if _is_duo_security_page(doc_page.url):
                if headless:
                    logger.info("Duo 2FA required after login; cannot automate in headless mode. Skipping PDF.")
                    if opened_new_tab and doc_page != page:
                        await doc_page.close()
                    link_index += 1
                    continue
                logger.info("Duo 2FA detected. Approve the push on your phone. Waiting up to 90 seconds...")
                for _ in range(45):
                    await asyncio.sleep(2)
                    if not _is_duo_security_page(doc_page.url):
                        logger.info("Duo completed; continuing with PDF search.")
                        break
                else:
                    logger.info("Duo 2FA not completed in time; skipping PDF for this result.")
                    if opened_new_tab and doc_page != page:
                        await doc_page.close()
                    link_index += 1
                    continue
            try:
                base_url = doc_page.url
                logger.info("Document page URL: %s", base_url)
                # Let provider page render (SPA/redirects) before looking for PDFs
                try:
                    await doc_page.wait_for_load_state("domcontentloaded")
                    await asyncio.sleep(1.5)
                except Exception:
                    pass
                # Direct PDF link on page — use browser request so cookies/session are sent
                pdf_links = await doc_page.query_selector_all('a[href$=".pdf"], a[href*=".pdf?"]')
                for a in pdf_links:
                    href = await a.get_attribute("href")
                    if not href:
                        continue
                    full_url = urljoin(base_url, href)
                    try:
                        response = await doc_page.request.get(full_url, timeout=30_000)
                        if response and response.status == 200:
                            ct = (response.headers.get("content-type") or "").lower()
                            if "pdf" in ct or full_url.lower().endswith(".pdf"):
                                name = Path(urlparse(full_url).path).name or "document.pdf"
                                safe = re.sub(r'[<>:"/\\|?*]', "_", name)[:120]
                                dest = download_dir / safe
                                dest.write_bytes(await response.body())
                                path = str(dest)
                                logger.info("Downloaded PDF: %s", dest.name)
                                break
                        if response and response.status != 200:
                            logger.debug("PDF URL returned %s: %s", response.status, full_url)
                    except Exception as e:
                        logger.debug("Download %s failed: %s", full_url, e)
                if not path and pdf_links:
                    logger.info("No PDF content from .pdf link(s) (possible login or redirect)")

                # Text links: "PDF", "Full text", "Download", etc. — use browser request so cookies are sent
                if not path:
                    for label in ["PDF", "Full text", "Download", "View PDF", "Download PDF", "Save as PDF"]:
                        try:
                            lnk = doc_page.get_by_role("link", name=re.compile(re.escape(label), re.I))
                            if await lnk.count() > 0:
                                href = await lnk.first.get_attribute("href")
                                if href:
                                    full_url = urljoin(base_url, href)
                                    try:
                                        response = await doc_page.request.get(full_url, timeout=30_000)
                                        if response and response.status == 200:
                                            ct = (response.headers.get("content-type") or "").lower()
                                            if "pdf" in ct:
                                                name = Path(urlparse(full_url).path).name or "document.pdf"
                                                safe = re.sub(r'[<>:"/\\|?*]', "_", name)[:120]
                                                dest = download_dir / safe
                                                dest.write_bytes(await response.body())
                                                path = str(dest)
                                                logger.info("Downloaded PDF via '%s' link: %s", label, dest.name)
                                                break
                                    except Exception as e:
                                        logger.debug("Fetch %s link failed: %s", label, e)
                        except Exception:
                            continue
                # Button (e.g. "Download PDF" as button)
                if not path:
                    try:
                        btn = doc_page.get_by_role("button", name=re.compile(r"Download|PDF|Save", re.I)).first
                        if await btn.count() > 0:
                            async with doc_page.context.expect_download(timeout=15_000) as dl_info:
                                await btn.click()
                            download = await dl_info.value
                            save_name = download.suggested_filename or "document.pdf"
                            save_path = download_dir / re.sub(r'[<>:"/\\|?*]', "_", save_name)[:120]
                            await download.save_as(save_path)
                            path = str(save_path)
                    except Exception:
                        pass
                if not path:
                    if _is_duo_security_page(doc_page.url):
                        logger.info("Stopped at Duo 2FA page; cannot proceed without manual authentication")
                    else:
                        logger.info("No PDF or download link found on document page (provider may require in-browser read only)")
            finally:
                if opened_new_tab and doc_page and doc_page != page:
                    await doc_page.close()
            if path:
                break
            link_index += 1
    except Exception as e:
        logger.warning("try_download_from_result failed for %s: %s", result_url, e)
    return path


async def run_search(
    config: Config,
    query: str,
    search_type: str = "OneSearch",
    scope: str = "",
    download_dir_path: str = "",
    no_db: bool = False,
    advanced: bool = False,
    material_types: list[str] | None = None,
    full_content: bool = False,
) -> list[SearchResultRecord]:
    """
    OneSearch (Primo): navigate to Primo, fill "Search anything", submit, extract results.
    Optionally download PDFs into download_dir (under output/).
    Writes output/search_<query>.json when no_db or Postgres disabled; else only Postgres.
    Spec says: "Writes output/search_<query>.json when Postgres disabled or --no-db."
    So we always write JSON when --no-db; when Postgres enabled and not --no-db we can still write JSON (spec says "Search JSON: Writes output/search_<query>.json when Postgres disabled or --no-db") so only write JSON when no_db or not postgres.
    """
    # Keep query string intact (vid=, lang=) — only strip trailing slash if no "?"
    primo_url = config.primo_search_url.rstrip("/") if "?" in config.primo_search_url else config.primo_search_url.strip("/")
    records: list[SearchResultRecord] = []
    write_json = no_db or not config.postgres.enabled
    out_path = search_json_path(query) if write_json else None
    download_dir: Path | None = None
    if download_dir_path:
        download_dir = download_dir_for(download_dir_path)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=config.headless)
        ctx_opts: dict = {"ignore_https_errors": True} if config.ignore_https_errors else {}
        # Primo is a heavy SPA; use a real viewport so it renders and doesn't block headless
        ctx_opts.setdefault("viewport", {"width": 1280, "height": 720})
        context = await browser.new_context(**ctx_opts)
        page = await context.new_page()

        try:
            # Try Primo URL first — wait for load (SPA needs more than domcontentloaded)
            await page.goto(primo_url, wait_until="load", timeout=45_000)
            await asyncio.sleep(max(2.0, config.polite_delay_ms / 1000))
            # Let Primo SPA finish bootstrapping (XHR/config)
            try:
                await page.wait_for_load_state("networkidle", timeout=8_000)
            except Exception:
                pass
            await asyncio.sleep(1)

            if advanced:
                # Advanced search: retry up to 3 times (form can load slowly)
                types_list = list(material_types) if material_types else []
                logger.info("Using advanced search (material types: %s)", types_list or "none")
                advanced_ok = False
                for attempt in range(3):
                    if attempt > 0:
                        logger.info("Advanced search retry %d/3", attempt + 1)
                        await asyncio.sleep(2)
                    if await _do_advanced_search(
                        page, query, scope, types_list, primo_url, config.polite_delay_ms
                    ):
                        advanced_ok = True
                        break
                if not advanced_ok:
                    logger.warning("Advanced search failed after 3 attempts; falling back to simple search")
                    advanced = False
            if not advanced:
                search_el = await _find_primo_search_input(page, timeout_ms=8_000)
                used_library_homepage = False

                # Fallback: library homepage OneSearch bar (e.g. library.sjsu.edu) then submit to Primo
                if not search_el:
                    logger.info("Primo search input not found; trying library homepage %s", config.library_base_url)
                    search_el = await _find_library_homepage_search(page, config.library_base_url)
                    if search_el:
                        logger.info("Using library homepage OneSearch bar")
                        used_library_homepage = True
                    else:
                        logger.error(
                            "Search input not found on Primo page or library homepage (tried selectors and iframes).",
                        )
                        if write_json and out_path:
                            out_path.parent.mkdir(parents=True, exist_ok=True)
                            with open(out_path, "w", encoding="utf-8") as f:
                                json.dump([], f, indent=2)
                        return records

                await search_el.fill(query)
                await asyncio.sleep(300 / 1000)

                # Optional: set scope dropdown (e.g. "San Jose State Collections") — only on Primo page
                if scope and not used_library_homepage:
                    try:
                        await page.get_by_role("combobox").first.click()
                        await asyncio.sleep(200 / 1000)
                        await page.get_by_text(scope, exact=False).first.click()
                        await asyncio.sleep(200 / 1000)
                    except Exception as e:
                        logger.debug("Scope dropdown failed: %s", e)

                # Submit: Enter
                await search_el.press("Enter")
                await page.wait_for_load_state("domcontentloaded")
                if used_library_homepage:
                    try:
                        await page.wait_for_url("*primo*", timeout=15_000)
                    except Exception:
                        pass
            await asyncio.sleep(2)
            # Wait for results
            try:
                await page.wait_for_selector(
                    f"{PRIMO_RESULT_ITEM}, {PRIMO_FULLDISPLAY_LINK}",
                    timeout=15_000,
                )
            except Exception:
                pass

            # First page only: extract results, then follow each result link to get document/PDF
            records = await _extract_primo_results(page, query, search_type, scope)
            if records:
                logger.info("First page: %d results (following links to download documents when --download-dir set)", len(records))

            # Optional: visit each result URL and scrape full page content (Primo fulldisplay / catalog record)
            if full_content and records:
                logger.info("Fetching full content for %d results (visiting each link)", len(records))
                content_page = await context.new_page()
                for i, rec in enumerate(records):
                    try:
                        await content_page.goto(rec.url, wait_until="load", timeout=25_000)
                        await asyncio.sleep(max(2.0, config.polite_delay_ms / 1000))
                        try:
                            await content_page.wait_for_load_state("networkidle", timeout=8_000)
                        except Exception:
                            pass
                        await asyncio.sleep(1)
                        # Primo fulldisplay is an SPA; use Primo-specific extraction (handles shadow DOM)
                        full_text = await _extract_primo_fulldisplay_content(content_page)
                        if full_text:
                            rec.full_text = full_text
                        else:
                            page_record = await extract(content_page, rec.url, None, 0)
                            rec.full_text = (page_record.full_text or "").strip()
                            if page_record.title and not rec.title:
                                rec.title = page_record.title
                    except Exception as e:
                        logger.warning("Full content extraction failed for %s: %s", rec.url, e)
                        rec.status = "error"
                        rec.error_msg = str(e)[:500]
                    if (i + 1) % 5 == 0:
                        await asyncio.sleep(config.polite_delay_ms / 1000)
                await content_page.close()

            if not download_dir:
                logger.info(
                    "PDF download skipped. Pass --download-dir <dir> (e.g. search_pdfs) to download articles/PDFs.",
                )
            elif records:
                logger.info("Downloading PDFs to %s (%d results)", download_dir, len(records))

            # Optional: download PDFs for each result
            if download_dir and records:
                for i, rec in enumerate(records):
                    try:
                        path = await _try_download_from_result(
                            page,
                            rec.url,
                            download_dir,
                            config.polite_delay_ms,
                            sjsu_id=config.sjsu_login.id if config.sjsu_login else "",
                            sjsu_password=config.sjsu_login.password if config.sjsu_login else "",
                            headless=config.headless,
                        )
                        if path:
                            rec.download_path = path
                    except Exception as e:
                        logger.debug("Download for result %s failed: %s", rec.url, e)
                    if (i + 1) % 5 == 0:
                        await asyncio.sleep(config.polite_delay_ms / 1000)

        finally:
            if not config.headless:
                await asyncio.sleep(2)
            await browser.close()

    if not records:
        logger.warning("No records found for query '%s'", query)

    # Write JSON when Postgres disabled or --no-db
    if write_json and out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump([r.to_dict() for r in records], f, ensure_ascii=False, indent=2)
        logger.info("Wrote %s (%d results)", out_path, len(records))

    # Postgres
    if config.postgres.enabled and not no_db and records:
        import asyncpg
        conn = await asyncpg.connect(config.postgres.url)
        await init_schema(conn)
        try:
            for r in records:
                try:
                    await upsert_search_result(conn, r)
                except Exception as e:
                    logger.exception("upsert_search_result failed for %s: %s", r.url, e)
        finally:
            await conn.close()
        logger.info("Upserted %d results to library_search_results", len(records))

    return records
