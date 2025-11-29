"""Development runner for guestvault.

Use this file to run the app in development with `python app.py`.
The actual application factory and routes live under the guestvault package.
"""

import os

from guestvault import create_app


if __name__ == "__main__":
	app = create_app()
	debug = (os.environ.get("DEBUG") or "").lower() in {"1", "true", "yes"}
	app.run(host="0.0.0.0", port=5000, debug=debug)

