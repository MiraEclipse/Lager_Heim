-- Lager Heim – Datenbankschema (SQLite)
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_info (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- ---------------------------------------------------------------- Benutzer
CREATE TABLE IF NOT EXISTS roles (
    code TEXT PRIMARY KEY,              -- ADMIN | USER
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id             INTEGER PRIMARY KEY,
    username       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    pw_hash        TEXT NOT NULL,
    role           TEXT NOT NULL REFERENCES roles(code),
    active         INTEGER NOT NULL DEFAULT 1,
    must_change_pw INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL,
    last_login     TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,         -- SHA-256 des Cookie-Werts
    user_id    INTEGER NOT NULL REFERENCES users(id),
    csrf_token TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen  TEXT NOT NULL,
    ip         TEXT
);

CREATE TABLE IF NOT EXISTS login_attempts (
    key          TEXT PRIMARY KEY,       -- "u:<benutzer>" oder "ip:<adresse>"
    fails        INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT
);

-- ---------------------------------------------------------------- Bestände
CREATE TABLE IF NOT EXISTS stores (
    code TEXT PRIMARY KEY,              -- KELLER | PRIVAT
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
    id     INTEGER PRIMARY KEY,
    name   TEXT NOT NULL UNIQUE,
    active INTEGER NOT NULL DEFAULT 1,
    sort   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS articles (
    ean         TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    category_id INTEGER REFERENCES categories(id),
    custom      TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL,
    created_by  TEXT NOT NULL
);

-- Bestandsposition: getrennt nach Bestand, EAN, MHD und Charge
CREATE TABLE IF NOT EXISTS lots (
    id         INTEGER PRIMARY KEY,
    store_code TEXT NOT NULL REFERENCES stores(code),
    ean        TEXT NOT NULL REFERENCES articles(ean),
    mhd        TEXT NOT NULL,
    charge     TEXT NOT NULL DEFAULT '',
    qty        INTEGER NOT NULL DEFAULT 0 CHECK (qty >= 0),
    created_at TEXT NOT NULL,
    UNIQUE (store_code, ean, mhd, charge)
);

-- Buchungen: unveränderlich
CREATE TABLE IF NOT EXISTS movements (
    id             INTEGER PRIMARY KEY,
    ts             TEXT NOT NULL,
    user_id        INTEGER NOT NULL,
    username       TEXT NOT NULL,
    store_code     TEXT NOT NULL,
    lot_id         INTEGER NOT NULL REFERENCES lots(id),
    ean            TEXT NOT NULL,
    mhd            TEXT NOT NULL,
    charge         TEXT NOT NULL,
    type           TEXT NOT NULL CHECK (type IN ('IN','OUT')),
    qty            INTEGER NOT NULL CHECK (qty > 0),
    qty_after      INTEGER NOT NULL,
    admin_eingriff INTEGER NOT NULL DEFAULT 0,
    begruendung    TEXT NOT NULL DEFAULT '',
    custom         TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_mov_lot ON movements(lot_id);

-- ---------------------------------------------------------------- Metadaten
CREATE TABLE IF NOT EXISTS meta_field (
    id            INTEGER PRIMARY KEY,
    entity        TEXT NOT NULL CHECK (entity IN ('artikel','buchung')),
    code          TEXT NOT NULL UNIQUE,
    label         TEXT NOT NULL,
    type          TEXT NOT NULL CHECK (type IN ('TEXT','NUMBER','DATE','SELECT','BOOL')),
    required      INTEGER NOT NULL DEFAULT 0,
    options       TEXT NOT NULL DEFAULT '[]',
    default_value TEXT NOT NULL DEFAULT '',
    system        INTEGER NOT NULL DEFAULT 0,
    active        INTEGER NOT NULL DEFAULT 1,
    sort          INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS meta_page (
    code   TEXT PRIMARY KEY,
    title  TEXT NOT NULL,
    kind   TEXT NOT NULL CHECK (kind IN ('LIST','FORM','SYSTEM')),
    config TEXT NOT NULL DEFAULT '{}',
    system INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS meta_menu (
    id        INTEGER PRIMARY KEY,
    parent_id INTEGER,
    label     TEXT NOT NULL,
    target    TEXT NOT NULL DEFAULT '',  -- Seitencode, leer bei Untermenü
    sort      INTEGER NOT NULL DEFAULT 0,
    active    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS meta_tcode (
    code        TEXT PRIMARY KEY,
    target      TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS meta_rule (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    trigger    TEXT NOT NULL CHECK (trigger IN ('ANZEIGE','BUCHUNG')),
    conditions TEXT NOT NULL DEFAULT '[]',
    action     TEXT NOT NULL DEFAULT '{}',
    active     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS permissions (
    role       TEXT NOT NULL,
    store_code TEXT NOT NULL,            -- '*' = bestandsunabhängig
    function   TEXT NOT NULL,
    allowed    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (role, store_code, function)
);

CREATE TABLE IF NOT EXISTS config_version (
    id        INTEGER PRIMARY KEY,
    ts        TEXT NOT NULL,
    user_id   INTEGER,
    username  TEXT NOT NULL,
    kommentar TEXT NOT NULL,
    snapshot  TEXT NOT NULL,
    hash      TEXT NOT NULL
);

-- ---------------------------------------------------------------- Protokoll
CREATE TABLE IF NOT EXISTS audit_log (
    seq            INTEGER PRIMARY KEY,
    ts             TEXT NOT NULL,
    user_id        INTEGER,
    username       TEXT NOT NULL,
    action         TEXT NOT NULL,
    object_type    TEXT NOT NULL,
    object_id      TEXT NOT NULL,
    store_code     TEXT NOT NULL,
    admin_eingriff INTEGER NOT NULL DEFAULT 0,
    old_value      TEXT NOT NULL,
    new_value      TEXT NOT NULL,
    ip             TEXT NOT NULL,
    prev_hash      TEXT NOT NULL,
    hash           TEXT NOT NULL UNIQUE
);

-- Append-only: Ändern und Löschen werden von der Datenbank abgewiesen
CREATE TRIGGER IF NOT EXISTS audit_log_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'Protokoll ist unveränderlich'); END;
CREATE TRIGGER IF NOT EXISTS audit_log_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'Protokoll ist unveränderlich'); END;
CREATE TRIGGER IF NOT EXISTS movements_no_update BEFORE UPDATE ON movements
BEGIN SELECT RAISE(ABORT, 'Buchungen sind unveränderlich'); END;
CREATE TRIGGER IF NOT EXISTS movements_no_delete BEFORE DELETE ON movements
BEGIN SELECT RAISE(ABORT, 'Buchungen sind unveränderlich'); END;
