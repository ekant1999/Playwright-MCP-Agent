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
from .writer import write_one_record

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


async def run(config_path: str) -> None:
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


def main() -> None:
    parser = argparse.ArgumentParser(description="SJSU Library Research Guides crawler")
    parser.add_argument(
        "--config",
        default=os.path.join(os.path.dirname(__file__), "config.yaml"),
        help="path to config.yaml (default: sjsu_crawler/config.yaml)",
    )
    args = parser.parse_args()
    try:
        asyncio.run(run(args.config))
    except Exception:
        logger.exception("Crawler failed")
        input("Press Enter to exit...")
        raise


if __name__ == "__main__":
    main()
