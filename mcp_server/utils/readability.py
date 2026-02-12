"""JavaScript-based content extraction via Playwright.

Runs extraction logic *inside* the browser so it can capture:
- JavaScript-rendered content (SPAs, dynamic pages)
- Lazy-loaded text that appears after scroll/interaction
- Content behind client-side routing

Provides a simplified Readability-like algorithm executed via page.evaluate().
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JavaScript extraction script
# ---------------------------------------------------------------------------

# This is a self-contained Readability-inspired script that runs in the
# browser context.  It scores DOM nodes and extracts the most likely
# article/main-content container, returning structured data.
_READABILITY_JS = """
() => {
    // --- Helpers ---
    const BLOCK_TAGS = new Set([
        'p','div','article','section','main','blockquote','pre',
        'h1','h2','h3','h4','h5','h6','ul','ol','li','table',
        'figure','figcaption','details','summary'
    ]);

    const NEGATIVE_RE = /combx|comment|com-|contact|foot|footer|footnote|masthead|media|meta|outbrain|promo|related|scroll|shoutbox|sidebar|sponsor|shopping|tags|tool|widget|nav|menu|breadcrumb|crumb|popup|modal|overlay|cookie|consent|newsletter|subscribe|signup/i;
    const POSITIVE_RE = /article|body|content|entry|hentry|h-entry|main|page|pagination|post|text|blog|story|paragraph|prose/i;
    const AD_RE = /\\b(?:ad|ads|advert|advertisement|adsense|ad-slot|ad-wrapper|banner-ad|sponsored|tracking|tracker|social-share|share-buttons|cookie-banner|cookie-notice)\\b/i;

    function getClassId(el) {
        return ((el.className || '') + ' ' + (el.id || '')).trim();
    }

    function textLength(el) {
        return (el.textContent || '').trim().length;
    }

    function linkDensity(el) {
        const tl = textLength(el);
        if (tl === 0) return 1;
        let linkLen = 0;
        el.querySelectorAll('a').forEach(a => { linkLen += textLength(a); });
        return linkLen / tl;
    }

    function countParagraphs(el) {
        let count = 0;
        el.querySelectorAll('p').forEach(p => {
            if (textLength(p) >= 20) count++;
        });
        return count;
    }

    // --- Remove noise ---
    function removeNoise(root) {
        const removeTags = ['script','style','noscript','iframe','svg'];
        removeTags.forEach(tag => {
            root.querySelectorAll(tag).forEach(el => el.remove());
        });

        // Remove hidden elements
        root.querySelectorAll('[aria-hidden="true"]').forEach(el => el.remove());
        root.querySelectorAll('[style*="display:none"], [style*="display: none"]')
            .forEach(el => el.remove());
        root.querySelectorAll('[style*="visibility:hidden"], [style*="visibility: hidden"]')
            .forEach(el => el.remove());

        // Remove nav/footer/aside/header if they match negative patterns
        ['header','footer','nav','aside'].forEach(tag => {
            root.querySelectorAll(tag).forEach(el => el.remove());
        });

        // Remove ad/noise elements
        root.querySelectorAll('*').forEach(el => {
            const ci = getClassId(el);
            if (ci && AD_RE.test(ci)) {
                el.remove();
            }
        });
    }

    // --- Score candidates ---
    function scoreCandidates(root) {
        const candidates = new Map();
        const paragraphs = root.querySelectorAll('p');

        paragraphs.forEach(p => {
            const txt = (p.textContent || '').trim();
            if (txt.length < 25) return;

            let parent = p.parentElement;
            let grandparent = parent ? parent.parentElement : null;

            [parent, grandparent].forEach((ancestor, level) => {
                if (!ancestor) return;
                if (!candidates.has(ancestor)) {
                    candidates.set(ancestor, { score: 0, el: ancestor });
                    // Base score from class/id
                    const ci = getClassId(ancestor);
                    if (POSITIVE_RE.test(ci)) candidates.get(ancestor).score += 25;
                    if (NEGATIVE_RE.test(ci)) candidates.get(ancestor).score -= 25;
                    // Tag bonus
                    const tn = ancestor.tagName.toLowerCase();
                    if (tn === 'article' || tn === 'main') candidates.get(ancestor).score += 10;
                    // Role bonus
                    const role = (ancestor.getAttribute('role') || '').toLowerCase();
                    if (role === 'main' || role === 'article') candidates.get(ancestor).score += 15;
                }
                const cand = candidates.get(ancestor);
                // Score based on text length
                let contentScore = 1;
                contentScore += Math.min(Math.floor(txt.length / 100), 3);
                // Comma bonus
                contentScore += (txt.match(/,/g) || []).length;
                cand.score += (level === 0) ? contentScore : contentScore / 2;
            });
        });

        // Adjust scores based on link density
        candidates.forEach(cand => {
            const ld = linkDensity(cand.el);
            cand.score *= (1 - ld);
        });

        return candidates;
    }

    // --- Extract metadata ---
    function extractMetadata() {
        const meta = {};
        // Title
        const ogTitle = document.querySelector('meta[property="og:title"]');
        meta.title = (ogTitle && ogTitle.content) || document.title || '';

        // Description
        const desc = document.querySelector('meta[name="description"]') ||
                     document.querySelector('meta[property="og:description"]');
        meta.description = desc ? desc.content : '';

        // Author
        const author = document.querySelector('meta[name="author"]') ||
                        document.querySelector('[rel="author"]') ||
                        document.querySelector('.author') ||
                        document.querySelector('[itemprop="author"]');
        meta.author = author ? (author.content || author.textContent || '').trim() : '';

        // Published date
        const dateEl = document.querySelector('meta[property="article:published_time"]') ||
                        document.querySelector('time[datetime]') ||
                        document.querySelector('[itemprop="datePublished"]');
        if (dateEl) {
            meta.published_date = dateEl.content || dateEl.getAttribute('datetime') || dateEl.textContent || '';
        } else {
            meta.published_date = '';
        }

        // Canonical URL
        const canonical = document.querySelector('link[rel="canonical"]');
        meta.canonical_url = canonical ? canonical.href : window.location.href;

        // Language
        meta.language = document.documentElement.lang || '';

        // Site name
        const siteName = document.querySelector('meta[property="og:site_name"]');
        meta.site_name = siteName ? siteName.content : '';

        return meta;
    }

    // --- Main extraction ---
    try {
        // Clone the body so we don't modify the live DOM
        const clone = document.body.cloneNode(true);
        removeNoise(clone);

        // Check for semantic landmarks first
        let mainContent = clone.querySelector('main') ||
                          clone.querySelector('[role="main"]') ||
                          clone.querySelector('article') ||
                          clone.querySelector('[itemprop="articleBody"]');

        if (mainContent && textLength(mainContent) >= 50) {
            return {
                success: true,
                method: 'semantic_landmark',
                html: mainContent.innerHTML,
                text: mainContent.innerText,
                text_length: textLength(mainContent),
                metadata: extractMetadata(),
            };
        }

        // Score-based extraction
        const candidates = scoreCandidates(clone);
        let best = null;
        let bestScore = -Infinity;

        candidates.forEach(cand => {
            if (cand.score > bestScore) {
                bestScore = cand.score;
                best = cand;
            }
        });

        if (best && bestScore > 0 && textLength(best.el) >= 50) {
            return {
                success: true,
                method: 'scoring',
                score: bestScore,
                html: best.el.innerHTML,
                text: best.el.innerText,
                text_length: textLength(best.el),
                metadata: extractMetadata(),
            };
        }

        // Fallback: return cleaned body
        return {
            success: true,
            method: 'body_fallback',
            html: clone.innerHTML,
            text: clone.innerText,
            text_length: textLength(clone),
            metadata: extractMetadata(),
        };

    } catch(e) {
        return {
            success: false,
            error: e.message,
            metadata: extractMetadata(),
        };
    }
}
"""

# ---------------------------------------------------------------------------
# Scroll-and-wait script for lazy-loaded content
# ---------------------------------------------------------------------------

_SCROLL_TO_LOAD_JS = """
async () => {
    // Scroll down incrementally to trigger lazy loading
    const scrollStep = window.innerHeight;
    const maxScrolls = 5;
    let previousHeight = document.body.scrollHeight;

    for (let i = 0; i < maxScrolls; i++) {
        window.scrollBy(0, scrollStep);
        await new Promise(r => setTimeout(r, 500));
        const newHeight = document.body.scrollHeight;
        if (newHeight === previousHeight) break;
        previousHeight = newHeight;
    }

    // Scroll back to top
    window.scrollTo(0, 0);
    await new Promise(r => setTimeout(r, 300));

    return { scrolled: true };
}
"""

# ---------------------------------------------------------------------------
# Wait-for-content script
# ---------------------------------------------------------------------------

_WAIT_FOR_CONTENT_JS = """
async (timeoutMs) => {
    const start = Date.now();
    const minTextLength = 100;

    while (Date.now() - start < timeoutMs) {
        // Check if body has meaningful content
        const body = document.body;
        if (body) {
            const text = body.innerText || '';
            // Check for substantial text AND no loading indicators
            const loading = document.querySelector(
                '.loading, .spinner, [aria-busy="true"], .skeleton, .placeholder'
            );
            if (text.length >= minTextLength && !loading) {
                return { ready: true, text_length: text.length, waited_ms: Date.now() - start };
            }
        }
        await new Promise(r => setTimeout(r, 200));
    }

    const finalLength = (document.body && document.body.innerText) ?
                         document.body.innerText.length : 0;
    return { ready: finalLength >= minTextLength, text_length: finalLength, waited_ms: timeoutMs, timed_out: true };
}
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def extract_with_js(page) -> dict:
    """Extract content from the current page using JavaScript Readability.
    
    Args:
        page: Playwright Page object
    
    Returns:
        dict with keys: success, method, html, text, text_length, metadata
    """
    try:
        result = await page.evaluate(_READABILITY_JS)
        return result
    except Exception as e:
        logger.warning("JS-based extraction failed: %s", e)
        return {"success": False, "error": str(e)}


async def wait_for_content(page, timeout_ms: int = 5000) -> dict:
    """Wait for meaningful content to appear on the page.
    
    Watches for:
    - Minimum text length threshold
    - Disappearance of loading indicators (.loading, .spinner, [aria-busy])
    
    Args:
        page: Playwright Page object
        timeout_ms: Maximum time to wait in milliseconds
    
    Returns:
        dict with keys: ready, text_length, waited_ms, timed_out (optional)
    """
    try:
        result = await page.evaluate(_WAIT_FOR_CONTENT_JS, timeout_ms)
        return result
    except Exception as e:
        logger.warning("wait_for_content failed: %s", e)
        return {"ready": False, "error": str(e)}


async def scroll_to_load(page) -> dict:
    """Scroll down the page incrementally to trigger lazy-loaded content.
    
    Scrolls in viewport-height increments (up to 5x) and returns to top.
    
    Args:
        page: Playwright Page object
    
    Returns:
        dict with key: scrolled
    """
    try:
        result = await page.evaluate(_SCROLL_TO_LOAD_JS)
        return result
    except Exception as e:
        logger.warning("scroll_to_load failed: %s", e)
        return {"scrolled": False, "error": str(e)}


async def extract_metadata_only(page) -> dict:
    """Extract just the page metadata without content.
    
    Returns: title, description, author, published_date, canonical_url,
             language, site_name.
    """
    try:
        result = await page.evaluate("""
            () => {
                const meta = {};
                const ogTitle = document.querySelector('meta[property="og:title"]');
                meta.title = (ogTitle && ogTitle.content) || document.title || '';

                const desc = document.querySelector('meta[name="description"]') ||
                             document.querySelector('meta[property="og:description"]');
                meta.description = desc ? desc.content : '';

                const author = document.querySelector('meta[name="author"]') ||
                                document.querySelector('[rel="author"]') ||
                                document.querySelector('.author') ||
                                document.querySelector('[itemprop="author"]');
                meta.author = author ? (author.content || author.textContent || '').trim() : '';

                const dateEl = document.querySelector('meta[property="article:published_time"]') ||
                                document.querySelector('time[datetime]') ||
                                document.querySelector('[itemprop="datePublished"]');
                meta.published_date = dateEl ?
                    (dateEl.content || dateEl.getAttribute('datetime') || dateEl.textContent || '') : '';

                const canonical = document.querySelector('link[rel="canonical"]');
                meta.canonical_url = canonical ? canonical.href : window.location.href;

                meta.language = document.documentElement.lang || '';

                const siteName = document.querySelector('meta[property="og:site_name"]');
                meta.site_name = siteName ? siteName.content : '';

                return meta;
            }
        """)
        return result
    except Exception as e:
        logger.warning("extract_metadata_only failed: %s", e)
        return {}
