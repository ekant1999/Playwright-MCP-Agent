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
#
# IMPORTANT: Does NOT short-circuit on semantic landmarks — always runs the
# scoring algorithm and compares the semantic match against scored candidates,
# picking whichever has more content.  This prevents returning a summary
# section when a larger article body exists elsewhere.
_READABILITY_JS = """
() => {
    // --- Helpers ---
    const BLOCK_TAGS = new Set([
        'p','div','article','section','main','blockquote','pre',
        'h1','h2','h3','h4','h5','h6','ul','ol','li','table',
        'figure','figcaption','details','summary'
    ]);

    // Use word-boundary \b for short/ambiguous terms to avoid false positives
    // (e.g. "navigate"→"nav", "metadata"→"meta", "loading"→no match)
    const NEGATIVE_RE = /combx|comment|contact|foot|footer|footnote|masthead|outbrain|promo|related|shoutbox|sidebar|sponsor|shopping|breadcrumb|crumb|pagination|pager|popup|modal|overlay|cookie|consent|newsletter|subscribe|signup|\bnav\b|\bmenu\b/i;
    const POSITIVE_RE = /article|body|content|entry|hentry|h-entry|main|page|pagination|post|text|blog|story|paragraph|prose/i;
    const AD_RE = /\\b(?:ad|ads|advert|advertisement|adsense|ad-slot|ad-wrapper|banner-ad|sponsored|tracking|tracker|social-share|share-buttons|cookie-banner|cookie-notice)\\b/i;

    function getClassId(el) {
        // el.className can be an SVGAnimatedString for SVG elements,
        // so always use getAttribute('class') which returns a plain string.
        const cls = el.getAttribute('class') || '';
        return (cls + ' ' + (el.id || '')).trim();
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
        // Count all meaningful text blocks, not just <p>.
        // Weather, product, and data pages use tables/lists instead.
        let count = 0;
        el.querySelectorAll('p, li, td, th, dd, dt, blockquote').forEach(b => {
            if (textLength(b) >= 15) count++;
        });
        return count;
    }

    // --- Remove noise ---
    function removeNoise(root) {
        const removeTags = ['script','style','noscript','iframe','svg'];
        removeTags.forEach(tag => {
            root.querySelectorAll(tag).forEach(el => el.remove());
        });

        // Remove hidden elements — BUT preserve content-heavy ones.
        // "Read More" collapses, expandable sections, and accordion content
        // are often hidden via display:none but contain the FULL article text.
        // Only remove hidden elements with very little text (<80 chars),
        // which are typically decorative (icons, tooltips, modals with buttons).
        root.querySelectorAll('[aria-hidden="true"]').forEach(el => {
            const textLen = (el.textContent || '').trim().length;
            if (textLen > 80) return; // Keep text-heavy hidden blocks
            el.remove();
        });
        root.querySelectorAll('[style*="display:none"], [style*="display: none"]')
            .forEach(el => {
                const textLen = (el.textContent || '').trim().length;
                if (textLen > 80) return; // Keep "Read More" collapsed content
                el.remove();
            });
        root.querySelectorAll('[style*="visibility:hidden"], [style*="visibility: hidden"]')
            .forEach(el => {
                const textLen = (el.textContent || '').trim().length;
                if (textLen > 80) return;
                el.remove();
            });

        // Remove nav/footer/aside — but NOT headers inside <article>
        // (article headers contain title, author, date)
        ['footer','nav','aside'].forEach(tag => {
            root.querySelectorAll(tag).forEach(el => el.remove());
        });
        // Only remove <header> if it's a page-level header (not inside article)
        root.querySelectorAll('header').forEach(el => {
            const parent = el.parentElement;
            if (!parent || (parent.tagName !== 'ARTICLE' &&
                            parent.tagName !== 'MAIN' &&
                            !parent.closest('article'))) {
                el.remove();
            }
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
    // Walk UP TO 5 ancestor levels from each paragraph.
    // This is critical for sites like MSN that inject ads between
    // article sections — the common ancestor wrapping all sections
    // may be 3-5 levels up from individual paragraphs.
    const MAX_ANCESTOR_LEVELS = 5;
    // Score contribution decreases for higher ancestors
    const LEVEL_WEIGHTS = [1, 0.5, 0.3, 0.2, 0.1];

    function scoreCandidates(root) {
        const candidates = new Map();

        // Score from MULTIPLE text-bearing element types, not just <p>.
        // This is critical for data-heavy pages (weather, product, forum)
        // where content lives in <td>, <li>, <dd>, <div>, <span>, etc.
        const TEXT_SELECTORS = 'p, li, td, th, dd, dt, blockquote, figcaption';
        const textElements = root.querySelectorAll(TEXT_SELECTORS);

        // Also find text-rich <div>/<section> with no block children
        // (these act as implicit paragraphs on many sites)
        root.querySelectorAll('div, section').forEach(el => {
            // Only count if this div/section has direct text (not just in children)
            const directText = Array.from(el.childNodes)
                .filter(n => n.nodeType === 3) // TEXT_NODE
                .map(n => n.textContent.trim())
                .join('');
            if (directText.length >= 25) {
                // Treat it like a text element for scoring
                textElements.length; // just to reference — we'll process below
            }
        });

        textElements.forEach(el => {
            const txt = (el.textContent || '').trim();
            if (txt.length < 20) return;  // lower threshold for table cells

            // Weight differently based on element type
            const tagName = el.tagName.toLowerCase();
            let elementWeight = 1.0;
            if (tagName === 'p') elementWeight = 1.0;
            else if (tagName === 'li') elementWeight = 0.7;
            else if (tagName === 'td' || tagName === 'th') elementWeight = 0.5;
            else if (tagName === 'dd' || tagName === 'dt') elementWeight = 0.6;
            else elementWeight = 0.4;

            // Walk up the tree collecting ancestors
            let ancestor = el.parentElement;
            for (let level = 0; level < MAX_ANCESTOR_LEVELS && ancestor; level++) {
                if (ancestor === root || ancestor.tagName === 'BODY' || ancestor.tagName === 'HTML') break;

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
                // Score based on text length, weighted by ancestor level + element type
                let contentScore = 1;
                contentScore += Math.min(Math.floor(txt.length / 100), 3);
                contentScore += (txt.match(/,/g) || []).length;
                const weight = (LEVEL_WEIGHTS[level] || 0.1) * elementWeight;
                cand.score += contentScore * weight;

                ancestor = ancestor.parentElement;
            }
        });

        // Adjust scores based on link density
        candidates.forEach(cand => {
            const ld = linkDensity(cand.el);
            cand.score *= (1 - ld);
        });

        return candidates;
    }

    // --- Ancestor expansion ---
    // After finding the best candidate, check if walking up 1-2 levels
    // captures significantly more article content (e.g., when ads split
    // the article across sibling containers).
    function expandCandidate(el) {
        if (!el || !el.parentElement) return el;

        let best = el;
        let bestParas = countParagraphs(el);
        let bestLen = textLength(el);

        let current = el;
        for (let i = 0; i < 3; i++) {
            const parent = current.parentElement;
            if (!parent || parent.tagName === 'BODY' || parent.tagName === 'HTML') break;

            const parentParas = countParagraphs(parent);
            const parentLen = textLength(parent);
            const parentLd = linkDensity(parent);
            const ci = getClassId(parent);

            // Stop if parent is clearly noise. Allow moderate link density (0.55)
            // so we can expand to a wrapper that includes article + ad siblings
            // (e.g. MSN injects sponsored blocks between article sections).
            if (NEGATIVE_RE.test(ci) || parentLd > 0.55) break;

            // Expand if parent has significantly more paragraphs
            // (indicates more article content beyond ads)
            if (parentParas > bestParas * 1.4 && parentLen > bestLen * 1.2) {
                best = parent;
                bestParas = parentParas;
                bestLen = parentLen;
            }

            current = parent;
        }

        return best;
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

        // --- Collect semantic landmark candidate ---
        let semanticEl = clone.querySelector('[itemprop="articleBody"]') ||
                         clone.querySelector('article') ||
                         clone.querySelector('[role="main"]') ||
                         clone.querySelector('main');
        let semanticLen = semanticEl ? textLength(semanticEl) : 0;

        // --- Scoring-based detection (always runs) ---
        const candidates = scoreCandidates(clone);
        let scoredEl = null;
        let scoredBest = -Infinity;

        candidates.forEach(cand => {
            if (cand.score > scoredBest) {
                scoredBest = cand.score;
                scoredEl = cand.el;
            }
        });

        let scoredLen = scoredEl ? textLength(scoredEl) : 0;

        // --- Try ancestor expansion on both candidates ---
        // This catches articles split by ads across sibling containers.
        if (semanticEl) {
            const expanded = expandCandidate(semanticEl);
            if (expanded !== semanticEl) {
                semanticEl = expanded;
                semanticLen = textLength(semanticEl);
            }
        }
        if (scoredEl) {
            const expanded = expandCandidate(scoredEl);
            if (expanded !== scoredEl) {
                scoredEl = expanded;
                scoredLen = textLength(scoredEl);
            }
        }

        // --- Pick the best: compare semantic vs scored ---
        // CRITICAL: Prefer the candidate with the MOST content when multiple
        // reasonable candidates exist. This avoids returning a short AI summary
        // box (e.g. "Summary / Details / Conclusion") instead of the full
        // article body (e.g. on Cybernews and similar sites).
        let bestEl = null;
        let method = 'body_fallback';

        const allCandidates = [];
        if (semanticEl && semanticLen >= 100) {
            allCandidates.push({ el: semanticEl, len: semanticLen, method: 'semantic_landmark' });
        }
        const sortedByScore = Array.from(candidates.entries())
            .map(([el, data]) => ({ el, score: data.score }))
            .filter(x => x.score > 0)
            .sort((a, b) => b.score - a.score)
            .slice(0, 5);
        sortedByScore.forEach(({ el }) => {
            const expanded = expandCandidate(el);
            const len = textLength(expanded);
            const ld = linkDensity(expanded);
            if (len >= 100 && ld <= 0.55) {
                allCandidates.push({ el: expanded, len, method: 'scoring' });
            }
        });

        const seen = new Set();
        const pool = allCandidates.filter(c => {
            if (seen.has(c.el)) return false;
            seen.add(c.el);
            return true;
        });

        if (pool.length > 0) {
            const bestByLength = pool.reduce((a, b) => a.len >= b.len ? a : b);
            const bestLen = bestByLength.len;
            // Prefer longest when it's clearly an article (>= 800 chars)
            // and beats others (avoids summary box with ~800 chars vs article with 5000+)
            if (bestLen >= 800) {
                bestEl = bestByLength.el;
                method = bestByLength.method;
            }
        }

        if (!bestEl) {
            if (scoredEl && scoredLen > semanticLen * 1.3 && scoredLen >= 200) {
                bestEl = scoredEl;
                method = 'scoring';
            } else if (semanticEl && semanticLen >= 200) {
                bestEl = semanticEl;
                method = 'semantic_landmark';
            } else if (scoredEl && scoredBest > 0 && scoredLen >= 50) {
                bestEl = scoredEl;
                method = 'scoring';
            } else if (semanticEl && semanticLen >= 50) {
                bestEl = semanticEl;
                method = 'semantic_landmark';
            }
        }

        if (bestEl) {
            // On sites like MSN, article body can be split into siblings with ads
            // in between. If our selection is modest length (600–3500 chars),
            // try merging in following siblings that look like article content.
            let outHtml = bestEl.innerHTML;
            let outText = (bestEl.textContent || '').replace(/\\s+/g, ' ').trim();
            const bestLen = outText.length;
            if (bestLen >= 600 && bestLen <= 3500 && bestEl.parentElement) {
                const parent = bestEl.parentElement;
                let foundSelf = false;
                for (const child of parent.children) {
                    if (child === bestEl) {
                        foundSelf = true;
                        continue;
                    }
                    if (!foundSelf) continue;
                    const len = textLength(child);
                    const ld = linkDensity(child);
                    const paras = countParagraphs(child);
                    const ci = getClassId(child);
                    if (NEGATIVE_RE.test(ci) || ld > 0.5 || len < 150 || paras < 1) continue;
                    outHtml += child.innerHTML;
                    outText += ' ' + (child.textContent || '').replace(/\\s+/g, ' ').trim();
                }
                if (outText.length > bestLen * 1.1) {
                    method = method + '+siblings';
                } else {
                    outHtml = bestEl.innerHTML;
                    outText = (bestEl.textContent || '').replace(/\\s+/g, ' ').trim();
                }
            }
            return {
                success: true,
                method: method,
                score: method === 'scoring' ? scoredBest : undefined,
                html: outHtml,
                text: outText.trim(),
                text_length: outText.trim().length,
                paragraph_count: countParagraphs(bestEl),
                metadata: extractMetadata(),
            };
        }

        // Fallback: return cleaned body
        const fallbackText = (clone.textContent || '').replace(/\\s+/g, ' ').trim();
        return {
            success: true,
            method: 'body_fallback',
            html: clone.innerHTML,
            text: fallbackText,
            text_length: fallbackText.length,
            paragraph_count: countParagraphs(clone),
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
    // Scroll down incrementally to trigger lazy loading.
    // Tracks BOTH scrollHeight growth AND innerText growth,
    // because some sites (MSN, Medium, etc.) load content into
    // pre-allocated containers without increasing scrollHeight.
    const scrollStep = window.innerHeight;
    const maxScrolls = 15;
    let previousHeight = document.body.scrollHeight;
    let previousTextLen = (document.body.innerText || '').length;
    let staleRounds = 0;     // rounds with no growth
    const maxStaleRounds = 3; // stop after 3 stale rounds in a row

    for (let i = 0; i < maxScrolls; i++) {
        window.scrollBy(0, scrollStep);
        // Wait for lazy content to render (800ms gives more time for
        // slow networks / heavy JS frameworks)
        await new Promise(r => setTimeout(r, 800));

        const newHeight = document.body.scrollHeight;
        const newTextLen = (document.body.innerText || '').length;

        // Check if EITHER scrollHeight or text content grew
        const heightGrew = newHeight > previousHeight;
        const textGrew = newTextLen > previousTextLen + 50; // 50 chars threshold

        if (!heightGrew && !textGrew) {
            staleRounds++;
            if (staleRounds >= maxStaleRounds) break;
        } else {
            staleRounds = 0;
        }

        previousHeight = newHeight;
        previousTextLen = newTextLen;
    }

    // Scroll back to top
    window.scrollTo(0, 0);
    await new Promise(r => setTimeout(r, 300));

    const finalTextLen = (document.body.innerText || '').length;
    return {
        scrolled: true,
        initial_text_length: previousTextLen,
        final_text_length: finalTextLen,
    };
}
"""

# ---------------------------------------------------------------------------
# Content stabilization wait script
# ---------------------------------------------------------------------------

# Instead of checking "does text.length exceed a threshold", this polls
# the page's text length multiple times.  It returns "ready" only when
# the text length has STOPPED GROWING for a stable window.  This ensures
# JS-hydrated content (Next.js, React, Vue) has finished rendering.

_WAIT_FOR_STABLE_CONTENT_JS = """
async (opts) => {
    const timeoutMs = opts.timeoutMs || 10000;
    const stableWindowMs = opts.stableWindowMs || 1500;
    const pollIntervalMs = opts.pollIntervalMs || 300;
    const minTextLength = opts.minTextLength || 100;

    const start = Date.now();
    let lastLength = 0;
    let stableSince = null;

    while (Date.now() - start < timeoutMs) {
        const body = document.body;
        if (!body) {
            await new Promise(r => setTimeout(r, pollIntervalMs));
            continue;
        }

        const currentLength = (body.innerText || '').length;

        // Check for Cloudflare / bot challenge pages
        const title = document.title || '';
        if (title === 'Just a moment...' ||
            title.includes('Attention Required') ||
            document.querySelector('#challenge-running, #cf-challenge-running, .cf-browser-verification')) {
            // On a challenge page — keep waiting, it may auto-resolve
            stableSince = null;
            lastLength = currentLength;
            await new Promise(r => setTimeout(r, pollIntervalMs));
            continue;
        }

        // Check for common loading indicators.
        // Use aria-busy as the primary signal (most reliable).
        // For class-based checks, verify the element is actually visible
        // and has loading-like EXACT classes to avoid false positives
        // (e.g. "loading-complete" should NOT match).
        const busyEl = document.querySelector('[aria-busy="true"]');
        let isLoading = !!busyEl;
        if (!isLoading) {
            const candidates = document.querySelectorAll(
                '.loading, .spinner, .skeleton, .placeholder'
            );
            for (const c of candidates) {
                // Only count if the element is visible (has dimensions)
                const rect = c.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) {
                    isLoading = true;
                    break;
                }
            }
        }
        if (isLoading) {
            // Page still loading — reset stability timer
            stableSince = null;
            lastLength = currentLength;
            await new Promise(r => setTimeout(r, pollIntervalMs));
            continue;
        }

        // Track stability: has the text length stopped changing?
        if (currentLength !== lastLength) {
            // Content still changing — reset stability timer
            stableSince = Date.now();
            lastLength = currentLength;
        } else if (stableSince === null) {
            stableSince = Date.now();
        }

        // Content is stable if it hasn't changed for stableWindowMs
        // AND has meaningful length
        if (stableSince &&
            (Date.now() - stableSince) >= stableWindowMs &&
            currentLength >= minTextLength) {
            return {
                ready: true,
                text_length: currentLength,
                waited_ms: Date.now() - start,
                stable_for_ms: Date.now() - stableSince,
            };
        }

        await new Promise(r => setTimeout(r, pollIntervalMs));
    }

    // Timed out — return current state
    const finalLength = (document.body && document.body.innerText) ?
                         document.body.innerText.length : 0;
    return {
        ready: finalLength >= minTextLength,
        text_length: finalLength,
        waited_ms: timeoutMs,
        timed_out: true,
    };
}
"""

# ---------------------------------------------------------------------------
# Cloudflare challenge detection + wait-through
# ---------------------------------------------------------------------------

_CLOUDFLARE_WAIT_JS = """
async (maxWaitMs) => {
    const start = Date.now();
    const pollMs = 500;

    while (Date.now() - start < maxWaitMs) {
        const title = (document.title || '').toLowerCase();
        const hasChallengeEl = !!document.querySelector(
            '#challenge-running, #cf-challenge-running, .cf-browser-verification, ' +
            '#challenge-stage, #turnstile-wrapper, [id*="challenge"]'
        );
        const bodyText = (document.body && document.body.innerText) || '';
        const isChallengeText = bodyText.includes('Checking your browser') ||
                                bodyText.includes('Just a moment') ||
                                bodyText.includes('Verify you are human') ||
                                bodyText.includes('Enable JavaScript and cookies');

        const isChallenge = title.includes('just a moment') ||
                           title.includes('attention required') ||
                           hasChallengeEl ||
                           isChallengeText;

        if (!isChallenge) {
            // Challenge resolved — page has real content now
            return {
                was_challenged: true,
                resolved: true,
                waited_ms: Date.now() - start,
                title: document.title,
            };
        }

        await new Promise(r => setTimeout(r, pollMs));
    }

    return {
        was_challenged: true,
        resolved: false,
        waited_ms: maxWaitMs,
        title: document.title,
    };
}
"""

_DETECT_CHALLENGE_JS = """
() => {
    const title = (document.title || '').toLowerCase();
    const hasChallengeEl = !!document.querySelector(
        '#challenge-running, #cf-challenge-running, .cf-browser-verification, ' +
        '#challenge-stage, #turnstile-wrapper, [id*="challenge"]'
    );
    const bodyText = (document.body && document.body.innerText) || '';
    const isChallengeText = bodyText.includes('Checking your browser') ||
                            bodyText.includes('Just a moment') ||
                            bodyText.includes('Verify you are human') ||
                            bodyText.includes('Enable JavaScript and cookies');

    return title.includes('just a moment') ||
           title.includes('attention required') ||
           hasChallengeEl ||
           isChallengeText;
}
"""

# ---------------------------------------------------------------------------
# Blocked / paywall / anti-bot page detection
# ---------------------------------------------------------------------------
# Detects pages that block content with paywalls, anti-bot walls, or
# ad-blocker detection — distinct from Cloudflare challenges (which may
# auto-resolve). These typically require user intervention.

_DETECT_BLOCKED_PAGE_JS = """
() => {
    const bodyText = (document.body && document.body.innerText) || '';
    const bodyLower = bodyText.toLowerCase();
    const title = (document.title || '').toLowerCase();
    const textLen = bodyText.trim().length;

    const signals = [];

    // Forbes-style: "Please enable JS and disable any ad blocker"
    if (bodyLower.includes('disable') && bodyLower.includes('ad blocker')) {
        signals.push('ad_blocker_wall');
    }

    // Generic paywall / subscription walls
    if (bodyLower.includes('subscribe to continue') ||
        bodyLower.includes('subscription required') ||
        bodyLower.includes('premium content') ||
        bodyLower.includes('members only') ||
        bodyLower.includes('sign in to read') ||
        bodyLower.includes('log in to continue') ||
        bodyLower.includes('create a free account')) {
        signals.push('paywall');
    }

    // Login walls
    if (textLen < 500 &&
        (bodyLower.includes('sign in') || bodyLower.includes('log in')) &&
        (bodyLower.includes('to continue') || bodyLower.includes('to read') ||
         bodyLower.includes('to access'))) {
        signals.push('login_wall');
    }

    // Very short page with "enable JavaScript" messages
    if (textLen < 200 &&
        (bodyLower.includes('enable javascript') ||
         bodyLower.includes('please enable js') ||
         bodyLower.includes('javascript is required'))) {
        signals.push('js_required');
    }

    // Cookie consent blocking content (full-page overlays)
    const consentOverlay = document.querySelector(
        '[class*="consent-wall"], [class*="cookie-wall"], ' +
        '[id*="consent-wall"], [class*="gdpr-blocker"]'
    );
    if (consentOverlay) {
        signals.push('consent_wall');
    }

    // Bot detection pages
    if (bodyLower.includes('bot detected') ||
        bodyLower.includes('automated access') ||
        bodyLower.includes('not a robot') ||
        bodyLower.includes('unusual traffic')) {
        signals.push('bot_detection');
    }

    return {
        is_blocked: signals.length > 0,
        signals: signals,
        page_text_length: textLen,
        title: document.title || '',
    };
}
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def extract_with_js(page) -> dict:
    """Extract content from the current page using JavaScript Readability.

    Always runs scoring AND semantic landmark detection, then picks
    whichever yields more content.  This prevents returning a summary
    container when a larger article body exists.

    Args:
        page: Playwright Page object

    Returns:
        dict with keys: success, method, html, text, text_length,
                        paragraph_count, metadata
    """
    try:
        result = await page.evaluate(_READABILITY_JS)
        return result
    except Exception as e:
        logger.warning("JS-based extraction failed: %s", e)
        return {"success": False, "error": str(e)}


async def wait_for_stable_content(page, timeout_ms: int = 10000,
                                  stable_window_ms: int = 1500) -> dict:
    """Wait for page content to STABILIZE (stop growing), not just appear.

    This is critical for JS-heavy sites (Next.js, React, Vue) where the
    initial server-rendered HTML is a skeleton/summary and the full
    content hydrates over several seconds.

    Strategy:
    - Polls document.body.innerText.length every 300ms
    - Only returns "ready" when text length hasn't changed for
      stable_window_ms (default 1.5s)
    - Also detects Cloudflare challenges and loading indicators

    Args:
        page: Playwright Page object
        timeout_ms: Maximum time to wait (default 10s)
        stable_window_ms: How long content must be stable before
                          considered "ready" (default 1.5s)

    Returns:
        dict with keys: ready, text_length, waited_ms, stable_for_ms,
                        timed_out (optional)
    """
    try:
        result = await page.evaluate(
            _WAIT_FOR_STABLE_CONTENT_JS,
            {
                "timeoutMs": timeout_ms,
                "stableWindowMs": stable_window_ms,
                "pollIntervalMs": 300,
                "minTextLength": 100,
            },
        )
        return result
    except Exception as e:
        logger.warning("wait_for_stable_content failed: %s", e)
        return {"ready": False, "error": str(e)}


async def detect_challenge(page) -> bool:
    """Detect if the current page is a Cloudflare/bot challenge.

    Returns True if the page appears to be a challenge/interstitial.
    """
    try:
        return await page.evaluate(_DETECT_CHALLENGE_JS)
    except Exception:
        return False


async def detect_blocked_page(page) -> dict:
    """Detect if the page is blocked by a paywall, ad-blocker wall, or login gate.

    Returns dict with:
        is_blocked: bool
        signals: list of detected block types
        page_text_length: int
        title: str
    """
    try:
        return await page.evaluate(_DETECT_BLOCKED_PAGE_JS)
    except Exception:
        return {"is_blocked": False, "signals": []}


async def wait_through_challenge(page, max_wait_ms: int = 20000) -> dict:
    """Wait for a Cloudflare/bot challenge to resolve.

    Polls every 500ms, checking if the challenge page has been replaced
    by real content.  Returns once the challenge resolves or times out.

    Args:
        page: Playwright Page object
        max_wait_ms: Maximum time to wait for challenge resolution

    Returns:
        dict with keys: was_challenged, resolved, waited_ms, title
    """
    try:
        result = await page.evaluate(_CLOUDFLARE_WAIT_JS, max_wait_ms)
        return result
    except Exception as e:
        logger.warning("wait_through_challenge failed: %s", e)
        return {"was_challenged": True, "resolved": False, "error": str(e)}


# Keep the old name as an alias for backward compatibility
async def wait_for_content(page, timeout_ms: int = 10000) -> dict:
    """Alias for wait_for_stable_content (backward compatible)."""
    return await wait_for_stable_content(page, timeout_ms=timeout_ms)


async def scroll_to_load(page) -> dict:
    """Scroll down the page incrementally to trigger lazy-loaded content.

    Scrolls in viewport-height increments (up to 8x) and returns to top.

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
