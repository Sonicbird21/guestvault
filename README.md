guestvault - an anonymous file upload hosting service
=======

guestvault is a simple Flask-based file host: upload files, view metadata (hashes, type, size, uploaded date), preview common formats, and download.

## Quick start (dev)

1. Create and activate a virtual environment (recommended):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Create your .env from the example and set credentials:

```powershell
Copy-Item .env.example .env
notepad .env
# Set ADMIN_PASSWORD and SECRET_KEY
```

3. Install dependencies:

```powershell
pip install -r requirements.txt
```

4. Run the app:

```powershell
python app.py
```

4. Open http://localhost:5000/ in your browser.

## Production

Options below assume you have a strong `.env` with `SECRET_KEY` and `ADMIN_PASSWORD` set, and `DEBUG` is unset.

### Docker (recommended)

```bash
docker build -t guestvault:latest .
docker run --rm -p 8000:8000 \
	--env-file .env \
	-e BEHIND_PROXY=1 -e SESSION_COOKIE_SECURE=1 -e PREFERRED_URL_SCHEME=https \
	-v "$PWD/uploads:/app/uploads" \
	-v "$PWD/data.db:/app/data.db" \
	--name guestvault guestvault:latest
```

- Serve via a reverse proxy (e.g., Nginx/Caddy) terminating TLS and forwarding to `localhost:8000`.
- Health endpoint: `GET /healthz` returns `{"status":"ok"}`.

### Gunicorn (Linux)

```bash
pip install -r requirements-prod.txt
gunicorn -w 2 -k gthread --threads 8 -t 60 -b 0.0.0.0:8000 wsgi:app
```

### Waitress (Windows-friendly)

```powershell
pip install waitress==2.1.2
python -m waitress --listen=0.0.0.0:8000 wsgi:app
```

### Secure settings
- `SESSION_COOKIE_SECURE=1`, `SESSION_COOKIE_SAMESITE=Lax`, `SESSION_COOKIE_HTTPONLY=True` (defaults set in app; secure flag opt-in).
- Set `BEHIND_PROXY=1` when running behind a reverse proxy to honor `X-Forwarded-*` headers.
- Debug is off by default; set `DEBUG=1` only locally.

### Reverse proxy snippet (Nginx)

```nginx
location / {
		proxy_set_header Host $host;
		proxy_set_header X-Real-IP $remote_addr;
		proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
		proxy_set_header X-Forwarded-Proto $scheme;
		proxy_pass http://127.0.0.1:8000;
}
```

## Notes

- Files are stored under `uploads/` in subfolders by SHA-256 prefix.
- Metadata is stored in `data.db` (SQLite) at the project root.
- Max upload size is 512 MB (configurable in `app.py`).
- Supported previews: images, text, audio, video (browser dependent).
