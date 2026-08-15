"""Auto-verdict criteria configuration, persisted in the user_settings key/value store.

Single source of truth for the thresholds so the evaluator and the API cannot drift.
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

SETTINGS_KEY = "auto_verdict_config"

# Both switches default off so installing the feature cannot post anything to
# GitHub until the user deliberately enables it in the config panel.
DEFAULT_CRITERIA: Dict[str, Any] = {
    "enabled": False,
    "maxCritical": 0,
    "maxMajor": 0,
    "maxMinor": 99,
    "allowAutoApprove": False,
    "autoFollowupReview": False,
}

_INT_KEYS = ("maxCritical", "maxMajor", "maxMinor")
_BOOL_KEYS = ("enabled", "allowAutoApprove", "autoFollowupReview")


def get_criteria() -> Dict[str, Any]:
    """Stored criteria merged over the defaults."""
    from backend.database import get_settings_db

    criteria = dict(DEFAULT_CRITERIA)
    try:
        stored = get_settings_db().get_setting(SETTINGS_KEY)
        if isinstance(stored, dict):
            criteria.update({k: v for k, v in stored.items() if k in criteria})
    except Exception as e:
        logger.error(f"Failed to read auto-verdict config, using defaults: {e}")
    return criteria


def validate_criteria(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce and validate an incoming criteria payload.

    Raises ValueError on a negative or non-integer threshold.
    """
    if not isinstance(payload, dict):
        raise ValueError("Criteria must be an object")

    criteria = dict(DEFAULT_CRITERIA)
    for key in _INT_KEYS:
        if key in payload:
            try:
                value = int(payload[key])
            except (TypeError, ValueError):
                raise ValueError(f"{key} must be an integer")
            if value < 0:
                raise ValueError(f"{key} must be zero or greater")
            criteria[key] = value
    for key in _BOOL_KEYS:
        if key in payload:
            criteria[key] = bool(payload[key])
    return criteria


def save_criteria(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and persist criteria. Returns the stored value."""
    from backend.database import get_settings_db

    criteria = validate_criteria(payload)
    get_settings_db().set_setting(SETTINGS_KEY, criteria)
    logger.info(f"Saved auto-verdict config: {criteria}")
    return criteria
