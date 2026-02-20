from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import asyncpg

from .models import PageRecord

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
