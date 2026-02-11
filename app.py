#!/usr/bin/env python3
"""GitHub PR Explorer - Flask Backend

Thin launcher that creates the app via the backend package factory
and starts the development server.
"""

import threading

from backend import create_app, startup_refresh_workflow_caches
from backend.config import get_config

app = create_app()

if __name__ == "__main__":
    config = get_config()

    # Refresh stale workflow caches in background on startup
    threading.Thread(target=startup_refresh_workflow_caches, daemon=True).start()

    app.run(
        host=config.get("host", "127.0.0.1"),
        port=config.get("port", 5050),
        debug=config.get("debug", False),
    )
