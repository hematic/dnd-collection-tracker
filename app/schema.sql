CREATE TABLE IF NOT EXISTS work (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    edition     TEXT NOT NULL,
    book_type   TEXT NOT NULL,
    first_year  INTEGER,
    setting     TEXT,
    notes       TEXT,
    primary_release_override INTEGER NOT NULL DEFAULT 0,
    source      TEXT NOT NULL DEFAULT 'catalog',  -- 'catalog' | 'user'
    parent_id   TEXT REFERENCES work(id) ON DELETE SET NULL  -- box set this book ships in
);

CREATE TABLE IF NOT EXISTS release (
    id              TEXT PRIMARY KEY,
    work_id         TEXT NOT NULL REFERENCES work(id) ON DELETE CASCADE,
    release_kind    TEXT NOT NULL DEFAULT 'Original',
    label           TEXT,
    year            INTEGER,
    publisher       TEXT,
    product_code    TEXT,
    isbn            TEXT,
    is_primary      INTEGER NOT NULL DEFAULT 0,
    pdf_path        TEXT,
    cover_path      TEXT,
    cover_source    TEXT,               -- 'pdf' | 'upload' | NULL
    owned_physical  INTEGER NOT NULL DEFAULT 0,
    owned_pdf       INTEGER NOT NULL DEFAULT 0,
    notes           TEXT,
    source          TEXT NOT NULL DEFAULT 'catalog'
);

CREATE INDEX IF NOT EXISTS idx_release_work ON release(work_id);

-- No foreign keys: these records must survive deletion of the catalog entry.
CREATE TABLE IF NOT EXISTS catalog_deletion (
    entity_type TEXT NOT NULL CHECK (entity_type IN ('work', 'release')),
    entity_id   TEXT NOT NULL,
    PRIMARY KEY (entity_type, entity_id)
);

-- Legacy catalog decisions remain part of the collection after tool retirement.
CREATE TABLE IF NOT EXISTS catalog_work_mapping (
    catalog_id TEXT PRIMARY KEY,
    local_id TEXT NOT NULL UNIQUE REFERENCES work(id) ON DELETE CASCADE,
    backup_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS catalog_release_mapping (
    catalog_id TEXT PRIMARY KEY,
    local_id TEXT NOT NULL UNIQUE REFERENCES release(id) ON DELETE CASCADE,
    backup_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TRIGGER IF NOT EXISTS mapped_work_deleted BEFORE DELETE ON work BEGIN
    INSERT OR IGNORE INTO catalog_deletion(entity_type, entity_id)
        SELECT 'work', catalog_id FROM catalog_work_mapping WHERE local_id = old.id;
END;

CREATE TRIGGER IF NOT EXISTS mapped_release_deleted BEFORE DELETE ON release BEGIN
    INSERT OR IGNORE INTO catalog_deletion(entity_type, entity_id)
        SELECT 'release', catalog_id FROM catalog_release_mapping WHERE local_id = old.id;
END;

CREATE TABLE IF NOT EXISTS catalog_metadata_repair (
    repair_id       TEXT PRIMARY KEY,
    batch_id        TEXT NOT NULL,
    work_id         TEXT NOT NULL REFERENCES work(id) ON DELETE CASCADE,
    release_id      TEXT NOT NULL REFERENCES release(id) ON DELETE CASCADE,
    backup_name     TEXT NOT NULL,
    changes_json    TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- No foreign keys: the full repair audit must survive later user deletions.
CREATE TABLE IF NOT EXISTS catalog_copy_repair (
    repair_id       TEXT PRIMARY KEY,
    backup_name     TEXT NOT NULL,
    details_json    TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS catalog_work_redirect (
    old_id          TEXT PRIMARY KEY,
    work_id         TEXT NOT NULL REFERENCES work(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS pdf_index (
    release_id      TEXT PRIMARY KEY REFERENCES release(id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued', 'processing', 'done', 'error')),
    file_size       INTEGER,
    file_mtime_ns   INTEGER,
    page_count      INTEGER NOT NULL DEFAULT 0,
    indexed_pages   INTEGER NOT NULL DEFAULT 0,
    ocr_pages       INTEGER,
    force_reindex   INTEGER NOT NULL DEFAULT 0,
    error           TEXT,
    updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pdf_index_control (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    paused              INTEGER NOT NULL DEFAULT 1,
    worker_id           TEXT,
    worker_heartbeat    REAL
);

INSERT OR IGNORE INTO pdf_index_control (id, paused) VALUES (1, 1);

CREATE TABLE IF NOT EXISTS pdf_text_page (
    id              INTEGER PRIMARY KEY,
    release_id      TEXT NOT NULL REFERENCES release(id) ON DELETE CASCADE,
    page_number     INTEGER NOT NULL,
    text            TEXT NOT NULL,
    UNIQUE (release_id, page_number)
);

CREATE VIRTUAL TABLE IF NOT EXISTS pdf_text_fts USING fts5(
    text,
    content='pdf_text_page',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS pdf_text_page_ai AFTER INSERT ON pdf_text_page BEGIN
    INSERT INTO pdf_text_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE TRIGGER IF NOT EXISTS pdf_text_page_ad AFTER DELETE ON pdf_text_page BEGIN
    INSERT INTO pdf_text_fts(pdf_text_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;

CREATE TRIGGER IF NOT EXISTS pdf_text_page_au AFTER UPDATE ON pdf_text_page BEGIN
    INSERT INTO pdf_text_fts(pdf_text_fts, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO pdf_text_fts(rowid, text) VALUES (new.id, new.text);
END;
