"""Auto-verdict criteria configuration, persisted in the user_settings key/value store.

Single source of truth for the thresholds so the evaluator and the API cannot drift.
"""

import json
import logging
from typing import Any, Dict, Optional

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

# Fields a per-PR override may replace. 'enabled' is deliberately absent: the
# master switch is the one global kill-switch and can never be overridden.
OVERRIDE_KEYS = ("maxCritical", "maxMajor", "maxMinor", "allowAutoApprove", "autoFollowupReview")


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


def validate_override(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce and validate a per-PR criteria override: a full snapshot of the
    overridable fields, without the master switch."""
    criteria = validate_criteria(payload)
    return {k: criteria[k] for k in OVERRIDE_KEYS}


def apply_override(criteria: Dict[str, Any], queue_item: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge a queued PR's stored criteria override over the given criteria.

    Returns a new dict; the base is untouched. A missing or malformed override
    leaves the criteria unchanged, and 'enabled' is never overridden.
    """
    raw = (queue_item or {}).get("auto_verdict_criteria")
    if not raw:
        return dict(criteria)
    try:
        override = raw if isinstance(raw, dict) else json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Ignoring malformed auto-verdict override: %r", raw)
        return dict(criteria)
    if not isinstance(override, dict):
        logger.warning("Ignoring non-object auto-verdict override: %r", raw)
        return dict(criteria)
    effective = dict(criteria)
    effective.update({k: override[k] for k in OVERRIDE_KEYS if k in override})
    return effective


def save_criteria(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and persist criteria. Returns the stored value."""
    from backend.database import get_settings_db

    criteria = validate_criteria(payload)
    get_settings_db().set_setting(SETTINGS_KEY, criteria)
    logger.info(f"Saved auto-verdict config: {criteria}")
    return criteria
