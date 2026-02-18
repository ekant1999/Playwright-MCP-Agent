from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field


@dataclass
class PageRecord:
    url: str
    crawled_at: str
    parent_url: str | None = None
    depth: int = 0
    title: str = ""
    meta_description: str = ""
    full_text: str = ""
    headings: list[dict] = field(default_factory=list)
    sections: list[dict] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)
    links_out: list[str] = field(default_factory=list)
    images: list[dict] = field(default_factory=list)
    status: str = "ok"
    error_msg: str = ""

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)
