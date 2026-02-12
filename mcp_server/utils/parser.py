"""HTML parsing and content extraction utilities."""

from bs4 import BeautifulSoup
from typing import Optional
import re


def html_to_text(html: str, preserve_links: bool = False) -> str:
    """Convert HTML to plain text."""
    soup = BeautifulSoup(html, 'lxml')
    
    # Remove script and style elements
    for script in soup(["script", "style", "noscript"]):
        script.decompose()
    
    if preserve_links:
        # Replace links with [text](url) format
        for link in soup.find_all('a', href=True):
            link.string = f"[{link.get_text()}]({link['href']})"
    
    # Get text
    text = soup.get_text()
    
    # Clean up whitespace
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    text = '\n'.join(chunk for chunk in chunks if chunk)
    
    return text


def html_to_markdown(html: str) -> str:
    """Convert HTML to markdown format."""
    soup = BeautifulSoup(html, 'lxml')
    
    # Remove script and style elements
    for script in soup(["script", "style", "noscript"]):
        script.decompose()
    
    markdown = []
    
    # Process headings
    for i in range(1, 7):
        for heading in soup.find_all(f'h{i}'):
            text = heading.get_text().strip()
            if text:
                markdown.append(f"{'#' * i} {text}\n")
                heading.replace_with(f"__HEADING_{len(markdown)}__")
    
    # Process lists
    for ul in soup.find_all('ul'):
        items = []
        for li in ul.find_all('li', recursive=False):
            items.append(f"- {li.get_text().strip()}")
        if items:
            markdown.append('\n'.join(items) + '\n')
            ul.replace_with(f"__LIST_{len(markdown)}__")
    
    for ol in soup.find_all('ol'):
        items = []
        for idx, li in enumerate(ol.find_all('li', recursive=False), 1):
            items.append(f"{idx}. {li.get_text().strip()}")
        if items:
            markdown.append('\n'.join(items) + '\n')
            ol.replace_with(f"__LIST_{len(markdown)}__")
    
    # Process links
    for link in soup.find_all('a', href=True):
        text = link.get_text().strip()
        href = link['href']
        if text and href:
            link.replace_with(f"[{text}]({href})")
    
    # Process bold and italic
    for bold in soup.find_all(['b', 'strong']):
        text = bold.get_text().strip()
        if text:
            bold.replace_with(f"**{text}**")
    
    for italic in soup.find_all(['i', 'em']):
        text = italic.get_text().strip()
        if text:
            italic.replace_with(f"*{text}*")
    
    # Process code
    for code in soup.find_all('code'):
        text = code.get_text().strip()
        if text:
            code.replace_with(f"`{text}`")
    
    # Get remaining text
    text = soup.get_text()
    
    # Replace placeholders
    for idx, item in enumerate(markdown, 1):
        text = text.replace(f"__HEADING_{idx}__", item)
        text = text.replace(f"__LIST_{idx}__", item)
    
    # Clean up whitespace
    text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)
    
    return text.strip()


def extract_main_content(html: str) -> str:
    """Extract main content from HTML, removing navigation, ads, etc."""
    soup = BeautifulSoup(html, 'lxml')
    
    # Remove unwanted elements
    for element in soup(["script", "style", "noscript", "header", "footer", "nav", "aside"]):
        element.decompose()
    
    # Remove common ad/tracking classes
    ad_patterns = ['ad', 'advertisement', 'sidebar', 'widget', 'social', 'share', 'cookie', 'banner']
    for pattern in ad_patterns:
        for element in soup.find_all(class_=lambda x: x and pattern in x.lower()):
            element.decompose()
        for element in soup.find_all(id=lambda x: x and pattern in x.lower()):
            element.decompose()
    
    # Try to find main content area
    main_content = (
        soup.find('main') or
        soup.find('article') or
        soup.find(class_=lambda x: x and 'content' in x.lower()) or
        soup.find(id=lambda x: x and 'content' in x.lower()) or
        soup.find('body')
    )
    
    if main_content:
        return str(main_content)
    
    return str(soup)
