"""Tests for the bot-login predicate used by the analytics rollup."""

from backend.services.bot_filter import is_bot_login, normalize_login

BOT_LOGINS = ["github-actions", "coderabbitai", "dependabot"]


# -- normalize_login ---------------------------------------------------------

def test_normalize_login_strips_app_prefix():
    assert normalize_login("app/github-actions") == "github-actions"


def test_normalize_login_strips_bot_suffix():
    assert normalize_login("coderabbitai[bot]") == "coderabbitai"


def test_normalize_login_lowercases():
    assert normalize_login("CoderabbitAI") == "coderabbitai"


def test_normalize_login_none_is_empty_string():
    assert normalize_login(None) == ""


def test_normalize_login_plain_login_unchanged():
    assert normalize_login("alice") == "alice"


# -- is_bot_login --------------------------------------------------------------

def test_is_bot_login_true_via_flag():
    assert is_bot_login("alice", is_bot_flag=True, bot_logins=[]) is True


def test_is_bot_login_true_via_app_prefix():
    assert is_bot_login("app/github-actions", bot_logins=[]) is True


def test_is_bot_login_true_via_bot_suffix():
    assert is_bot_login("dependabot[bot]", bot_logins=[]) is True


def test_is_bot_login_true_via_list_membership():
    assert is_bot_login("coderabbitai", bot_logins=BOT_LOGINS) is True


def test_is_bot_login_list_membership_normalizes_both_sides():
    assert is_bot_login("CoderabbitAI", bot_logins=["CoderabbitAI"]) is True


def test_is_bot_login_false_for_non_bot():
    assert is_bot_login("alice", bot_logins=BOT_LOGINS) is False


def test_is_bot_login_false_for_none():
    assert is_bot_login(None, bot_logins=BOT_LOGINS) is False


def test_is_bot_login_none_bot_logins_uses_config(monkeypatch):
    import backend.services.bot_filter as bot_filter

    monkeypatch.setattr(bot_filter, "get_analytics_config", lambda: {"bot_logins": ["scalazack"]})
    assert is_bot_login("scalazack") is True
    assert is_bot_login("alice") is False
