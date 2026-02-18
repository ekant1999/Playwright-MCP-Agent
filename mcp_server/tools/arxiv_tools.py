"""arXiv research paper tools."""

import json
import arxiv
from datetime import datetime, timedelta
import httpx
from mcp_server.schemas import (
    ArxivSearchInput,
    ArxivGetPaperInput,
    ArxivDownloadPdfInput,
    ArxivGetRecentInput
)
from mcp_server.utils.errors import format_error
from mcp_server.utils.file_manager import file_manager


async def arxiv_search(arguments: dict) -> str:
    """Search arXiv for papers."""
    try:
        input_data = ArxivSearchInput(**arguments)
        
        # Build search query
        query = input_data.query
        if input_data.category:
            query = f"cat:{input_data.category} AND {query}"
        
        # Search arXiv
        search = arxiv.Search(
            query=query,
            max_results=input_data.max_results,
            sort_by=arxiv.SortCriterion.Relevance
        )
        
        results = []
        for paper in search.results():
            results.append({
                "arxiv_id": paper.entry_id.split("/")[-1],
                "title": paper.title,
                "authors": [author.name for author in paper.authors],
                "abstract": paper.summary,
                "published": paper.published.isoformat(),
                "updated": paper.updated.isoformat() if paper.updated else None,
                "pdf_url": paper.pdf_url,
                "categories": paper.categories,
                "primary_category": paper.primary_category
            })
        
        result = {
            "status": "success",
            "query": input_data.query,
            "category": input_data.category,
            "results_count": len(results),
            "results": results
        }
        
        return json.dumps(result, indent=2)
    
    except Exception as e:
        return format_error("arxiv_search", e, "Check your query syntax and try again.")


async def arxiv_get_paper(arguments: dict) -> str:
    """Get detailed metadata for a specific arXiv paper."""
    try:
        input_data = ArxivGetPaperInput(**arguments)
        
        # Clean paper ID
        paper_id = input_data.paper_id.replace("arXiv:", "").replace("v", "").split()[0]
        
        # Search for specific paper
        search = arxiv.Search(id_list=[paper_id])
        
        paper = next(search.results(), None)
        
        if not paper:
            return format_error(
                "arxiv_get_paper",
                Exception("Paper not found"),
                f"No paper found with ID: {paper_id}"
            )
        
        paper_data = {
            "status": "success",
            "arxiv_id": paper.entry_id.split("/")[-1],
            "title": paper.title,
            "authors": [author.name for author in paper.authors],
            "abstract": paper.summary,
            "published": paper.published.isoformat(),
            "updated": paper.updated.isoformat() if paper.updated else None,
            "pdf_url": paper.pdf_url,
            "categories": paper.categories,
            "primary_category": paper.primary_category,
            "doi": paper.doi,
            "journal_ref": paper.journal_ref,
            "comment": paper.comment,
            "links": [{"title": link.title, "href": link.href} for link in paper.links]
        }
        
        return json.dumps(paper_data, indent=2)
    
    except Exception as e:
        return format_error("arxiv_get_paper", e)


async def arxiv_download_pdf(arguments: dict) -> str:
    """Download PDF for an arXiv paper."""
    try:
        input_data = ArxivDownloadPdfInput(**arguments)
        
        # Clean paper ID
        paper_id = input_data.paper_id.replace("arXiv:", "").replace("v", "").split()[0]
        
        # Get paper metadata first
        search = arxiv.Search(id_list=[paper_id])
        paper = next(search.results(), None)
        
        if not paper:
            return format_error(
                "arxiv_download_pdf",
                Exception("Paper not found"),
                f"No paper found with ID: {paper_id}"
            )
        
        # Download PDF
        pdf_url = paper.pdf_url
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(pdf_url)
            response.raise_for_status()
            pdf_content = response.content
        
        # Save PDF
        filename = f"arxiv_{paper_id}.pdf"
        file_info = file_manager.save_file(pdf_content, filename)
        
        saved_path = file_info["path"]
        result = {
            "status": "downloaded",
            "path": saved_path,
            "file_path": saved_path,  # Same as path; use this to open/locate the file
            "message": f"Downloaded PDF successfully. Saved to download folder: {saved_path}",
            "download_folder": str(file_manager.base_dir.absolute()),
            "arxiv_id": paper_id,
            "title": paper.title,
            "pdf_url": pdf_url,
            **file_info
        }
        
        return json.dumps(result, indent=2)
    
    except Exception as e:
        return format_error("arxiv_download_pdf", e)


async def arxiv_get_recent(arguments: dict) -> str:
    """Get recent papers from an arXiv category."""
    try:
        input_data = ArxivGetRecentInput(**arguments)
        
        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=input_data.days)
        
        # Build query for category and date range
        query = f"cat:{input_data.category}"
        
        # Search arXiv
        search = arxiv.Search(
            query=query,
            max_results=input_data.max_results * 2,  # Get more to filter by date
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending
        )
        
        results = []
        for paper in search.results():
            # Filter by date
            if paper.published >= start_date.replace(tzinfo=paper.published.tzinfo):
                results.append({
                    "arxiv_id": paper.entry_id.split("/")[-1],
                    "title": paper.title,
                    "authors": [author.name for author in paper.authors],
                    "abstract": paper.summary,
                    "published": paper.published.isoformat(),
                    "updated": paper.updated.isoformat() if paper.updated else None,
                    "pdf_url": paper.pdf_url,
                    "categories": paper.categories
                })
                
                if len(results) >= input_data.max_results:
                    break
        
        result = {
            "status": "success",
            "category": input_data.category,
            "days": input_data.days,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "results_count": len(results),
            "results": results
        }
        
        return json.dumps(result, indent=2)
    
    except Exception as e:
        return format_error("arxiv_get_recent", e)
