from __future__ import annotations

import pathlib
from dataclasses import dataclass

import yaml


@dataclass(frozen=True)
class Config:
    start_url: str
    scope_prefix: str
    max_depth: int
    max_pages: int
    polite_delay_ms: int
    headless: bool
    output_json: str


def load_config(path: str) -> Config:
    raw = pathlib.Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise ValueError(f"config file must be a YAML mapping, got {type(data).__name__}")

    required_keys = {
        "start_url", "scope_prefix", "max_depth",
        "max_pages", "polite_delay_ms", "headless", "output_json",
    }
    missing = required_keys - data.keys()
    if missing:
        raise ValueError(f"missing config keys: {', '.join(sorted(missing))}")

    start_url = str(data["start_url"])
    scope_prefix = str(data["scope_prefix"])
    max_depth = int(data["max_depth"])
    max_pages = int(data["max_pages"])
    polite_delay_ms = int(data["polite_delay_ms"])
    headless = bool(data["headless"])
    output_json = str(data["output_json"])

    if not start_url.startswith("http"):
        raise ValueError(f"start_url must begin with http, got: {start_url}")
    if not scope_prefix.startswith("http"):
        raise ValueError(f"scope_prefix must begin with http, got: {scope_prefix}")
    if max_depth < -1:
        raise ValueError(f"max_depth must be >= -1, got {max_depth}")
    if max_pages < 1:
        raise ValueError(f"max_pages must be >= 1, got {max_pages}")
    if polite_delay_ms < 0:
        raise ValueError(f"polite_delay_ms must be >= 0, got {polite_delay_ms}")

    out_dir = pathlib.Path(output_json).parent
    out_dir.mkdir(parents=True, exist_ok=True)

    return Config(
        start_url=start_url,
        scope_prefix=scope_prefix,
        max_depth=max_depth,
        max_pages=max_pages,
        polite_delay_ms=polite_delay_ms,
        headless=headless,
        output_json=output_json,
    )
