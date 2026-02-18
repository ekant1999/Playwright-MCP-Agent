from __future__ import annotations

import json
from collections.abc import AsyncGenerator

from .models import PageRecord


async def write_records(
    records: AsyncGenerator[PageRecord, None],
    output_path: str,
) -> int:
    count = 0
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write("[\n")
        async for record in records:
            if count > 0:
                fh.write(",\n")
            blob = json.dumps(record.to_dict(), ensure_ascii=False, indent=2)
            fh.write(blob)
            fh.flush()
            count += 1
        fh.write("\n]\n")
    return count
