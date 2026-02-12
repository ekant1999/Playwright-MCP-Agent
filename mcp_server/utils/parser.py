"""HTML parsing and content extraction utilities.

Provides robust content extraction using:
- Readability-inspired scoring heuristics for main content detection
- Word-boundary-aware noise removal (ads, nav, sidebars)
- Rich markdown conversion with tables, code blocks, blockquotes, images
- Paragraph-aware plain-text conversion
"""

from __future__ import annotations

import re
import math
from typing import Optional
from bs4 import BeautifulSoup, Tag, NavigableString


# ---------------------------------------------------------------------------
# Constants for content scoring
# ---------------------------------------------------------------------------

# Positive indicators — elements/classes likely to hold main content
_POSITIVE_PATTERNS = re.compile(
    r"article|body|content|entry|hentry|h-entry|main|page|"
    r"pagination|post|text|blog|story|paragraph|prose",
    re.IGNORECASE,
)

# Negative indicators — elements/classes likely to be boilerplate
_NEGATIVE_PATTERNS = re.compile(
    r"combx|comment|com-|contact|foot|footer|footnote|masthead|media|meta|"
    r"outbrain|promo|related|scroll|shoutbox|sidebar|sponsor|shopping|"
    r"tags|tool|widget|nav|menu|breadcrumb|crumb|pagination|pager|"
    r"popup|modal|overlay|cookie|consent|newsletter|subscribe|signup",
    re.IGNORECASE,
)

# Elements whose content is boilerplate (always remove)
_BOILERPLATE_TAGS = {"script", "style", "noscript", "iframe", "svg", "form"}

# Structural elements to remove if they match negative patterns
_STRUCTURAL_NOISE_TAGS = {"header", "footer", "nav", "aside"}

# Ad/tracking patterns — matched as whole words to avoid false positives
# e.g. "ad" won't match "loading" or "heading"
_AD_WORD_PATTERNS = re.compile(
    r"\b(?:ad|ads|advert|advertisement|adsense|ad-slot|ad-wrapper|"
    r"banner-ad|sponsored|sponsor|tracking|tracker|"
    r"social-share|share-buttons|cookie-banner|cookie-notice|"
    r"newsletter-signup|popup-overlay)\b",
    re.IGNORECASE,
)

# Minimum content length thresholds
_MIN_CONTENT_LENGTH = 50  # characters for a valid content block
_MIN_PARAGRAPH_LENGTH = 20  # characters for scoring a paragraph


# ---------------------------------------------------------------------------
# Content scoring (Readability-inspired)
# ---------------------------------------------------------------------------

def _get_class_id_string(tag: Tag) -> str:
    """Get combined class + id string for pattern matching."""
    parts = []
    if tag.get("class"):
        parts.extend(tag["class"] if isinstance(tag["class"], list) else [tag["class"]])
    if tag.get("id"):
        parts.append(tag["id"])
    return " ".join(parts)


def _score_node(tag: Tag) -> float:
    """Score a node based on its likelihood of being main content.
    
    Higher scores indicate more likely to contain the main article content.
    Uses class/id pattern matching plus content density analysis.
    """
    score = 0.0
    class_id = _get_class_id_string(tag)

    # Tag name bonuses
    tag_scores = {
        "article": 10, "main": 10, "section": 3,
        "div": 0, "td": 1, "blockquote": 3,
    }
    score += tag_scores.get(tag.name, 0)

    # Class/id pattern bonuses
    if _POSITIVE_PATTERNS.search(class_id):
        score += 25
    if _NEGATIVE_PATTERNS.search(class_id):
        score -= 25

    # Role attribute bonus
    role = tag.get("role", "").lower()
    if role in ("main", "article"):
        score += 20
    elif role in ("navigation", "banner", "complementary", "contentinfo"):
        score -= 15

    # itemprop bonus (Schema.org)
    itemprop = tag.get("itemprop", "").lower()
    if itemprop in ("articlebody", "text", "description"):
        score += 15

    return score


def _calculate_content_density(tag: Tag) -> float:
    """Calculate the ratio of text content to total HTML in a node.
    
    Higher density suggests more actual content vs. markup/navigation.
    """
    text_length = len(tag.get_text(strip=True))
    html_length = len(str(tag))
    if html_length == 0:
        return 0.0
    return text_length / html_length


def _count_paragraphs(tag: Tag) -> int:
    """Count meaningful paragraphs (> minimum length) inside a tag."""
    count = 0
    for p in tag.find_all("p"):
        if len(p.get_text(strip=True)) >= _MIN_PARAGRAPH_LENGTH:
            count += 1
    return count


def _count_links_ratio(tag: Tag) -> float:
    """Calculate link text ratio — high ratio suggests navigation, not content."""
    text_length = len(tag.get_text(strip=True))
    if text_length == 0:
        return 1.0
    link_text = sum(len(a.get_text(strip=True)) for a in tag.find_all("a"))
    return link_text / text_length


def _score_candidate(tag: Tag) -> float:
    """Comprehensive score for a content candidate node."""
    base_score = _score_node(tag)
    
    # Paragraph count bonus (more paragraphs = more likely article)
    para_count = _count_paragraphs(tag)
    base_score += para_count * 3
    
    # Content density bonus
    density = _calculate_content_density(tag)
    base_score += density * 20
    
    # Link ratio penalty (navigation-heavy sections)
    link_ratio = _count_links_ratio(tag)
    if link_ratio > 0.5:
        base_score -= 30 * link_ratio
    
    # Text length bonus (logarithmic to avoid huge-page domination)
    text_length = len(tag.get_text(strip=True))
    if text_length > _MIN_CONTENT_LENGTH:
        base_score += math.log(text_length) * 2
    
    # Penalize very short content
    if text_length < _MIN_CONTENT_LENGTH:
        base_score -= 20
    
    return base_score


# ---------------------------------------------------------------------------
# Noise removal
# ---------------------------------------------------------------------------

def _is_noise_element(tag: Tag) -> bool:
    """Determine if a tag is a noise element that should be removed."""
    if not isinstance(tag, Tag):
        return False
    
    class_id = _get_class_id_string(tag)
    
    # Always remove boilerplate tags
    if tag.name in _BOILERPLATE_TAGS:
        return True
    
    # Remove structural noise tags (header/footer/nav/aside)
    if tag.name in _STRUCTURAL_NOISE_TAGS:
        return True
    
    # Remove elements matching ad word patterns (whole-word matching)
    if class_id and _AD_WORD_PATTERNS.search(class_id):
        return True
    
    # Remove elements with negative class/id patterns
    if class_id and _NEGATIVE_PATTERNS.search(class_id):
        # But only if they have low content density
        density = _calculate_content_density(tag)
        if density < 0.3:
            return True
    
    # Remove hidden elements
    style = tag.get("style", "")
    if "display:none" in style.replace(" ", "") or "visibility:hidden" in style.replace(" ", ""):
        return True
    
    # Remove aria-hidden elements
    if tag.get("aria-hidden") == "true":
        return True
    
    return False


def _clean_soup(soup: BeautifulSoup) -> BeautifulSoup:
    """Remove noise elements from the soup, preserving main content."""
    # First pass: remove definite boilerplate
    for tag in soup.find_all(_BOILERPLATE_TAGS):
        tag.decompose()
    
    # Second pass: remove noise elements by class/id/structure
    # Collect first, then remove (to avoid modifying during iteration)
    to_remove = []
    for tag in soup.find_all(True):
        if _is_noise_element(tag):
            to_remove.append(tag)
    
    for tag in to_remove:
        try:
            tag.decompose()
        except Exception:
            pass  # Already removed by parent decomposition
    
    return soup


# ---------------------------------------------------------------------------
# Main content extraction (public API)
# ---------------------------------------------------------------------------

def extract_main_content(html: str) -> str:
    """Extract main content from HTML using scoring heuristics.
    
    Strategy:
    1. Parse HTML and remove obvious noise
    2. Score candidate containers (article, main, section, div)
    3. Pick the highest-scoring candidate
    4. Fall back to <body> if no good candidate found
    
    Returns the inner HTML of the best content container.
    """
    soup = BeautifulSoup(html, "lxml")
    
    # Clean noise from the entire document
    soup = _clean_soup(soup)
    
    # --- Direct semantic match (highest priority) ---
    # Check for explicit main content landmarks first
    for finder in [
        lambda: soup.find("main"),
        lambda: soup.find(attrs={"role": "main"}),
        lambda: soup.find("article"),
        lambda: soup.find(attrs={"itemprop": "articleBody"}),
    ]:
        candidate = finder()
        if candidate and len(candidate.get_text(strip=True)) >= _MIN_CONTENT_LENGTH:
            return str(candidate)
    
    # --- Scoring-based detection ---
    # Collect all plausible container elements
    candidates: list[tuple[float, Tag]] = []
    for tag in soup.find_all(["div", "section", "td", "article", "main", "blockquote"]):
        text_length = len(tag.get_text(strip=True))
        if text_length < _MIN_CONTENT_LENGTH:
            continue
        score = _score_candidate(tag)
        candidates.append((score, tag))
    
    if candidates:
        # Sort by score descending
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_tag = candidates[0]
        
        # Only accept if score is reasonable
        if best_score > 0:
            return str(best_tag)
    
    # --- Fallback: return cleaned body ---
    body = soup.find("body")
    if body:
        return str(body)
    
    return str(soup)


# ---------------------------------------------------------------------------
# HTML → Plain Text
# ---------------------------------------------------------------------------

def html_to_text(html: str, preserve_links: bool = False) -> str:
    """Convert HTML to clean plain text with paragraph structure preserved.
    
    Args:
        html: HTML string to convert
        preserve_links: If True, render links as [text](url) format
    """
    soup = BeautifulSoup(html, "lxml")
    
    # Remove non-content elements
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    
    if preserve_links:
        for link in soup.find_all("a", href=True):
            text = link.get_text(strip=True)
            href = link["href"]
            if text and href:
                link.replace_with(f"[{text}]({href})")
    
    # Insert separators for block-level elements to preserve structure
    block_elements = [
        "p", "div", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6",
        "li", "tr", "blockquote", "pre", "table", "section", "article",
    ]
    for tag in soup.find_all(block_elements):
        tag.insert_before("\n")
        tag.insert_after("\n")
    
    # Get text
    text = soup.get_text()
    
    # Clean up whitespace while preserving paragraph breaks
    # Replace tabs and multiple spaces with single space
    text = re.sub(r"[^\S\n]+", " ", text)
    # Collapse 3+ newlines into 2 (paragraph break)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Strip leading/trailing whitespace per line
    lines = [line.strip() for line in text.splitlines()]
    # Remove completely empty consecutive lines beyond one
    cleaned: list[str] = []
    prev_empty = False
    for line in lines:
        if not line:
            if not prev_empty:
                cleaned.append("")
                prev_empty = True
        else:
            cleaned.append(line)
            prev_empty = False
    
    return "\n".join(cleaned).strip()


# ---------------------------------------------------------------------------
# HTML → Markdown
# ---------------------------------------------------------------------------

def html_to_markdown(html: str) -> str:
    """Convert HTML to well-formatted markdown.
    
    Supports: headings, paragraphs, links, bold/italic, code/pre blocks,
    ordered/unordered lists, tables, blockquotes, images, and horizontal rules.
    """
    soup = BeautifulSoup(html, "lxml")
    
    # Remove non-content elements
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    
    # Process the tree recursively
    result = _process_node(soup)
    
    # Final cleanup
    # Collapse excessive blank lines
    result = re.sub(r"\n{3,}", "\n\n", result)
    # Remove trailing whitespace per line
    result = "\n".join(line.rstrip() for line in result.splitlines())
    
    return result.strip()


def _process_node(node, depth: int = 0) -> str:
    """Recursively process a BeautifulSoup node into markdown."""
    if isinstance(node, NavigableString):
        text = str(node)
        # Collapse whitespace in inline text (but preserve intentional newlines in <pre>)
        if not _is_inside_pre(node):
            text = re.sub(r"[ \t]+", " ", text)
        return text
    
    if not isinstance(node, Tag):
        return ""
    
    tag_name = node.name.lower() if node.name else ""
    
    # --- Headings ---
    if tag_name in ("h1", "h2", "h3", "h4", "h5", "h6"):
        level = int(tag_name[1])
        text = _inline_text(node).strip()
        if text:
            return f"\n\n{'#' * level} {text}\n\n"
        return ""
    
    # --- Paragraphs ---
    if tag_name == "p":
        text = _inline_text(node).strip()
        if text:
            return f"\n\n{text}\n\n"
        return ""
    
    # --- Line breaks ---
    if tag_name == "br":
        return "\n"
    
    # --- Horizontal rule ---
    if tag_name == "hr":
        return "\n\n---\n\n"
    
    # --- Links ---
    if tag_name == "a":
        text = _inline_text(node).strip()
        href = node.get("href", "")
        if text and href and not href.startswith("javascript:"):
            return f"[{text}]({href})"
        return text
    
    # --- Bold ---
    if tag_name in ("b", "strong"):
        text = _inline_text(node).strip()
        if text:
            return f"**{text}**"
        return ""
    
    # --- Italic ---
    if tag_name in ("i", "em"):
        text = _inline_text(node).strip()
        if text:
            return f"*{text}*"
        return ""
    
    # --- Inline code ---
    if tag_name == "code" and not _is_inside_pre(node):
        text = node.get_text()
        if text:
            return f"`{text.strip()}`"
        return ""
    
    # --- Code blocks ---
    if tag_name == "pre":
        code = node.find("code")
        text = code.get_text() if code else node.get_text()
        # Try to detect language from class
        lang = ""
        if code and code.get("class"):
            classes = code["class"] if isinstance(code["class"], list) else [code["class"]]
            for cls in classes:
                if cls.startswith("language-") or cls.startswith("lang-"):
                    lang = cls.split("-", 1)[1]
                    break
        return f"\n\n```{lang}\n{text.rstrip()}\n```\n\n"
    
    # --- Blockquotes ---
    if tag_name == "blockquote":
        inner = _process_children(node, depth).strip()
        # Collapse excessive blank lines inside the quote
        inner = re.sub(r"\n{3,}", "\n\n", inner)
        lines = inner.splitlines()
        quoted = "\n".join(f"> {line}" if line.strip() else ">" for line in lines)
        return f"\n\n{quoted}\n\n"
    
    # --- Unordered lists ---
    if tag_name == "ul":
        return _process_list(node, ordered=False, depth=depth)
    
    # --- Ordered lists ---
    if tag_name == "ol":
        return _process_list(node, ordered=True, depth=depth)
    
    # --- List items (handled by parent list processor) ---
    if tag_name == "li":
        return _inline_text(node).strip()
    
    # --- Tables ---
    if tag_name == "table":
        return _process_table(node)
    
    # --- Images ---
    if tag_name == "img":
        alt = node.get("alt", "").strip()
        src = node.get("src", "")
        if alt and src:
            return f"![{alt}]({src})"
        elif alt:
            return f"[Image: {alt}]"
        return ""
    
    # --- Figure ---
    if tag_name == "figure":
        parts = []
        img = node.find("img")
        if img:
            alt = img.get("alt", "").strip()
            src = img.get("src", "")
            if src:
                parts.append(f"![{alt}]({src})")
        caption = node.find("figcaption")
        if caption:
            parts.append(f"*{caption.get_text(strip=True)}*")
        if parts:
            return "\n\n" + "\n".join(parts) + "\n\n"
        return _process_children(node, depth)
    
    # --- Div / Section / Article — just process children ---
    return _process_children(node, depth)


def _process_children(node: Tag, depth: int = 0) -> str:
    """Process all children of a node and concatenate results."""
    parts = []
    for child in node.children:
        parts.append(_process_node(child, depth))
    return "".join(parts)


def _inline_text(node: Tag) -> str:
    """Process a node's children for inline markdown (links, bold, italic, code)."""
    parts = []
    for child in node.children:
        if isinstance(child, NavigableString):
            text = str(child)
            if not _is_inside_pre(child):
                text = re.sub(r"[ \t]+", " ", text)
            parts.append(text)
        elif isinstance(child, Tag):
            child_name = child.name.lower() if child.name else ""
            if child_name == "a":
                text = _inline_text(child).strip()
                href = child.get("href", "")
                if text and href and not href.startswith("javascript:"):
                    parts.append(f"[{text}]({href})")
                else:
                    parts.append(text)
            elif child_name in ("b", "strong"):
                text = _inline_text(child).strip()
                if text:
                    parts.append(f"**{text}**")
            elif child_name in ("i", "em"):
                text = _inline_text(child).strip()
                if text:
                    parts.append(f"*{text}*")
            elif child_name == "code":
                text = child.get_text().strip()
                if text:
                    parts.append(f"`{text}`")
            elif child_name == "br":
                parts.append("\n")
            elif child_name == "img":
                alt = child.get("alt", "").strip()
                src = child.get("src", "")
                if alt and src:
                    parts.append(f"![{alt}]({src})")
                elif alt:
                    parts.append(f"[Image: {alt}]")
            else:
                # Recurse for nested inline elements (span, etc.)
                parts.append(_inline_text(child))
    return "".join(parts)


def _is_inside_pre(node) -> bool:
    """Check if a node is inside a <pre> element."""
    parent = node.parent
    while parent:
        if isinstance(parent, Tag) and parent.name == "pre":
            return True
        parent = parent.parent
    return False


def _process_list(node: Tag, ordered: bool, depth: int = 0) -> str:
    """Process an ordered or unordered list, supporting nesting."""
    items: list[str] = []
    indent = "  " * depth
    
    for idx, li in enumerate(node.find_all("li", recursive=False), 1):
        # Process the li content — handle nested lists separately
        text_parts = []
        nested_lists = []
        
        for child in li.children:
            if isinstance(child, Tag) and child.name in ("ul", "ol"):
                nested_lists.append(child)
            else:
                if isinstance(child, NavigableString):
                    text_parts.append(str(child).strip())
                elif isinstance(child, Tag):
                    text_parts.append(_inline_text(child).strip())
        
        text = " ".join(part for part in text_parts if part)
        
        if ordered:
            items.append(f"{indent}{idx}. {text}")
        else:
            items.append(f"{indent}- {text}")
        
        # Process nested lists with increased depth
        for nested in nested_lists:
            is_ordered = nested.name == "ol"
            nested_md = _process_list(nested, ordered=is_ordered, depth=depth + 1)
            items.append(nested_md.strip("\n"))
    
    return "\n\n" + "\n".join(items) + "\n\n"


def _process_table(table: Tag) -> str:
    """Convert an HTML table to markdown table format."""
    rows: list[list[str]] = []
    
    # Collect all rows (from thead, tbody, tfoot, or direct)
    for tr in table.find_all("tr"):
        cells = []
        for cell in tr.find_all(["th", "td"]):
            text = cell.get_text(strip=True)
            # Escape pipes in cell content
            text = text.replace("|", "\\|")
            cells.append(text)
        if cells:
            rows.append(cells)
    
    if not rows:
        return ""
    
    # Normalize column count
    max_cols = max(len(row) for row in rows)
    for row in rows:
        while len(row) < max_cols:
            row.append("")
    
    # Build markdown table
    lines: list[str] = []
    
    # Header row
    header = rows[0]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    
    # Data rows
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")
    
    return "\n\n" + "\n".join(lines) + "\n\n"
