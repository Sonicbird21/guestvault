from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from flask import (
    Flask,
    request,
    render_template,
    redirect,
    url_for,
    flash,
    send_from_directory,
    session,
    abort,
    make_response,
)
from werkzeug.utils import secure_filename
from datetime import datetime

from .db import (
    init_db,
    insert_file_record,
    list_files,
    get_file,
    increment_download_count,
    get_db_connection,
)
from .security import (
    generate_csrf_token,
    validate_csrf_from_request,
    require_admin,
    get_login_rate_limiter,
)
from .storage import ensure_dirs, store_file, delete_blob_if_unreferenced


def human_size(num: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num)
    for unit in units:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"


def set_security_headers(response):
    # Base CSP: self only, allow images/media blob: for previews
    csp = (
        "default-src 'self'; "
        "img-src 'self' data: blob:; media-src 'self' blob:; "
        "style-src 'self'; script-src 'self'; frame-ancestors 'none'"
    )
    response.headers.setdefault("Content-Security-Policy", csp)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


def set_raw_sandbox_headers(response):
    response.headers["Content-Security-Policy"] = "sandbox"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def init_app(app: Flask) -> None:
    @app.template_filter("human_size")
    def _tpl_human_size(val: Any):
        try:
            return human_size(int(val))
        except Exception:
            return str(val)

    @app.context_processor
    def inject_globals():
        return {
            "csrf_token": generate_csrf_token(),
            "admin_logged_in": session.get("is_admin", False),
            "is_admin": session.get("is_admin", False),
            "datetime": datetime,
        }

    app.after_request(set_security_headers)

    @app.get("/")
    def index():
        files = list_files()
        return render_template("index.html", files=files)

    @app.post("/upload")
    def upload():
        validate_csrf_from_request()
        if "file" not in request.files:
            abort(400, description="No file part")
        file = request.files["file"]
        if file.filename == "":
            abort(400, description="No selected file")
        filename = secure_filename(file.filename)
        meta, _abs_path = store_file(file, filename)
        file_id = insert_file_record(meta)
        return redirect(url_for("file_detail", file_id=file_id))

    @app.get("/files/<int:file_id>")
    def file_detail(file_id: int):
        row = get_file(file_id)
        if not row:
            abort(404)
        ct = row["content_type"] or "application/octet-stream"
        is_image = ct.startswith("image/")
        is_text = ct.startswith("text/") or ct in ("application/json", "application/xml")
        is_audio = ct.startswith("audio/")
        is_video = ct.startswith("video/")
        return render_template(
            "detail.html",
            file=row,
            is_image=is_image,
            is_text=is_text,
            is_audio=is_audio,
            is_video=is_video,
        )

    @app.get("/download/<int:file_id>")
    def download(file_id: int):
        row = get_file(file_id)
        if not row:
            abort(404)
        rel = row["stored_relpath"]
        directory = Path(app.config["UPLOAD_DIR"]) / Path(rel).parent
        filename = Path(rel).name
        increment_download_count(file_id)
        return send_from_directory(directory, filename, as_attachment=True, download_name=row["filename_original"])

    @app.get("/raw/<int:file_id>")
    def raw(file_id: int):
        row = get_file(file_id)
        if not row:
            abort(404)
        rel = row["stored_relpath"]
        directory = Path(app.config["UPLOAD_DIR"]) / Path(rel).parent
        filename = Path(rel).name
        resp = make_response(send_from_directory(directory, filename))
        return set_raw_sandbox_headers(resp)

    @app.post("/files/<int:file_id>/delete")
    def delete_file(file_id: int):
        require_admin()
        validate_csrf_from_request()
        row = get_file(file_id)
        if not row:
            abort(404)
        # Delete DB row
        conn = get_db_connection()
        try:
            conn.execute("DELETE FROM files WHERE id = ?", (file_id,))
            conn.commit()
        finally:
            conn.close()
        delete_blob_if_unreferenced(row["sha256"], row["stored_relpath"])
        flash("File deleted.", "success")
        return redirect(url_for("index"))

    @app.post("/files/bulk-delete")
    def bulk_delete():
        require_admin()
        validate_csrf_from_request()
        raw_ids = request.form.getlist("ids")
        ids: list[int] = []
        for v in raw_ids:
            try:
                ids.append(int(v))
            except Exception:
                continue
        if not ids:
            return redirect(url_for("index"))

        conn = get_db_connection()
        rows = []
        try:
            for fid in ids:
                row = conn.execute(
                    "SELECT id, sha256, stored_relpath FROM files WHERE id = ?",
                    (fid,),
                ).fetchone()
                if row:
                    rows.append(row)
                    conn.execute("DELETE FROM files WHERE id = ?", (fid,))
            conn.commit()
        finally:
            conn.close()
        for r in rows:
            delete_blob_if_unreferenced(r["sha256"], r["stored_relpath"])
        flash(f"Deleted {len(rows)} file(s).", "success")
        return redirect(url_for("index"))

    @app.get("/admin/login")
    def admin_login_form():
        return render_template("login.html")

    @app.post("/admin/login")
    def admin_login_post():
        validate_csrf_from_request()
        limiter = get_login_rate_limiter()
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0].strip()
        if not limiter.check(ip):
            abort(429, description="Too many attempts. Try later.")
        password = request.form.get("password", "")
        if password and password == os.environ.get("ADMIN_PASSWORD"):
            session["is_admin"] = True
            flash("Logged in.", "success")
            return redirect(url_for("index"))
        flash("Invalid password.", "error")
        return redirect(url_for("admin_login_form"))

    @app.route("/admin/logout", methods=["GET", "POST"])
    def admin_logout():
        session.pop("is_admin", None)
        flash("Logged out.", "success")
        return redirect(url_for("index"))

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    # Ensure directories and DB exist at app startup
    with app.app_context():
        ensure_dirs()
        init_db()
