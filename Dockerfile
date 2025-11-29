# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

# Install requirements
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir gunicorn==21.2.0

# Copy app
COPY . .

# Create a non-root user
RUN useradd -u 10001 -r -s /sbin/nologin appuser \
 && mkdir -p /app/uploads \
 && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# Healthcheck (optional)
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 CMD wget -qO- http://127.0.0.1:8000/healthz || exit 1

# Run with Gunicorn
CMD ["gunicorn", "-w", "2", "-k", "gthread", "--threads", "8", "-t", "60", "-b", "0.0.0.0:8000", "wsgi:app"]
