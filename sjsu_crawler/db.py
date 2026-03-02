from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import asyncpg

from .models import GuideRecord, PageRecord, SearchResultRecord

SCHEMA_SQL = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")


def _schema_statements() -> list[str]:
    """Split schema file into single statements (asyncpg runs one at a time)."""
    return [s.strip() for s in SCHEMA_SQL.split(";") if s.strip()]


async def init_schema(conn: asyncpg.Connection) -> None:
    for stmt in _schema_statements():
        await conn.execute(stmt)


def _parse_crawled_at(value: str) -> datetime:
    """Parse ISO crawled_at string to datetime for asyncpg TIMESTAMPTZ."""
    if isinstance(value, datetime):
        return value
    s = value.replace("Z", "+00:00")
    return datetime.fromisoformat(s)

def _json_for_jsonb(value: list | dict | None) -> str | None:
    """Serialize Python list/dict to JSON string for asyncpg JSONB."""
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


async def upsert(
    conn: asyncpg.Connection,
    record: PageRecord,
    scope_prefix: str,
) -> None:
    d = record.to_dict()
    crawled_at = _parse_crawled_at(d["crawled_at"])
    await conn.execute(
        """
        INSERT INTO crawl_pages (
            scope_prefix, url, parent_url, depth, crawled_at,
            title, meta_description, full_text, headings, sections,
            paragraphs, tables, links_out, images, status, error_msg
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10::jsonb, $11::jsonb, $12::jsonb, $13::jsonb, $14::jsonb, $15, $16)
        ON CONFLICT (scope_prefix, url) DO UPDATE SET
            parent_url = EXCLUDED.parent_url,
            depth = EXCLUDED.depth,
            crawled_at = EXCLUDED.crawled_at,
            title = EXCLUDED.title,
            meta_description = EXCLUDED.meta_description,
            full_text = EXCLUDED.full_text,
            headings = EXCLUDED.headings,
            sections = EXCLUDED.sections,
            paragraphs = EXCLUDED.paragraphs,
            tables = EXCLUDED.tables,
            links_out = EXCLUDED.links_out,
            images = EXCLUDED.images,
            status = EXCLUDED.status,
            error_msg = EXCLUDED.error_msg
        """,
        scope_prefix,
        d["url"],
        d["parent_url"],
        d["depth"],
        crawled_at,
        d["title"] or None,
        d["meta_description"] or None,
        d["full_text"] or None,
        _json_for_jsonb(d.get("headings")),
        _json_for_jsonb(d.get("sections")),
        _json_for_jsonb(d.get("paragraphs")),
        _json_for_jsonb(d.get("tables")),
        _json_for_jsonb(d.get("links_out")),
        _json_for_jsonb(d.get("images")),
        d.get("status") or None,
        d.get("error_msg") or None,
    )


async def upsert_guide(conn: asyncpg.Connection, record: GuideRecord) -> None:
    d = record.to_dict()
    fetched_at = _parse_crawled_at(d["fetched_at"])
    await conn.execute(
        """
        INSERT INTO research_guides (
            url, title, query, query_type, fetched_at,
            full_content, sections, links_out, status, error_msg
        ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9, $10)
        ON CONFLICT (url) DO UPDATE SET
            title = EXCLUDED.title,
            query = EXCLUDED.query,
            query_type = EXCLUDED.query_type,
            fetched_at = EXCLUDED.fetched_at,
            full_content = EXCLUDED.full_content,
            sections = EXCLUDED.sections,
            links_out = EXCLUDED.links_out,
            status = EXCLUDED.status,
            error_msg = EXCLUDED.error_msg
        """,
        d["url"],
        d.get("title") or None,
        d["query"],
        d["query_type"],
        fetched_at,
        d.get("full_content") or None,
        _json_for_jsonb(d.get("sections")),
        _json_for_jsonb(d.get("links_out")),
        d.get("status") or None,
        d.get("error_msg") or None,
    )


async def upsert_search_result(
    conn: asyncpg.Connection,
    record: SearchResultRecord,
) -> None:
    d = record.to_dict()
    fetched_at = _parse_crawled_at(d["fetched_at"]) if d.get("fetched_at") else None
    await conn.execute(
        """
        INSERT INTO library_search_results (
            url, query, search_type, scope, title, fetched_at,
            snippet, authors, source, year, download_path, status, error_msg
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10, $11, $12, $13)
        ON CONFLICT (url, query) DO UPDATE SET
            search_type = EXCLUDED.search_type,
            scope = EXCLUDED.scope,
            title = EXCLUDED.title,
            fetched_at = EXCLUDED.fetched_at,
            snippet = EXCLUDED.snippet,
            authors = EXCLUDED.authors,
            source = EXCLUDED.source,
            year = EXCLUDED.year,
            download_path = EXCLUDED.download_path,
            status = EXCLUDED.status,
            error_msg = EXCLUDED.error_msg
        """,
        d["url"],
        d["query"],
        d.get("search_type") or "OneSearch",
        d.get("scope") or None,
        d.get("title") or None,
        fetched_at,
        d.get("snippet") or None,
        _json_for_jsonb(d.get("authors")),
        d.get("source") or None,
        d.get("year") or None,
        d.get("download_path") or None,
        d.get("status") or None,
        d.get("error_msg") or None,
    )
