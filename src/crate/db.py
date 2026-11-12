"""SQLite storage: files, provenance, batches and the operation journal."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    current_path TEXT NOT NULL UNIQUE,
    original_path TEXT NOT NULL,
    original_name TEXT NOT NULL,
    pack TEXT,
    raw_hash TEXT,
    content_hash TEXT,           -- decoded-PCM hash, filled from Milestone 2
    size INTEGER
);
CREATE INDEX IF NOT EXISTS idx_files_raw ON files(raw_hash);
CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    command TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running'   -- running | done | undone | undoing
);
CREATE TABLE IF NOT EXISTS ops (
    id INTEGER PRIMARY KEY,
    batch_id INTEGER NOT NULL REFERENCES batches(id),
    seq INTEGER NOT NULL,
    kind TEXT NOT NULL,          -- move | copy | mkdir | rmdir
    src TEXT,
    dst TEXT,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | done | undone
    note TEXT
);
CREATE INDEX IF NOT EXISTS idx_ops_batch ON ops(batch_id, seq);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn
