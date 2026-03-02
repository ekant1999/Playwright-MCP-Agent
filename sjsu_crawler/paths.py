"""Resolve output paths under project output/ from package location (stable regardless of cwd)."""
from __future__ import annotations

import re
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _PACKAGE_DIR.parent
OUTPUT_DIR = _PROJECT_ROOT / "output"


def get_output_dir() -> Path:
    """Return project output directory; created if missing."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


def safe_filename(s: str) -> str:
    """Replace characters unsafe for filenames."""
    s = re.sub(r'[<>:"/\\|?*]', "_", s)
    return s.strip().strip(".") or "query"


def guides_json_path(query: str) -> Path:
    """output/guides_<query>.json"""
    name = safe_filename(query)[:80]
    return get_output_dir() / f"guides_{name}.json"


def search_json_path(query: str) -> Path:
    """output/search_<query>.json"""
    name = safe_filename(query)[:80]
    return get_output_dir() / f"search_{name}.json"


def download_dir_for(relative_path: str) -> Path:
    """Directory under output/ for downloads (e.g. output/downloads or output/guides_downloads)."""
    base = get_output_dir()
    path = base / safe_filename(relative_path.strip("/")).strip("_") or "downloads"
    path.mkdir(parents=True, exist_ok=True)
    return path
