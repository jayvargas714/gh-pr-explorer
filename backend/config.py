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
