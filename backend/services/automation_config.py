"""Full-automation configuration, persisted in the user_settings key/value store.

Mirrors auto_verdict_config.py: one validated blob, defaults all off so nothing
is dispatched until the operator explicitly enables a scope and lists repos.
"""

import logging
from typing import Any, Dict, Iterable, List

logger = logging.getLogger(__name__)

SETTINGS_KEY = "automation_config"

VALID_SCOPES = ("off", "authors", "all")
VALID_MODES = ("verdict", "comment")

DEFAULT_CONFIG: Dict[str, Any] = {
    "scope": "off",                    # 'off' | 'authors' | 'all'
    "authors": [],                     # GitHub logins (used when scope == 'authors')
    "repoAllowlist": [],               # 'owner/repo'; empty = nothing processed
    "maxConcurrentAutoReviews": 2,
    "requireCiPass": True,             # CI must be completed and passing before dispatch
    "maxBehindBase": 10,               # max commits the PR branch may be behind its base head
    "maxPipelineSize": 1000,           # max pending pipeline rows; new candidates are refused at the cap
    "ignorePatterns": [],              # globs stripped before classification
    "defaultRule": {"reviewerKey": "default", "autoVerdict": False, "autoVerdictMode": "verdict"},
    "rules": [],                       # ordered: [{name, patterns, reviewerKey, autoVerdict, autoVerdictMode}]
}


def get_config() -> Dict[str, Any]:
    """Stored config merged over the defaults."""
    from backend.database import get_settings_db

    config = {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v)
              for k, v in DEFAULT_CONFIG.items()}
    try:
        stored = get_settings_db().get_setting(SETTINGS_KEY)
        if isinstance(stored, dict):
            config.update({k: v for k, v in stored.items() if k in config})
    except Exception as e:
        logger.error(f"Failed to read automation config, using defaults: {e}")
    return config


def _string_list(value: Any, field: str) -> List[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list of strings")
    result = []
    for entry in value:
        if not isinstance(entry, str):
            raise ValueError(f"{field} must contain only strings")
        entry = entry.strip()
        if entry:
            result.append(entry)
    return result


def _validate_rule(rule: Any, valid_reviewer_keys: Iterable[str],
                   require_name: bool = True) -> Dict[str, Any]:
    if not isinstance(rule, dict):
        raise ValueError("Each rule must be an object")
    validated: Dict[str, Any] = {}
    if require_name:
        name = (rule.get("name") or "").strip() if isinstance(rule.get("name"), str) else ""
        if not name:
            raise ValueError("Each rule needs a non-empty name")
        validated["name"] = name
        patterns = _string_list(rule.get("patterns"), "rule patterns")
        if not patterns:
            raise ValueError(f"Rule '{name}' needs at least one pattern")
        validated["patterns"] = patterns
    reviewer_key = rule.get("reviewerKey")
    if reviewer_key not in valid_reviewer_keys:
        raise ValueError(f"Unknown reviewerKey: {reviewer_key}")
    validated["reviewerKey"] = reviewer_key
    validated["autoVerdict"] = bool(rule.get("autoVerdict"))
    mode = rule.get("autoVerdictMode") or "verdict"
    if mode not in VALID_MODES:
        raise ValueError(f"Invalid autoVerdictMode: {mode}")
    validated["autoVerdictMode"] = mode
    return validated


def validate_config(payload: Dict[str, Any], valid_reviewer_keys: Iterable[str]) -> Dict[str, Any]:
    """Coerce and validate an incoming automation config payload.

    Raises ValueError on anything malformed. Unknown keys are dropped.
    """
    if not isinstance(payload, dict):
        raise ValueError("Config must be an object")
    valid_keys = tuple(valid_reviewer_keys)

    config: Dict[str, Any] = {}

    scope = payload.get("scope", DEFAULT_CONFIG["scope"])
    if scope not in VALID_SCOPES:
        raise ValueError(f"Invalid scope: {scope}")
    config["scope"] = scope

    config["authors"] = _string_list(payload.get("authors", []), "authors")
    config["repoAllowlist"] = _string_list(payload.get("repoAllowlist", []), "repoAllowlist")
    config["ignorePatterns"] = _string_list(payload.get("ignorePatterns", []), "ignorePatterns")

    try:
        concurrency = int(payload.get("maxConcurrentAutoReviews", DEFAULT_CONFIG["maxConcurrentAutoReviews"]))
    except (TypeError, ValueError):
        raise ValueError("maxConcurrentAutoReviews must be an integer")
    if concurrency < 1:
        raise ValueError("maxConcurrentAutoReviews must be at least 1")
    config["maxConcurrentAutoReviews"] = concurrency

    config["requireCiPass"] = bool(payload.get("requireCiPass", DEFAULT_CONFIG["requireCiPass"]))

    try:
        max_behind = int(payload.get("maxBehindBase", DEFAULT_CONFIG["maxBehindBase"]))
    except (TypeError, ValueError):
        raise ValueError("maxBehindBase must be an integer")
    if max_behind < 0:
        raise ValueError("maxBehindBase must be zero or greater")
    config["maxBehindBase"] = max_behind

    try:
        pipeline_size = int(payload.get("maxPipelineSize", DEFAULT_CONFIG["maxPipelineSize"]))
    except (TypeError, ValueError):
        raise ValueError("maxPipelineSize must be an integer")
    if pipeline_size < 1:
        raise ValueError("maxPipelineSize must be at least 1")
    config["maxPipelineSize"] = pipeline_size

    config["defaultRule"] = _validate_rule(
        payload.get("defaultRule", DEFAULT_CONFIG["defaultRule"]),
        valid_keys, require_name=False,
    )

    rules = payload.get("rules", [])
    if not isinstance(rules, list):
        raise ValueError("rules must be a list")
    config["rules"] = [_validate_rule(rule, valid_keys) for rule in rules]

    return config


def save_config(payload: Dict[str, Any], valid_reviewer_keys: Iterable[str]) -> Dict[str, Any]:
    """Validate and persist the config. Returns the stored value."""
    from backend.database import get_settings_db

    config = validate_config(payload, valid_reviewer_keys)
    get_settings_db().set_setting(SETTINGS_KEY, config)
    logger.info(f"Saved automation config: scope={config['scope']}, "
                f"repos={len(config['repoAllowlist'])}, rules={len(config['rules'])}")
    return config
