"""Application configuration loaded from config.json."""

import json
from pathlib import Path
from typing import Any, Dict

# Project root is one level up from backend/
PROJECT_ROOT = Path(__file__).parent.parent

# Default code reviews directory (overridden by config.json "reviews_dir")
REVIEWS_DIR = Path("/Users/jvargas714/Documents/code-reviews")


def get_reviews_dir() -> Path:
    """Get the reviews directory from config, with fallback to PROJECT_ROOT/reviews."""
    config = get_config()
    reviews_path = config.get("reviews_dir")
    if reviews_path:
        return Path(reviews_path)
    return PROJECT_ROOT / "reviews"

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
