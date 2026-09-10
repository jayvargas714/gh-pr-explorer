"""Bot-login predicate for analytics — separate from pr_conversation._is_bot,
which drives conversation-fetch exclusion rather than rollup attribution."""

from typing import Iterable, Optional

from backend.config import get_analytics_config


def normalize_login(login: Optional[str]) -> str:
    """Lowercase a login and strip GitHub App / bot-account decorations."""
    if not login:
        return ""
    normalized = login.lower()
    if normalized.startswith("app/"):
        normalized = normalized[len("app/"):]
    if normalized.endswith("[bot]"):
        normalized = normalized[:-len("[bot]")]
    return normalized


def is_bot_login(login: Optional[str], is_bot_flag: bool = False,
                  bot_logins: Optional[Iterable[str]] = None) -> bool:
    """True when a login should be treated as a bot account for analytics."""
    if is_bot_flag:
        return True
    if login and (login.startswith("app/") or login.endswith("[bot]")):
        return True
    if bot_logins is None:
        bot_logins = get_analytics_config()["bot_logins"]
    return normalize_login(login) in {normalize_login(b) for b in bot_logins}
