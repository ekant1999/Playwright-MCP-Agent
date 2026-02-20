CREATE TABLE IF NOT EXISTS crawl_pages (
    scope_prefix TEXT NOT NULL,
    url TEXT NOT NULL,
    parent_url TEXT,
    depth INT NOT NULL,
    crawled_at TIMESTAMPTZ NOT NULL,
    title TEXT,
    meta_description TEXT,
    full_text TEXT,
    headings JSONB,
    sections JSONB,
    paragraphs JSONB,
    tables JSONB,
    links_out JSONB,
    images JSONB,
    status TEXT,
    error_msg TEXT,
    PRIMARY KEY (scope_prefix, url)
);
CREATE INDEX IF NOT EXISTS idx_crawl_pages_scope_depth ON crawl_pages (scope_prefix, depth);
CREATE INDEX IF NOT EXISTS idx_crawl_pages_scope_parent ON crawl_pages (scope_prefix, parent_url);
