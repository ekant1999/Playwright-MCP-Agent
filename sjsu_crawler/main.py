from __future__ import annotations

import argparse
import asyncio
import logging
import os
import time

from .config import load_config
from .crawler import crawl
from .extractor import extract
from .writer import write_records

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

    t0 = time.monotonic()
    records = crawl(config, extract)
    count = await write_records(records, config.output_json)
    elapsed = time.monotonic() - t0

    logger.info("--- crawl complete ---")
    logger.info("pages crawled : %d", count)
    logger.info("output file   : %s", os.path.abspath(config.output_json))
    logger.info("elapsed       : %.1f s", elapsed)


def main() -> None:
    parser = argparse.ArgumentParser(description="SJSU Library Research Guides crawler")
    parser.add_argument(
        "--config",
        default=os.path.join(os.path.dirname(__file__), "config.yaml"),
        help="path to config.yaml (default: sjsu_crawler/config.yaml)",
    )
    args = parser.parse_args()
    asyncio.run(run(args.config))


if __name__ == "__main__":
    main()
