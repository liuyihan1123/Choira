"""SQLite 存储层：表结构、连接、通用小工具。"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]          # backend/
DATA_DIR = Path(os.environ.get("CHOIR_DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
WORK_DIR = DATA_DIR / "work"
ASSET_DIR = DATA_DIR / "assets"
AUDIO_DIR = DATA_DIR / "audio"
DEMO_DIR = DATA_DIR / "demo"
DB_PATH = DATA_DIR / "choir.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS scores (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    composer    TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS versions (
    id           TEXT PRIMARY KEY,
    score_id     TEXT NOT NULL REFERENCES scores(id) ON DELETE CASCADE,
    version_no   INTEGER NOT NULL,
    status       TEXT NOT NULL,              -- draft | published | pending_omr
    source_kind  TEXT NOT NULL,              -- musicxml | mxl | pdf | pdf+musicxml
    source_name  TEXT NOT NULL DEFAULT '',
    source_path  TEXT NOT NULL DEFAULT '',   -- 原始上传文件
    musicxml_path TEXT NOT NULL DEFAULT '',  -- 可解析的 MusicXML（PDF 回填后才有）
    source_hash  TEXT NOT NULL DEFAULT '',
    title        TEXT NOT NULL DEFAULT '',
    composer     TEXT NOT NULL DEFAULT '',
    notes        TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    published_at TEXT,
    UNIQUE (score_id, version_no)
);

CREATE TABLE IF NOT EXISTS parts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id     TEXT NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    part_id        TEXT NOT NULL,
    idx            INTEGER NOT NULL DEFAULT 0,
    name           TEXT NOT NULL,
    abbreviation   TEXT NOT NULL DEFAULT '',
    staves         INTEGER NOT NULL DEFAULT 1,
    voices         TEXT NOT NULL DEFAULT '[]',
    note_count     INTEGER NOT NULL DEFAULT 0,
    multi_voice    INTEGER NOT NULL DEFAULT 0,
    extractable    INTEGER NOT NULL DEFAULT 1,
    suggested_role TEXT,
    confidence     REAL NOT NULL DEFAULT 0,
    warnings       TEXT NOT NULL DEFAULT '[]',
    UNIQUE (version_id, part_id)
);

CREATE TABLE IF NOT EXISTS assignments (
    version_id TEXT NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    role       TEXT NOT NULL,
    part_id    TEXT NOT NULL,
    PRIMARY KEY (version_id, role, part_id)
);

CREATE TABLE IF NOT EXISTS assets (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id TEXT NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    role       TEXT NOT NULL,
    part_id    TEXT NOT NULL,
    path       TEXT NOT NULL,
    sha256     TEXT NOT NULL,
    size       INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (version_id, role, part_id)
);

CREATE TABLE IF NOT EXISTS part_audio (
    version_id TEXT NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    part_id    TEXT NOT NULL,
    path       TEXT NOT NULL,
    mime       TEXT NOT NULL DEFAULT 'audio/mpeg',
    sha256     TEXT NOT NULL,
    size       INTEGER NOT NULL,
    duration   REAL NOT NULL DEFAULT 0,
    note_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    PRIMARY KEY (version_id, part_id)
);

CREATE TABLE IF NOT EXISTS tokens (
    token      TEXT PRIMARY KEY,
    asset_id   INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    role       TEXT NOT NULL DEFAULT '',
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    action     TEXT NOT NULL,
    role       TEXT NOT NULL DEFAULT '',
    version_id TEXT NOT NULL DEFAULT '',
    part_id    TEXT NOT NULL DEFAULT '',
    ip         TEXT NOT NULL DEFAULT '',
    detail     TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_versions_score ON versions(score_id);
CREATE INDEX IF NOT EXISTS idx_assign_role ON assignments(role);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts DESC);
CREATE INDEX IF NOT EXISTS idx_audio_version ON part_audio(version_id);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def ensure_dirs() -> None:
    for path in (DATA_DIR, UPLOAD_DIR, WORK_DIR, ASSET_DIR, AUDIO_DIR, DEMO_DIR):
        path.mkdir(parents=True, exist_ok=True)


def connect() -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    ensure_dirs()
    with db() as conn:
        conn.executescript(SCHEMA)


def rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


def audit(action: str, *, role: str = "", version_id: str = "", part_id: str = "",
          ip: str = "", detail: str = "") -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO audit (ts, action, role, version_id, part_id, ip, detail) VALUES (?,?,?,?,?,?,?)",
            (now_iso(), action, role, version_id, part_id, ip, detail),
        )
