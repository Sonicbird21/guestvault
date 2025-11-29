"""guestvault Flask application factory.

This package wires together routes, storage, database access, and security
helpers. Behavior is equivalent to the previous single-file app.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from . import routes


def create_app() -> Flask:
    base_dir = Path(__file__).resolve().parent.parent
    load_dotenv(base_dir / ".env")

    app = Flask(__name__, template_folder=str(base_dir / "templates"), static_folder=str(base_dir / "static"))

    # Core config
    def _parse_size_env(val: str, default: int) -> int:
        val = (val or "").strip()
        if not val:
            return default
        # Allow raw integer bytes
        try:
            return int(val)
        except ValueError:
            pass
        # Allow forms like 256MB, 1GB, 0.5GB
        m = re.match(r"^(\d+(?:\.\d+)?)\s*([KMG]B)$", val.upper())
        if m:
            num = float(m.group(1))
            unit = m.group(2)
            mult = {"KB": 1024, "MB": 1024**2, "GB": 1024**3}[unit]
            return int(num * mult)
        logging.warning("Invalid MAX_CONTENT_LENGTH value '%s'; using default", val)
        return default

    app.config["MAX_CONTENT_LENGTH"] = _parse_size_env(os.environ.get("MAX_CONTENT_LENGTH"), 512 * 1024 * 1024)
    app.secret_key = os.environ.get("SECRET_KEY") or ""
    if not app.secret_key:
        raise RuntimeError("SECRET_KEY is required. Set it in .env")
    if not (os.environ.get("ADMIN_PASSWORD") or "").strip():
        raise RuntimeError("ADMIN_PASSWORD is required. Set it in .env")

    # Paths
    app.config["BASE_DIR"] = base_dir
    app.config["UPLOAD_DIR"] = base_dir / "uploads"
    app.config["DB_PATH"] = base_dir / "data.db"

    # Cookies
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", os.environ.get("SESSION_COOKIE_SAMESITE", "Lax"))
    if (os.environ.get("SESSION_COOKIE_SECURE") or "").lower() in {"1", "true", "yes"}:
        app.config["SESSION_COOKIE_SECURE"] = True
    if (os.environ.get("PREFERRED_URL_SCHEME") or "").lower() in {"http", "https"}:
        app.config["PREFERRED_URL_SCHEME"] = os.environ.get("PREFERRED_URL_SCHEME")

    # Reverse proxy support
    if (os.environ.get("BEHIND_PROXY") or "").lower() in {"1", "true", "yes"}:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    # Logging
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

    # Register routes/filters/context
    routes.init_app(app)

    return app
