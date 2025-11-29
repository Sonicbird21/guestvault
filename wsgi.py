from guestvault import create_app

app = create_app()

# This module exposes the Flask app for WSGI servers
# Example: gunicorn -w 2 -k gthread -t 60 -b 0.0.0.0:8000 wsgi:app
