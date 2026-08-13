#!/usr/bin/env python3
"""GitHub PR Explorer - Flask Backend

Thin launcher that creates the app via the backend package factory
and starts the development server.
"""

import os
import threading

from backend import create_app, startup_refresh_workflow_caches, startup_refresh_stats_caches
from backend.config import get_config
from backend.services.auto_verdict_watcher import auto_verdict_watcher_loop

app = create_app()

if __name__ == "__main__":
    config = get_config()

    # Refresh stale caches in background on startup
    threading.Thread(target=startup_refresh_workflow_caches, daemon=True).start()
    threading.Thread(target=startup_refresh_stats_caches, daemon=True).start()

    # Watch for review completions so auto verdicts fire without a browser attached.
    # Under debug mode Flask's reloader runs this module twice; only the child
    # process (WERKZEUG_RUN_MAIN=true) should own the watcher.
    if not config.get("debug") or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        threading.Thread(target=auto_verdict_watcher_loop, daemon=True).start()

    app.run(
        host=config.get("host", "127.0.0.1"),
        port=config.get("port", 5050),
        debug=config.get("debug", False),
    )
