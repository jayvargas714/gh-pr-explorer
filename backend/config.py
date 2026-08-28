"""Application configuration loaded from config.json."""

import json
import os
from pathlib import Path
from typing import Any, Dict

# Project root is one level up from backend/
PROJECT_ROOT = Path(__file__).parent.parent

# Default code reviews directory when config.json omits "reviews_dir".
# Kept machine-agnostic via ~ expansion so it works on any host.
DEFAULT_REVIEWS_DIR = "~/code-reviews"

# Review retry policy. An attempt fails when the Claude CLI exits non-zero or
# exits 0 without writing its review files; the run is retried up to
# DEFAULT_REVIEW_MAX_ATTEMPTS times in total before being recorded as failed.
DEFAULT_REVIEW_MAX_ATTEMPTS = 3
REVIEW_MAX_ATTEMPTS_CAP = 5
DEFAULT_REVIEW_RETRY_DELAY_SECONDS = 30

# How long review lifecycle events are kept before the startup purge drops them.
DEFAULT_REVIEW_LOG_RETENTION_DAYS = 90


def _resolve_path(raw: str) -> Path:
    """Expand ~ and environment variables in a configured path."""
    return Path(os.path.expanduser(os.path.expandvars(raw)))


def get_reviews_dir() -> Path:
    """Get the reviews directory from config.

    Reads config.json's "reviews_dir" (with ~ and $VAR expansion), falling back
    to DEFAULT_REVIEWS_DIR so the app runs on any machine without edits.
    """
    config = get_config()
    reviews_path = config.get("reviews_dir") or DEFAULT_REVIEWS_DIR
    return _resolve_path(reviews_path)


def get_past_reviews_dir() -> Path:
    """Get the legacy past-reviews directory for one-time data migration.

    Reads config.json's "past_reviews_dir" (with ~/$VAR expansion), defaulting
    to a "past-reviews" subfolder of the configured reviews directory.
    """
    config = get_config()
    past_path = config.get("past_reviews_dir")
    if past_path:
        return _resolve_path(past_path)
    return get_reviews_dir() / "past-reviews"


def get_review_retry_settings() -> tuple:
    """Get the review retry policy from config.

    Reads config.json's "review_max_attempts" (total attempts including the
    first, clamped to 1..REVIEW_MAX_ATTEMPTS_CAP) and
    "review_retry_delay_seconds" (backoff before each retry). A malformed value
    falls back to its default rather than breaking the retry loop.

    Returns:
        tuple: (max_attempts, retry_delay_seconds)
    """
    config = get_config()

    try:
        max_attempts = int(config.get("review_max_attempts", DEFAULT_REVIEW_MAX_ATTEMPTS))
    except (TypeError, ValueError):
        max_attempts = DEFAULT_REVIEW_MAX_ATTEMPTS
    max_attempts = max(1, min(max_attempts, REVIEW_MAX_ATTEMPTS_CAP))

    try:
        delay = float(config.get("review_retry_delay_seconds", DEFAULT_REVIEW_RETRY_DELAY_SECONDS))
    except (TypeError, ValueError):
        delay = DEFAULT_REVIEW_RETRY_DELAY_SECONDS
    delay = max(0.0, delay)

    return max_attempts, delay


def get_review_log_retention_days() -> int:
    """Get the review event log retention window in days.

    Reads config.json's "review_log_retention_days". Zero or negative disables
    purging; a malformed value falls back to the default.
    """
    config = get_config()
    try:
        days = int(config.get("review_log_retention_days", DEFAULT_REVIEW_LOG_RETENTION_DAYS))
    except (TypeError, ValueError):
        days = DEFAULT_REVIEW_LOG_RETENTION_DAYS
    return max(0, days)


# PR list sync worker defaults; overridable via config.json's "pr_sync" block.
DEFAULT_PR_SYNC = {
    "enabled": True,
    "poll_interval_seconds": 120,
    "history_days": 180,
    "max_synced_repos": 10,
    "exclude_repos": [],
}


def get_pr_sync_config() -> Dict[str, Any]:
    """Get the PR sync settings, merged over defaults and sanitized.

    Malformed values fall back to their defaults rather than breaking the
    worker loop (mirrors get_review_retry_settings' tolerance).
    """
    config = get_config()
    raw = config.get("pr_sync")
    merged = dict(DEFAULT_PR_SYNC)
    if isinstance(raw, dict):
        for key in DEFAULT_PR_SYNC:
            if key in raw:
                merged[key] = raw[key]

    merged["enabled"] = bool(merged["enabled"])

    for key, minimum in (("poll_interval_seconds", 30), ("history_days", 1), ("max_synced_repos", 1)):
        try:
            value = int(merged[key])
            if value <= 0 and key != "max_synced_repos":
                raise ValueError
            merged[key] = max(minimum, value)
        except (TypeError, ValueError):
            merged[key] = DEFAULT_PR_SYNC[key]

    if not isinstance(merged["exclude_repos"], list):
        merged["exclude_repos"] = []
    merged["exclude_repos"] = [str(r) for r in merged["exclude_repos"]]

    return merged


# Database file path
DB_PATH = PROJECT_ROOT / "pr_explorer.db"


def load_config(config_path: Path = None) -> Dict[str, Any]:
    """Load configuration from config.json.

    Args:
        config_path: Optional path to config file. Defaults to PROJECT_ROOT/config.json.

    Returns:
        Configuration dictionary.
    """
    if config_path is None:
        config_path = PROJECT_ROOT / "config.json"
    with open(config_path) as f:
        return json.load(f)


# Singleton config instance
_config: Dict[str, Any] = None


def get_config() -> Dict[str, Any]:
    """Get the singleton config dictionary."""
    global _config
    if _config is None:
        _config = load_config()
    return _config
