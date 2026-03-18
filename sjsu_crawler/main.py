"""Choice-based CLI: crawl, guides, search (explicit subcommands)."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import time

import asyncpg

from .config import load_config
from .crawler import crawl
from .db import init_schema, upsert
from .extractor import extract
from .guides_flow import run_guides
from .search_flow import run_search
from .writer import write_one_record

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_CONFIG = os.path.join(os.path.dirname(__file__), "config.yaml")


def _parse_material_types(raw: list[str] | None) -> list[str]:
    """Parse --material-type args: allow comma-separated (e.g. 'Articles,Books') and return flat list."""
    if not raw:
        return []
    out = []
    for s in raw:
        out.extend(x.strip() for x in s.split(",") if x.strip())
    return out


async def run_crawl(config_path: str) -> None:
    """Full-site DFS crawl of LibGuides; writes to JSON and/or Postgres (crawl_pages)."""
    config = load_config(config_path)

    logger.info("start_url   = %s", config.start_url)
    logger.info("scope       = %s", config.scope_prefix)
    logger.info("max_depth   = %s", config.max_depth)
    logger.info("max_pages   = %s", config.max_pages)
    logger.info("output      = %s", config.output_json)
    if config.postgres.enabled:
        logger.info("postgres    = enabled")

    t0 = time.monotonic()
    records = crawl(config, extract)

    count = 0
    fh = None
    conn = None

    if config.output_json and config.output_json.strip():
        out_dir = os.path.dirname(config.output_json)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        fh = open(config.output_json, "w", encoding="utf-8")
        fh.write("[\n")

    if config.postgres.enabled:
        url_safe = config.postgres.url.split("@")[-1] if "@" in config.postgres.url else config.postgres.url
        logger.info("postgres URL  = ...@%s", url_safe)
        conn = await asyncpg.connect(config.postgres.url)
        await init_schema(conn)
        logger.info("postgres      = schema ready, upserting each record")

    try:
        async for record in records:
            if fh is not None:
                write_one_record(fh, record, need_comma=count > 0)
            if conn is not None:
                try:
                    await upsert(conn, record, config.scope_prefix)
                except Exception as e:
                    logger.exception("postgres upsert failed for url=%s: %s", record.url, e)
                    raise
            count += 1
    finally:
        if fh is not None:
            fh.write("\n]\n")
            fh.close()
        if conn is not None:
            await conn.close()

    elapsed = time.monotonic() - t0
    logger.info("--- crawl complete ---")
    logger.info("pages crawled : %d", count)
    if config.output_json:
        logger.info("output file   : %s", os.path.abspath(config.output_json))
    if config.postgres.enabled:
        logger.info("postgres      : %d rows upserted", count)
    logger.info("elapsed       : %.1f s", elapsed)


async def run_guides_cmd(config_path: str, query: str, query_type: str, full_content: bool, no_db: bool) -> None:
    """Fetches Research Guides list; optional --full-content and downloads. Always writes output/guides_<query>.json."""
    config = load_config(config_path)
    logger.info("guides query=%s type=%s full_content=%s no_db=%s", query, query_type, full_content, no_db)
    await run_guides(
        config,
        query=query,
        query_type=query_type,
        full_content=full_content,
        no_db=no_db,
        download_attachments=full_content,
    )


async def run_search_cmd(
    config_path: str,
    query: str,
    search_type: str,
    scope: str,
    download_dir: str,
    no_db: bool,
    advanced: bool,
    material_types: list[str],
    full_content: bool = False,
) -> None:
    """OneSearch (Primo): search, extract results, optional PDF download and full page content. Writes output/search_<query>.json when --no-db or Postgres disabled."""
    config = load_config(config_path)
    logger.info(
        "search query=%s search_type=%s scope=%s download_dir=%s no_db=%s advanced=%s material_types=%s full_content=%s",
        query, search_type, scope, download_dir or "(none)", no_db, advanced, material_types or "none", full_content,
    )
    await run_search(
        config,
        query=query,
        search_type=search_type,
        scope=scope,
        download_dir_path=download_dir,
        no_db=no_db,
        advanced=advanced,
        material_types=material_types or None,
        full_content=full_content,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SJSU Library CLI: crawl LibGuides, fetch Research Guides, or search OneSearch (Primo).",
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG,
        help="path to config.yaml",
    )
    subparsers = parser.add_subparsers(dest="command", required=True, help="Subcommand to run")

    # crawl: full-site DFS
    p_crawl = subparsers.add_parser("crawl", help="Full-site DFS crawl of LibGuides; JSON and/or Postgres (crawl_pages)")
    p_crawl.set_defaults(func=lambda a: asyncio.run(run_crawl(a.config)))

    # guides: research guides list
    p_guides = subparsers.add_parser("guides", help="Fetch Research Guides list (by subject/course/type); optional --full-content and downloads")
    p_guides.add_argument("--query", default="all", help="Query filter (e.g. subject/course name or 'all')")
    p_guides.add_argument("--query-type", default="all", choices=("subject", "course", "type", "all"), help="Type of guide list")
    p_guides.add_argument("--full-content", action="store_true", help="Visit each guide and extract full text (#s-lg-content)")
    p_guides.add_argument("--no-db", action="store_true", help="Skip Postgres; still write output/guides_<query>.json")
    p_guides.set_defaults(
        func=lambda a: asyncio.run(
            run_guides_cmd(a.config, a.query, a.query_type, a.full_content, a.no_db)
        )
    )

    # search: OneSearch (Primo)
    p_search = subparsers.add_parser("search", help="OneSearch (Primo) for articles/books/PDFs; extract results and optional PDF download")
    p_search.add_argument("query", help="Search query string")
    p_search.add_argument("--search-type", default="OneSearch", help="e.g. OneSearch, Articles+ (default: OneSearch)")
    p_search.add_argument("--scope", default="", help="Scope filter (e.g. San Jose State Collections)")
    p_search.add_argument("--download-dir", default="", help="Download article/PDF files into this dir under output/ (e.g. search_pdfs). Required for PDF download.")
    p_search.add_argument("--no-db", action="store_true", help="Skip Postgres; write output/search_<query>.json")
    p_search.add_argument("--advanced", action="store_true", help="Use Primo advanced search (query + scope + material type)")
    p_search.add_argument("--material-type", dest="material_types", metavar="TYPE", action="append", default=None, help="Material type in advanced search dropdown (e.g. Articles, Book chapters for articles/documents; repeat or comma-separated)")
    p_search.add_argument("--full-content", action="store_true", help="Visit each result URL and extract full page content (e.g. Primo fulldisplay / catalog record)")
    p_search.set_defaults(
        func=lambda a: asyncio.run(
            run_search_cmd(
                a.config,
                a.query,
                a.search_type,
                a.scope,
                a.download_dir or "",
                a.no_db,
                getattr(a, "advanced", False),
                _parse_material_types(a.material_types),
                getattr(a, "full_content", False),
            )
        )
    )

    args = parser.parse_args()
    try:
        args.func(args)
    except Exception:
        logger.exception("Command failed")
        if not os.environ.get("CI"):
            input("Press Enter to exit...")
        raise


if __name__ == "__main__":
    main()
