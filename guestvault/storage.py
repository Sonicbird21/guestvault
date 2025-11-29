from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Tuple

from flask import current_app


def ensure_dirs() -> None:
    Path(current_app.config["UPLOAD_DIR"]).mkdir(parents=True, exist_ok=True)
    Path(Path(current_app.config["DB_PATH"]).parent).mkdir(parents=True, exist_ok=True)


def _hash_fileobj(f: BinaryIO) -> Tuple[str, str, int]:
    # Compute content hashes for display. SHA-256 is the integrity hash.
    # MD5 is included ONLY as a legacy checksum for convenience in UIs/tools,
    # not for any security purpose.  # nosec B303
    sha256 = hashlib.sha256()
    md5 = hashlib.md5()  # nosec B303: non-security display checksum
    size = 0
    for chunk in iter(lambda: f.read(1024 * 1024), b""):
        sha256.update(chunk)
        md5.update(chunk)
        size += len(chunk)
    f.seek(0)
    return sha256.hexdigest(), md5.hexdigest(), size


def store_file(file_storage, filename_sanitized: str) -> tuple[dict, str]:
    # file_storage is werkzeug FileStorage
    f = file_storage.stream
    sha256_hex, md5_hex, size = _hash_fileobj(f)

    # Keep original extension if any
    ext = os.path.splitext(filename_sanitized)[1]
    sha_prefix = sha256_hex[:2]
    stored_filename = f"{sha256_hex}{ext}"
    rel_path = os.path.join(sha_prefix, stored_filename)
    abs_dir = Path(current_app.config["UPLOAD_DIR"]) / sha_prefix
    abs_dir.mkdir(parents=True, exist_ok=True)
    abs_path = abs_dir / stored_filename

    file_storage.save(abs_path)

    meta = {
        "filename_original": filename_sanitized,
        "stored_relpath": rel_path.replace("\\", "/"),
        "content_type": file_storage.mimetype,
        "size": size,
        "sha256": sha256_hex,
        # MD5 is provided for compatibility display only (non-security)
        "md5": md5_hex,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    return meta, str(abs_path)


def delete_blob_if_unreferenced(sha256_hex: str, rel_path: str) -> None:
    # Called after DB row removal; only delete blob if no more references to same sha256
    from .db import get_db_connection

    conn = get_db_connection()
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM files WHERE sha256 = ?", (sha256_hex,)
        ).fetchone()[0]
    finally:
        conn.close()

    if count == 0:
        abs_path = Path(current_app.config["UPLOAD_DIR"]) / rel_path
        try:
            abs_path.unlink(missing_ok=True)
            # Attempt to clean empty prefix dir
            abs_path.parent.rmdir()
        except Exception:
            pass
