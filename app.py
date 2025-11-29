import os
import secrets
import sqlite3
import hashlib
import time
import mimetypes
from datetime import datetime
from pathlib import Path

from flask import (
	Flask,
	request,
	redirect,
	url_for,
	render_template,
	send_from_directory,
	abort,
	session,
)
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from collections import deque
import logging
from werkzeug.middleware.proxy_fix import ProxyFix


BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
DB_PATH = BASE_DIR / "data.db"

# Load environment variables from .env in project root
load_dotenv(BASE_DIR / ".env")


def ensure_dirs():
	UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def get_db_connection():
	conn = sqlite3.connect(DB_PATH)
	conn.row_factory = sqlite3.Row
	return conn


def init_db():
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


def _hash_fileobj(fileobj):
	sha = hashlib.sha256()
	md5 = hashlib.md5()
	total = 0
	fileobj.seek(0)
	while True:
		chunk = fileobj.read(1024 * 1024)
		if not chunk:
			break
		sha.update(chunk)
		md5.update(chunk)
		total += len(chunk)
	fileobj.seek(0)
	return sha.hexdigest(), md5.hexdigest(), total


def _store_file(fileobj, sha256_hex: str, orig_filename: str) -> str:
	ext = Path(orig_filename).suffix
	subdir = UPLOAD_DIR / sha256_hex[:2]
	subdir.mkdir(parents=True, exist_ok=True)
	stored_name = f"{sha256_hex}{ext}"
	stored_path = subdir / stored_name
	# Stream write
	fileobj.seek(0)
	with open(stored_path, "wb") as out:
		while True:
			buf = fileobj.read(1024 * 1024)
			if not buf:
				break
			out.write(buf)
	relpath = os.path.relpath(stored_path, BASE_DIR)
	return relpath.replace("\\", "/")


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


def increment_download_count(file_id: int):
	conn = get_db_connection()
	try:
		conn.execute(
			"UPDATE files SET download_count = download_count + 1 WHERE id = ?",
			(file_id,),
		)
		conn.commit()
	finally:
		conn.close()


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024  # 512 MB
app.secret_key = os.environ.get("SECRET_KEY") or ""

# Fail fast if critical secrets are missing
if not app.secret_key:
	raise RuntimeError("SECRET_KEY is required. Set it in .env")
if not (os.environ.get("ADMIN_PASSWORD") or "").strip():
	raise RuntimeError("ADMIN_PASSWORD is required. Set it in .env")

# Secure cookie settings (tune via env)
app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
app.config.setdefault("SESSION_COOKIE_SAMESITE", os.environ.get("SESSION_COOKIE_SAMESITE", "Lax"))
if (os.environ.get("SESSION_COOKIE_SECURE") or "").lower() in {"1", "true", "yes"}:
	app.config["SESSION_COOKIE_SECURE"] = True
if (os.environ.get("PREFERRED_URL_SCHEME") or "").lower() in {"http", "https"}:
	app.config["PREFERRED_URL_SCHEME"] = os.environ.get("PREFERRED_URL_SCHEME")

# Respect reverse proxy headers when enabled
if (os.environ.get("BEHIND_PROXY") or "").lower() in {"1", "true", "yes"}:
	app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

# Basic logging
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

# Login rate limiting (in-memory, per-process)
LOGIN_MAX_ATTEMPTS = int(os.environ.get("LOGIN_MAX_ATTEMPTS", "8"))
LOGIN_WINDOW_SECONDS = int(os.environ.get("LOGIN_WINDOW_SECONDS", "300"))  # 5 min
_login_attempts = {}


def is_admin() -> bool:
	return bool(session.get("is_admin"))


def get_csrf_token() -> str:
	token = session.get("csrf_token")
	if not token:
		token = secrets.token_urlsafe(32)
		session["csrf_token"] = token
	return token


def require_csrf():
	expected = session.get("csrf_token")
	provided = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
	if not expected or not provided or provided != expected:
		abort(403)


@app.template_filter("human_size")
def _human_size_filter(num):
	try:
		size = float(num)
	except Exception:
		return f"{num} B"
	units = ["B", "KB", "MB", "GB", "TB", "PB"]
	for unit in units:
		if size < 1024 or unit == units[-1]:
			return f"{size:.2f} {unit}"
		size /= 1024


@app.context_processor
def inject_globals():
	return {"datetime": datetime, "is_admin": is_admin(), "csrf_token": get_csrf_token()}


def _client_ip() -> str:
	xff = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
	return xff or (request.remote_addr or "unknown")


def _check_login_rate_limit() -> tuple[bool, int]:
	now = time.time()
	ip = _client_ip()
	dq = _login_attempts.setdefault(ip, deque())
	# drop old entries
	while dq and now - dq[0] > LOGIN_WINDOW_SECONDS:
		dq.popleft()
	if len(dq) >= LOGIN_MAX_ATTEMPTS:
		retry_after = int(LOGIN_WINDOW_SECONDS - (now - dq[0]) + 1)
		return True, max(retry_after, 1)
	return False, 0


def _record_login_attempt():
	ip = _client_ip()
	dq = _login_attempts.setdefault(ip, deque())
	dq.append(time.time())


def _clear_login_attempts():
	ip = _client_ip()
	if ip in _login_attempts:
		_login_attempts[ip].clear()


@app.route("/")
def index():
	files = list_files()
	return render_template("index.html", files=files)


@app.post("/upload")
def upload():
	require_csrf()
	if "file" not in request.files:
		abort(400, "No file part in the request")
	f = request.files["file"]
	if not f or f.filename == "":
		abort(400, "No selected file")

	original_name = secure_filename(f.filename)
	if not original_name:
		abort(400, "Invalid filename")

	# Hash and size
	sha256_hex, md5_hex, total_size = _hash_fileobj(f.stream)

	# Store
	stored_relpath = _store_file(f.stream, sha256_hex, original_name)

	# Content type guess
	guessed_ct, _ = mimetypes.guess_type(original_name)
	content_type = guessed_ct or "application/octet-stream"

	meta = {
		"filename_original": original_name,
		"stored_relpath": stored_relpath,
		"content_type": content_type,
		"size": total_size,
		"sha256": sha256_hex,
		"md5": md5_hex,
		"uploaded_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
	}
	file_id = insert_file_record(meta)
	return redirect(url_for("file_detail", file_id=file_id))


@app.get("/files/<int:file_id>")
def file_detail(file_id: int):
	row = get_file(file_id)
	if not row:
		abort(404)
	# Determine preview capability
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


def _send_file_common(row, as_attachment: bool):
	relpath = row["stored_relpath"]
	abs_path = (BASE_DIR / relpath).resolve()
	if not abs_path.is_file() or not str(abs_path).startswith(str(BASE_DIR)):
		abort(404)
	directory = abs_path.parent
	filename = abs_path.name
	download_name = row["filename_original"]
	return send_from_directory(
		directory,
		filename,
		mimetype=row["content_type"] or None,
		as_attachment=as_attachment,
		download_name=download_name if as_attachment else None,
		conditional=True,
		etag=True,
		last_modified=None,
	)


@app.get("/download/<int:file_id>")
def download(file_id: int):
	row = get_file(file_id)
	if not row:
		abort(404)
	increment_download_count(file_id)
	return _send_file_common(row, as_attachment=True)


@app.get("/raw/<int:file_id>")
def raw(file_id: int):
	row = get_file(file_id)
	if not row:
		abort(404)
	resp = _send_file_common(row, as_attachment=False)
	# Extra hardening for untrusted raw content; isolate with sandbox
	resp.headers["Content-Security-Policy"] = "sandbox"
	resp.headers.setdefault("X-Content-Type-Options", "nosniff")
	return resp


def delete_file_and_blob_if_unused(file_id: int) -> bool:
	conn = get_db_connection()
	try:
		row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
		if not row:
			return False
		relpath = row["stored_relpath"]
		cnt_row = conn.execute(
			"SELECT COUNT(*) AS c FROM files WHERE stored_relpath = ?",
			(relpath,),
		).fetchone()
		ref_count = int(cnt_row[0]) if cnt_row else 0
		conn.execute("DELETE FROM files WHERE id = ?", (file_id,))
		conn.commit()
	finally:
		conn.close()

	if relpath and ref_count <= 1:
		try:
			abs_path = (BASE_DIR / relpath).resolve()
			if abs_path.is_file() and str(abs_path).startswith(str(BASE_DIR)):
				abs_path.unlink(missing_ok=True)
				try:
					abs_path.parent.rmdir()
				except Exception:
					pass
		except Exception:
			pass
	return True


@app.post("/files/<int:file_id>/delete")
def delete_file(file_id: int):
	if not is_admin():
		abort(403)
	require_csrf()
	ok = delete_file_and_blob_if_unused(file_id)
	if not ok:
		abort(404)
	return redirect(url_for("index"))


@app.post("/files/bulk-delete")
def bulk_delete():
	if not is_admin():
		abort(403)
	require_csrf()
	ids = request.form.getlist("ids")
	deleted = 0
	for sid in ids:
		try:
			fid = int(sid)
		except Exception:
			continue
		if delete_file_and_blob_if_unused(fid):
			deleted += 1
	return redirect(url_for("index"))


@app.get("/admin/login")
def admin_login_form():
	if is_admin():
		return redirect(url_for("index"))
	return render_template("login.html")


@app.post("/admin/login")
def admin_login_post():
	require_csrf()
	limited, retry_after = _check_login_rate_limit()
	if limited:
		from flask import Response
		resp = Response("Too many login attempts. Try again later.", status=429)
		resp.headers["Retry-After"] = str(retry_after)
		return resp
	pwd = (request.form.get("password") or "").strip()
	expected = os.environ.get("ADMIN_PASSWORD") or ""
	if expected and pwd == expected:
		session["is_admin"] = True
		_clear_login_attempts()
		return redirect(url_for("index"))
	_record_login_attempt()
	abort(403)


@app.route("/admin/logout", methods=["POST", "GET"]) 
def admin_logout():
	session.pop("is_admin", None)
	return redirect(url_for("index"))


@app.after_request
def set_security_headers(resp):
	resp.headers.setdefault("X-Frame-Options", "DENY")
	resp.headers.setdefault("X-Content-Type-Options", "nosniff")
	resp.headers.setdefault("Referrer-Policy", "no-referrer")
	# Strict CSP for app pages; scripts/styles are served from self
	csp = " ".join([
		"default-src 'self'",
		"script-src 'self'",
		"style-src 'self'",
		"img-src 'self' data: blob:",
		"font-src 'self'",
		"object-src 'none'",
		"base-uri 'none'",
		"frame-ancestors 'none'",
	])
	# Preserve any route-specific CSP if already set
	resp.headers.setdefault("Content-Security-Policy", csp)
	return resp


@app.get("/healthz")
def healthz():
	return {"status": "ok", "time": datetime.utcnow().isoformat(timespec="seconds") + "Z"}


if __name__ == "__main__":
	ensure_dirs()
	init_db()
	debug = (os.environ.get("DEBUG") or "").lower() in {"1", "true", "yes"}
	app.run(host="0.0.0.0", port=5000, debug=debug)

