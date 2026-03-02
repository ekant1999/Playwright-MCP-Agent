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


@dataclass
class GuideRecord:
    """Single research guide (list view or full-content)."""
    url: str
    title: str
    query: str  # subject, course, or type filter used to fetch this list
    query_type: str  # "subject" | "course" | "type" | "all"
    fetched_at: str
    full_content: str = ""  # populated when --full-content
    sections: list[dict] = field(default_factory=list)
    links_out: list[str] = field(default_factory=list)
    status: str = "ok"
    error_msg: str = ""

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass
class SearchResultRecord:
    """Single Primo/OneSearch result (article, book, etc.)."""
    url: str
    title: str
    query: str
    search_type: str  # e.g. "OneSearch", "Articles+"
    scope: str = ""
    fetched_at: str = ""
    snippet: str = ""
    authors: list[str] = field(default_factory=list)
    source: str = ""
    year: str = ""
    download_path: str = ""  # local path if PDF/doc was downloaded
    status: str = "ok"
    error_msg: str = ""

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)
