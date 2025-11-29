from __future__ import annotations

import sqlite3
from flask import current_app


def get_db_connection() -> sqlite3.Connection:
    path = current_app.config["DB_PATH"]
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_db_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename_original TEXT NOT NULL,
                stored_relpath TEXT NOT NULL,
                content_type TEXT,
                size INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                md5 TEXT,
                uploaded_at TEXT NOT NULL,
                download_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_files_sha256 ON files(sha256)")
        conn.commit()
    finally:
        conn.close()


def insert_file_record(meta: dict) -> int:
    conn = get_db_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO files (
                filename_original, stored_relpath, content_type, size, sha256, md5, uploaded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                meta["filename_original"],
                meta["stored_relpath"],
                meta.get("content_type"),
                meta["size"],
                meta["sha256"],
                meta.get("md5"),
                meta["uploaded_at"],
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def list_files():
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM files ORDER BY datetime(uploaded_at) DESC, id DESC"
        ).fetchall()
        return rows
    finally:
        conn.close()


def get_file(file_id: int):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
        return row
    finally:
        conn.close()


def increment_download_count(file_id: int) -> None:
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE files SET download_count = download_count + 1 WHERE id = ?",
            (file_id,),
        )
        conn.commit()
    finally:
        conn.close()
