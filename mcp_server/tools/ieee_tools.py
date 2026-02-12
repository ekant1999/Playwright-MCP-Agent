"""IEEE Xplore research paper tools."""

import json
import httpx
from urllib.parse import quote_plus
from bs4 import BeautifulSoup
from mcp_server.browser_manager import BrowserManager
from mcp_server.schemas import (
    IeeeSearchInput,
    IeeeGetPaperInput,
    IeeeDownloadPdfInput
)
from mcp_server.utils.errors import format_error
from mcp_server.utils.file_manager import file_manager


async def ieee_search(arguments: dict) -> str:
    """Search IEEE Xplore for papers."""
    try:
        input_data = IeeeSearchInput(**arguments)
        manager = await BrowserManager.get_instance()
        page = await manager.ensure_page()
        
        # Build search URL
        query_encoded = quote_plus(input_data.query)
        search_url = f"https://ieeexplore.ieee.org/search/searchresult.jsp?queryText={query_encoded}"
        
        # Navigate to search page
        await page.goto(search_url, wait_until="networkidle", timeout=60000)
        
        # Wait for results (try multiple possible selectors)
        try:
            await page.wait_for_selector(".List-results-items, .result-item, xpl-results-list", timeout=20000)
        except:
            # Check if there's a CAPTCHA or access issue
            page_content = await page.content()
            if "captcha" in page_content.lower() or "access denied" in page_content.lower():
                return format_error(
                    "ieee_search",
                    Exception("Access blocked"),
                    "IEEE Xplore has blocked automated access. Try again later or use a different network."
                )
            raise
        
        # Extract search results
        results = await page.evaluate(f"""
            (maxResults) => {{
                const results = [];
                
                // Try different result selectors
                const resultItems = document.querySelectorAll('.List-results-items .List-results-item, .result-item, xpl-results-item');
                
                for (let i = 0; i < Math.min(resultItems.length, maxResults); i++) {{
                    const item = resultItems[i];
                    
                    // Extract title and URL
                    const titleElem = item.querySelector('h3 a, .result-item-title a, h2 a, [class*="title"] a');
                    if (!titleElem) continue;
                    
                    const title = titleElem.textContent.trim();
                    let url = titleElem.href;
                    if (!url.startsWith('http')) {{
                        url = 'https://ieeexplore.ieee.org' + url;
                    }}
                    
                    // Extract authors
                    const authorElems = item.querySelectorAll('.author a, [class*="author"] a, [class*="Author"] span');
                    const authors = Array.from(authorElems).map(a => a.textContent.trim()).filter(a => a);
                    
                    // Extract abstract/description
                    const abstractElem = item.querySelector('.js-displayer-content, .abstract-text, [class*="abstract"], [class*="description"]');
                    const abstract = abstractElem ? abstractElem.textContent.trim() : '';
                    
                    // Extract publication info
                    const pubInfoElem = item.querySelector('.publisher-info-container, .description, [class*="publication"]');
                    const publicationInfo = pubInfoElem ? pubInfoElem.textContent.trim() : '';
                    
                    results.push({{
                        title,
                        url,
                        authors,
                        abstract,
                        publication_info: publicationInfo
                    }});
                }}
                
                return results;
            }}
        """, input_data.max_results)
        
        result = {
            "status": "success",
            "query": input_data.query,
            "results_count": len(results),
            "results": results
        }
        
        return json.dumps(result, indent=2)
    
    except Exception as e:
        return format_error(
            "ieee_search",
            e,
            "IEEE Xplore layout may have changed or access is blocked. Try again later."
        )


async def ieee_get_paper(arguments: dict) -> str:
    """Get detailed metadata for a specific IEEE paper."""
    try:
        input_data = IeeeGetPaperInput(**arguments)
        manager = await BrowserManager.get_instance()
        page = await manager.ensure_page()
        
        # Navigate to paper page
        await page.goto(input_data.url, wait_until="networkidle", timeout=60000)
        
        # Wait for content to load
        await page.wait_for_selector(".document-header, .document-main, xpl-document-header", timeout=15000)
        
        # Extract paper details
        paper_data = await page.evaluate("""
            () => {
                const data = {};
                
                // Title
                const titleElem = document.querySelector('.document-title, h1[class*="title"], xpl-document-title');
                data.title = titleElem ? titleElem.textContent.trim() : '';
                
                // Authors
                const authorElems = document.querySelectorAll('.authors-info a, .author-name, [class*="author"] a, xpl-author');
                data.authors = Array.from(authorElems).map(a => a.textContent.trim()).filter(a => a);
                
                // Abstract
                const abstractElem = document.querySelector('.abstract-text, [class*="Abstract"] .u-mb-1, xpl-document-abstract');
                data.abstract = abstractElem ? abstractElem.textContent.trim() : '';
                
                // Keywords
                const keywordElems = document.querySelectorAll('.stats-keywords a, [class*="keyword"], xpl-document-keyword');
                data.keywords = Array.from(keywordElems).map(k => k.textContent.trim()).filter(k => k);
                
                // DOI
                const doiElem = document.querySelector('.doi, [class*="DOI"], xpl-document-doi');
                data.doi = doiElem ? doiElem.textContent.trim().replace('DOI:', '').trim() : '';
                
                // Publication date
                const dateElem = document.querySelector('.doc-abstract-pubdate, [class*="date"], xpl-document-date');
                data.publication_date = dateElem ? dateElem.textContent.trim() : '';
                
                // Publisher
                const publisherElem = document.querySelector('.publisher, [class*="publisher"]');
                data.publisher = publisherElem ? publisherElem.textContent.trim() : 'IEEE';
                
                // Citation count
                const citationElem = document.querySelector('.document-banner-metric-count, [class*="citation"]');
                data.citations = citationElem ? citationElem.textContent.trim() : 'N/A';
                
                // PDF link
                const pdfElem = document.querySelector('a[href*="stamp.jsp"], a[href*=".pdf"], [class*="pdf"] a');
                data.pdf_link = pdfElem ? pdfElem.href : '';
                
                return data;
            }
        """)
        
        result = {
            "status": "success",
            "url": input_data.url,
            **paper_data
        }
        
        return json.dumps(result, indent=2)
    
    except Exception as e:
        return format_error("ieee_get_paper", e)


async def ieee_download_pdf(arguments: dict) -> str:
    """Download PDF for an IEEE paper."""
    try:
        input_data = IeeeDownloadPdfInput(**arguments)
        manager = await BrowserManager.get_instance()
        page = await manager.ensure_page()
        
        # Navigate to paper page
        await page.goto(input_data.url, wait_until="networkidle", timeout=60000)
        
        # Wait for page to load
        await page.wait_for_selector(".document-header, .document-main", timeout=15000)
        
        # Try to find PDF link
        pdf_info = await page.evaluate("""
            () => {
                // Try multiple selectors for PDF link
                const pdfSelectors = [
                    'a[href*="stamp.jsp"]',
                    'a[href*="stamp/stamp.jsp"]',
                    'a[href*="/iel"]',
                    '.pdf-btn-link',
                    '[class*="pdf"] a'
                ];
                
                for (const selector of pdfSelectors) {
                    const elem = document.querySelector(selector);
                    if (elem && elem.href) {
                        return {
                            found: true,
                            url: elem.href,
                            text: elem.textContent.trim()
                        };
                    }
                }
                
                return { found: false };
            }
        """)
        
        if not pdf_info.get('found'):
            # Get title for error message
            title = await page.title()
            return json.dumps({
                "status": "error",
                "message": "PDF requires IEEE subscription or is not publicly accessible",
                "url": input_data.url,
                "title": title,
                "suggestion": "You may need an IEEE Xplore subscription to download this PDF. Try accessing it through your institution or download manually."
            }, indent=2)
        
        pdf_url = pdf_info['url']
        
        # Try to download PDF
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            # Set headers to mimic browser
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                'Referer': input_data.url
            }
            
            response = await client.get(pdf_url, headers=headers)
            
            # Check if we got a PDF
            content_type = response.headers.get('content-type', '')
            if 'pdf' not in content_type.lower() and response.status_code == 200:
                # Might be a login page
                if len(response.content) < 100000:  # PDFs are usually larger
                    return json.dumps({
                        "status": "error",
                        "message": "PDF requires IEEE subscription",
                        "pdf_url": pdf_url,
                        "suggestion": "The PDF link was found but requires authentication. Please download manually or access through your institution."
                    }, indent=2)
            
            response.raise_for_status()
            pdf_content = response.content
        
        # Extract paper ID from URL for filename
        import re
        paper_id_match = re.search(r'/document/(\d+)', input_data.url)
        paper_id = paper_id_match.group(1) if paper_id_match else 'paper'
        
        # Save PDF
        filename = f"ieee_{paper_id}.pdf"
        file_info = file_manager.save_file(pdf_content, filename)
        
        result = {
            "status": "success",
            "message": "PDF downloaded successfully",
            "url": input_data.url,
            "pdf_url": pdf_url,
            **file_info
        }
        
        return json.dumps(result, indent=2)
    
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403 or e.response.status_code == 401:
            return json.dumps({
                "status": "error",
                "message": "PDF requires IEEE subscription",
                "url": input_data.url,
                "http_status": e.response.status_code,
                "suggestion": "Access denied. Please download manually or access through your institution's IEEE subscription."
            }, indent=2)
        return format_error("ieee_download_pdf", e)
    
    except Exception as e:
        return format_error("ieee_download_pdf", e)
