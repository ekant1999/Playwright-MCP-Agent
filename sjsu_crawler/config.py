from __future__ import annotations

import pathlib
from dataclasses import dataclass

import yaml


@dataclass(frozen=True)
class PostgresConfig:
    enabled: bool
    url: str


@dataclass(frozen=True)
class Config:
    start_url: str
    scope_prefix: str
    max_depth: int
    max_pages: int
    polite_delay_ms: int
    headless: bool
    output_json: str
    postgres: PostgresConfig
    skip_url_contains: tuple[str, ...]
    ignore_https_errors: bool


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
    if max_pages < -1 or max_pages == 0:
        raise ValueError(f"max_pages must be >= 1 or -1 (no limit), got {max_pages}")
    if polite_delay_ms < 0:
        raise ValueError(f"polite_delay_ms must be >= 0, got {polite_delay_ms}")

    out_dir = pathlib.Path(output_json).parent
    out_dir.mkdir(parents=True, exist_ok=True)

    postgres_enabled = False
    postgres_url = ""
    if "postgres" in data:
        pg = data["postgres"]
        if isinstance(pg, dict):
            postgres_enabled = bool(pg.get("enabled", False))
            postgres_url = str(pg.get("url", ""))
            if postgres_enabled and postgres_url and not postgres_url.startswith("postgresql"):
                raise ValueError("postgres.url must start with postgresql:// when provided")
    postgres = PostgresConfig(enabled=postgres_enabled, url=postgres_url)

    skip_url_contains: tuple[str, ...] = ()
    if "skip_url_contains" in data:
        raw = data["skip_url_contains"]
        if isinstance(raw, list):
            skip_url_contains = tuple(str(x) for x in raw)
        else:
            skip_url_contains = (str(raw),) if raw else ()
    ignore_https_errors = bool(data.get("ignore_https_errors", False))

    return Config(
        start_url=start_url,
        scope_prefix=scope_prefix,
        max_depth=max_depth,
        max_pages=max_pages,
        polite_delay_ms=polite_delay_ms,
        headless=headless,
        output_json=output_json,
        postgres=postgres,
        skip_url_contains=skip_url_contains,
        ignore_https_errors=ignore_https_errors,
    )
