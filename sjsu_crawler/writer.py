from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import TextIO

from .models import PageRecord


def write_one_record(fh: TextIO, record: PageRecord, need_comma: bool) -> None:
    if need_comma:
        fh.write(",\n")
    blob = json.dumps(record.to_dict(), ensure_ascii=False, indent=2)
    fh.write(blob)
    fh.flush()


async def write_records(
    records: AsyncGenerator[PageRecord, None],
    output_path: str,
) -> int:
    count = 0
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write("[\n")
        async for record in records:
            write_one_record(fh, record, need_comma=count > 0)
            count += 1
        fh.write("\n]\n")
    return count
