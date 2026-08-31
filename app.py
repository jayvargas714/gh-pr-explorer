#!/usr/bin/env python3
"""GitHub PR Explorer - Flask Backend

Thin launcher that creates the app via the backend package factory
and starts the development server.
"""

import os
import threading

from backend import (
    create_app,
    startup_refresh_workflow_caches,
    startup_refresh_stats_caches,
    startup_purge_review_events,
)
from backend.config import get_config, get_pr_sync_config
from backend.services.auto_review_watcher import auto_review_watcher_loop
from backend.services.auto_verdict_watcher import auto_verdict_watcher_loop
from backend.services.automation_dispatch_worker import automation_dispatch_worker_loop
from backend.services.pr_sync_worker import pr_sync_worker_loop
from backend.services.review_reconciliation import reconcile_orphaned_reviews
from backend.services.stale_review_watcher import stale_review_watcher_loop

app = create_app()

if __name__ == "__main__":
    config = get_config()

    # Refresh stale caches in background on startup
    threading.Thread(target=startup_refresh_workflow_caches, daemon=True).start()
    threading.Thread(target=startup_refresh_stats_caches, daemon=True).start()
    threading.Thread(target=startup_purge_review_events, daemon=True).start()

    # Watch for review completions so auto verdicts fire without a browser attached.
    # Under debug mode Flask's reloader runs this module twice; only the child
    # process (WERKZEUG_RUN_MAIN=true) should own the watcher.
    if not config.get("debug") or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        # Close and restart review runs the previous process left in flight.
        # Synchronous, and before the watchers spawn, so a freshly started
        # review can never be mistaken for an orphan.
        reconcile_orphaned_reviews()
        threading.Thread(target=auto_verdict_watcher_loop, daemon=True).start()
        # Watch armed PRs for new commits so follow-up reviews start themselves.
        threading.Thread(target=auto_review_watcher_loop, daemon=True).start()
        # Stop and restart running reviews that new commits made stale.
        threading.Thread(target=stale_review_watcher_loop, daemon=True).start()
        # Keep the DB-backed PR list fresh (see docs/specs/2026-08-28-pr-sync-db-design.md).
        if get_pr_sync_config()["enabled"]:
            threading.Thread(target=pr_sync_worker_loop, daemon=True).start()
        # Drain pending automation dispatches into reviews. Started
        # unconditionally: the loop's own scope=='off' check is the gate.
        threading.Thread(target=automation_dispatch_worker_loop, daemon=True).start()

    app.run(
        host=config.get("host", "127.0.0.1"),
        port=config.get("port", 5050),
        debug=config.get("debug", False),
    )
