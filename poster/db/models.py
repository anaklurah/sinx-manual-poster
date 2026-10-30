"""
SQLite Database Schema and Connection Management for Sin'X Manual Poster.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

SCHEMA = """
-- ---------------------------------------------------------------------------
-- accounts
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS accounts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL UNIQUE,
    is_active       INTEGER DEFAULT 1,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------------------
-- account_settings
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS account_settings (
    account_id                  INTEGER PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
    timezone                    TEXT DEFAULT 'Asia/Jakarta',
    delay_between_platforms_sec INTEGER DEFAULT 25,
    telegram_enabled            INTEGER DEFAULT 0,
    telegram_bot_token          TEXT DEFAULT '',
    telegram_chat_id            TEXT DEFAULT '',
    proxy_url                   TEXT DEFAULT '',
    updated_at                  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------------------
-- platform_targets
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS platform_targets (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    target_key          TEXT    NOT NULL UNIQUE,
    platform            TEXT    NOT NULL,
    name                TEXT    NOT NULL,
    enabled             INTEGER DEFAULT 1,
    is_custom           INTEGER DEFAULT 0,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------------------
-- posts (Manual Content Records)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS posts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id          INTEGER DEFAULT 1 REFERENCES accounts(id) ON DELETE SET NULL,
    title               TEXT    NOT NULL,
    description         TEXT    DEFAULT '',
    tags                TEXT    DEFAULT '[]',
    video_path          TEXT    NOT NULL,
    video_filename      TEXT    NOT NULL,
    video_size_bytes    INTEGER DEFAULT 0,
    status              TEXT    NOT NULL DEFAULT 'draft', -- draft, scheduled, uploading, done, partial, failed
    target_platforms    TEXT    NOT NULL DEFAULT '[]',    -- JSON array e.g. ["youtube", "tiktok"]
    scheduled_at        DATETIME,                         -- ISO datetime or NULL if instant
    published_at        DATETIME,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------------------
-- post_platforms (Per-platform publish state for each post)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS post_platforms (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id             INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    account_id          INTEGER DEFAULT 1 REFERENCES accounts(id) ON DELETE SET NULL,
    target_key          TEXT    NOT NULL,
    platform            TEXT    NOT NULL,
    status              TEXT    NOT NULL DEFAULT 'pending', -- pending, uploading, done, failed, skipped
    upload_url          TEXT,
    error_msg           TEXT,
    attempts            INTEGER DEFAULT 0,
    published_at        DATETIME,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(post_id, target_key)
);

-- ---------------------------------------------------------------------------
-- users & sessions
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    username        TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    password_hash   TEXT    NOT NULL,
    is_admin        INTEGER DEFAULT 0,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id  INTEGER NOT NULL,
    token       TEXT    NOT NULL UNIQUE,
    expires_at  DATETIME NOT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------------------
-- audit_logs
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    username    TEXT,
    account_id  INTEGER,
    action      TEXT NOT NULL,
    details     TEXT DEFAULT '',
    ip_address  TEXT DEFAULT '',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------------------
-- error_log
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS error_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id     INTEGER REFERENCES posts(id) ON DELETE SET NULL,
    target_key  TEXT,
    module      TEXT NOT NULL,
    error_msg   TEXT NOT NULL,
    stack_trace TEXT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status);
CREATE INDEX IF NOT EXISTS idx_posts_scheduled ON posts(scheduled_at);
CREATE INDEX IF NOT EXISTS idx_posts_account ON posts(account_id);
CREATE INDEX IF NOT EXISTS idx_post_platforms_post ON post_platforms(post_id);
CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs(created_at DESC);
"""

DEFAULT_TARGETS = [
    ("youtube", "youtube", "YouTube Shorts", 1, 0),
    ("tiktok", "tiktok", "TikTok", 1, 0),
    ("instagram", "instagram", "Instagram Reels", 1, 0),
    ("facebook", "facebook", "Facebook Reels", 1, 0),
    ("twitter", "twitter", "Twitter / X", 1, 0),
    ("twitter_nsfw", "twitter_nsfw", "Twitter NSFW", 0, 0),
    ("upscrolled", "upscrolled", "Upscrolled", 0, 0),
    ("febspot", "febspot", "Febspot", 0, 0),
]


def get_conn(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(
        str(db_path),
        check_same_thread=False,
        timeout=30.0,
    )
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db_session(db_path: str | Path) -> Generator[sqlite3.Connection, None, None]:
    conn = get_conn(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str | Path) -> None:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = get_conn(db_path)
    try:
        conn.executescript(SCHEMA)

        # Default account 1
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM accounts")
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO accounts (id, name, is_active) VALUES (1, 'Utama (Default)', 1)")

        # Default platform targets
        cursor.execute("SELECT COUNT(*) FROM platform_targets")
        if cursor.fetchone()[0] == 0:
            cursor.executemany(
                "INSERT INTO platform_targets (target_key, platform, name, enabled, is_custom) VALUES (?, ?, ?, ?, ?)",
                DEFAULT_TARGETS,
            )

        conn.commit()
    finally:
        conn.close()
