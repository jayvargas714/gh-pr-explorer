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
    # Blocking findings tolerated before changes are requested. 0 = one blocking
    # finding trips REQUEST_CHANGES.
    "maxBlocking": 0,
    # Non-blocking findings tolerated; None = unlimited (the default), so
    # non-blocking findings alone never block a PR.
    "maxNonBlocking": None,
    "allowAutoApprove": False,
    "autoFollowupReview": False,
    # Disputed blocking findings at or above this count route the PR to human
    # mediation instead of a verdict. Disputed/deferred findings never count
    # toward the max* thresholds.
    "mediationDisputedThreshold": 3,
}

_INT_KEYS = ("maxBlocking", "mediationDisputedThreshold")
# Int keys that also accept null / "" meaning "no limit".
_NULLABLE_INT_KEYS = ("maxNonBlocking",)
_BOOL_KEYS = ("enabled", "allowAutoApprove", "autoFollowupReview")
# Lower bounds for the int keys; anything absent here allows zero.
_INT_MINIMUMS = {"mediationDisputedThreshold": 1}

# Fields a per-PR override may replace. 'enabled' is deliberately absent: the
# master switch is the one global kill-switch and can never be overridden.
OVERRIDE_KEYS = (
    "maxBlocking", "maxNonBlocking", "allowAutoApprove", "autoFollowupReview",
    "mediationDisputedThreshold",
)

# Pre-two-tier threshold keys (critical / major / minor).
_LEGACY_KEYS = ("maxCritical", "maxMajor", "maxMinor")


def upgrade_legacy_criteria(criteria: Dict[str, Any]) -> Dict[str, Any]:
    """Fold a three-tier criteria dict into the two-tier keys.

    ``maxBlocking = maxCritical + maxMajor`` (a missing key counts as 0) and
    ``maxNonBlocking = None`` (unlimited); the legacy keys are dropped. A dict
    without legacy keys is returned unchanged (same object). Used by
    ``get_criteria`` / ``apply_override`` for values still stored in the old
    shape, and by the one-shot data migration.
    """
    if not any(key in criteria for key in _LEGACY_KEYS):
        return criteria
    upgraded = {k: v for k, v in criteria.items() if k not in _LEGACY_KEYS}
    upgraded["maxBlocking"] = _legacy_int(criteria.get("maxCritical")) + _legacy_int(criteria.get("maxMajor"))
    upgraded["maxNonBlocking"] = None
    return upgraded


def _legacy_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def get_criteria() -> Dict[str, Any]:
    """Stored criteria merged over the defaults."""
    from backend.database import get_settings_db

    criteria = dict(DEFAULT_CRITERIA)
    try:
        stored = get_settings_db().get_setting(SETTINGS_KEY)
        if isinstance(stored, dict):
            stored = upgrade_legacy_criteria(stored)
            criteria.update({k: v for k, v in stored.items() if k in criteria})
    except Exception as e:
        logger.error(f"Failed to read auto-verdict config, using defaults: {e}")
    return criteria


def validate_criteria(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce and validate an incoming criteria payload.

    Raises ValueError on a negative or non-integer threshold. ``maxNonBlocking``
    additionally accepts null / "" for "unlimited".
    """
    if not isinstance(payload, dict):
        raise ValueError("Criteria must be an object")
    payload = upgrade_legacy_criteria(payload)

    criteria = dict(DEFAULT_CRITERIA)
    for key in _INT_KEYS + _NULLABLE_INT_KEYS:
        if key not in payload:
            continue
        value = payload[key]
        if key in _NULLABLE_INT_KEYS and (value is None or value == ""):
            criteria[key] = None
            continue
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be an integer")
        minimum = _INT_MINIMUMS.get(key, 0)
        if value < minimum:
            raise ValueError(f"{key} must be {minimum} or greater")
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
    override = upgrade_legacy_criteria(override)
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
