# SJSU Crawler — Summary and Flow

## Summary

The **SJSU crawler** is a modular async Python web scraper for LibGuides (e.g. `https://library.sjsu.edu/research-guides` and related URLs). It crawls in-scope pages with stack-based DFS, extracts main content (title, full text, headings, sections, tables, links, images), and can write results to a **JSON file** and/or **PostgreSQL**. Re-running the crawler **upserts** into Postgres (no duplicate rows); `crawled_at` is updated so you know when each page was last fetched.

### Features

- **Modular design**: Config, models, extractor, crawler, writer, and DB are separate; no cross-module logic or global state.
- **LibGuides-aware extraction**: Main content is taken from `#s-lg-content` (center column) so output matches the visible guide text, not nav/sidebar.
- **Hierarchy in data**: Each page has `parent_url` and `depth` (0 = start URL). Stored in Postgres for query-by-depth and parent-child traversal.
- **Optional outputs**: JSON only, Postgres only, or both, controlled by `config.yaml`.
- **Upsert semantics**: Same `(scope_prefix, url)` in Postgres is updated on re-run; no duplicates, and changed source content overwrites the row.

### Directory layout

```
sjsu_crawler/
  config.yaml      # start_url, scope_prefix, max_depth, max_pages, polite_delay_ms, headless, output_json, postgres
  config.py        # Config + PostgresConfig, load_config()
  models.py        # PageRecord dataclass (url, parent_url, depth, crawled_at, title, full_text, sections, …)
  extractor.py     # extract(page, url, parent_url, depth) -> PageRecord (main-content only)
  crawler.py       # crawl(config, extract_fn) -> AsyncGenerator[PageRecord]
  writer.py        # write_one_record(), write_records() for incremental JSON
  db.py            # init_schema(), upsert() for Postgres
  schema.sql       # CREATE TABLE crawl_pages + indexes
  main.py          # Orchestrator: load config, run crawl, write to JSON and/or Postgres
  __main__.py      # Entry point for python -m sjsu_crawler
```

---

## Flow

### High-level pipeline

```mermaid
flowchart LR
    ConfigYAML[config.yaml]
    ConfigYAML --> LoadConfig[config.load_config]
    LoadConfig --> Main[main.run]
    Main --> Crawl[crawler.crawl]
    Crawl -->|PageRecord stream| Loop[async for record]
    Loop --> JSON[writer.write_one_record]
    Loop --> DB[db.upsert]
    Config[Config] --> Crawl
    Config --> Main
```

### Step-by-step

1. **Load config**  
   `main.run()` calls `load_config(config_path)`. Reads YAML, validates required keys and constraints, parses optional `postgres` (enabled, url). Ensures `output_json` parent directory exists. Returns frozen `Config` (and nested `PostgresConfig`).

2. **Crawl**  
   `crawl(config, extract)` launches Playwright (Chromium), normalizes URLs (lowercase, strip trailing slash and fragment), and does stack-based DFS:
   - Pop `(url, parent_url, depth)` from stack; skip if visited or over `max_pages`.
   - `page.goto(url)` then `extract(page, url, parent_url, depth)` to get a `PageRecord`.
   - Yield that record.
   - If depth allows, push in-scope links from `record.links_out` onto the stack.  
   On timeout/error, yields a `PageRecord` with `status="error"` and continues.

3. **Extract**  
   `extract(page, url, parent_url, depth)` runs in the browser context. It restricts to the main content root (`#s-lg-content` or fallback to `body`), then reads title, meta description, full text, h1–h4 headings, `.s-lib-box` sections (title + text + links), paragraphs (if no sections), tables, all links, and images. Returns one `PageRecord` with `crawled_at` set.

4. **Write (single loop in main)**  
   For each yielded `PageRecord`:
   - If `config.output_json` is set: call `write_one_record(fh, record, need_comma)` so the JSON file is a valid array written incrementally (flush per record).
   - If `config.postgres.enabled`: call `upsert(conn, record, config.scope_prefix)`.  
   Connection and file are opened before the loop; closed in `finally`.

5. **Postgres**  
   On first use (or when you run the app with Postgres enabled), `init_schema(conn)` runs `schema.sql` (CREATE TABLE and indexes). Each record is inserted with `ON CONFLICT (scope_prefix, url) DO UPDATE SET ...`, so re-runs update the same row and refresh `crawled_at`.

### Data flow (records)

```mermaid
flowchart TB
    Crawler[crawler.crawl]
    Crawler -->|yields| Record[PageRecord]
    Record --> Writer[writer.write_one_record]
    Record --> Upsert[db.upsert]
    Writer --> File[JSON file]
    Upsert --> PG[(PostgreSQL crawl_pages)]
```

### Config → behavior

| Config | Effect |
|--------|--------|
| `start_url`, `scope_prefix` | Where to start and which links to follow (prefix match). |
| `max_depth` (-1 = unlimited) | How many link hops from start. |
| `max_pages` | Stop after this many pages. |
| `polite_delay_ms` | Sleep after each page load. |
| `output_json` | Path for JSON output; if set, array is written incrementally. |
| `postgres.enabled` | If true, connect and upsert each record. |
| `postgres.url` | Postgres connection string (e.g. `postgresql://user:pass@host:5432/db`). |

### Querying stored data (Postgres)

- **By depth**: `SELECT * FROM crawl_pages WHERE scope_prefix = $1 AND depth = 1;`
- **Children of a URL**: `SELECT * FROM crawl_pages WHERE scope_prefix = $1 AND parent_url = $2;`
- **Full subtree**: Use a recursive CTE on `(scope_prefix, url, parent_url)`.

---

## Run

From project root:

```bash
python3 -m sjsu_crawler
python3 -m sjsu_crawler --config sjsu_crawler/config.yaml
```

With Postgres: set `postgres.enabled: true` and a valid `postgres.url` in `config.yaml`, then run the same command. The table is created automatically on first run.
