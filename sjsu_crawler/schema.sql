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

CREATE TABLE IF NOT EXISTS research_guides (
    url TEXT NOT NULL PRIMARY KEY,
    title TEXT,
    query TEXT NOT NULL,
    query_type TEXT NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL,
    full_content TEXT,
    sections JSONB,
    links_out JSONB,
    status TEXT,
    error_msg TEXT
);
CREATE INDEX IF NOT EXISTS idx_research_guides_query ON research_guides (query, query_type);

CREATE TABLE IF NOT EXISTS library_search_results (
    url TEXT NOT NULL,
    query TEXT NOT NULL,
    search_type TEXT NOT NULL,
    scope TEXT,
    PRIMARY KEY (url, query),
    title TEXT,
    fetched_at TIMESTAMPTZ,
    snippet TEXT,
    authors JSONB,
    source TEXT,
    year TEXT,
    download_path TEXT,
    full_text TEXT,
    status TEXT,
    error_msg TEXT
);
-- Ensure columns exist (for DBs created with a different schema)
ALTER TABLE library_search_results ADD COLUMN IF NOT EXISTS query TEXT;
ALTER TABLE library_search_results ADD COLUMN IF NOT EXISTS search_type TEXT;
ALTER TABLE library_search_results ADD COLUMN IF NOT EXISTS scope TEXT;
ALTER TABLE library_search_results ADD COLUMN IF NOT EXISTS fetched_at TIMESTAMPTZ;
ALTER TABLE library_search_results ADD COLUMN IF NOT EXISTS snippet TEXT;
ALTER TABLE library_search_results ADD COLUMN IF NOT EXISTS authors JSONB;
ALTER TABLE library_search_results ADD COLUMN IF NOT EXISTS source TEXT;
ALTER TABLE library_search_results ADD COLUMN IF NOT EXISTS year TEXT;
ALTER TABLE library_search_results ADD COLUMN IF NOT EXISTS download_path TEXT;
ALTER TABLE library_search_results ADD COLUMN IF NOT EXISTS full_text TEXT;
ALTER TABLE library_search_results ADD COLUMN IF NOT EXISTS status TEXT;
ALTER TABLE library_search_results ADD COLUMN IF NOT EXISTS error_msg TEXT;
CREATE INDEX IF NOT EXISTS idx_library_search_query ON library_search_results (query);
