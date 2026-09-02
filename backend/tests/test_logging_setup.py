"""Tests for backend.logging_setup: per-run UTC log files, error.log, pruning."""
import logging
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone

import pytest

import backend.config as config_mod
from backend.config import get_log_retention_days
from backend.logging_setup import MAIN_LOG_GLOB, configure_logging

MAIN_NAME_RE = re.compile(r"^pr-explorer_\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z\.log$")
LINE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z (INFO|WARNING|ERROR|CRITICAL)\s+"
    r"\[[^\]]+\] [\w.]+: .+$"
)


@pytest.fixture
def clean_logging(monkeypatch):
    """Restore root handlers, level, and excepthooks after each test.

    configure_logging() replaces the root handlers process-wide; without this
    the file handlers would leak into every later test in the session.
    """
    monkeypatch.setattr(config_mod, "_config", {})
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    saved_sys_hook, saved_thread_hook = sys.excepthook, threading.excepthook
    yield
    for handler in root.handlers[:]:
        if handler not in saved_handlers:
            root.removeHandler(handler)
            handler.close()
    for handler in saved_handlers:
        if handler not in root.handlers:
            root.addHandler(handler)
    root.setLevel(saved_level)
    sys.excepthook, threading.excepthook = saved_sys_hook, saved_thread_hook


def _flush():
    for handler in logging.getLogger().handlers:
        handler.flush()


def _main_files(log_dir):
    return sorted(p for p in log_dir.glob(MAIN_LOG_GLOB))


def test_creates_timestamped_main_log_and_error_log(clean_logging, tmp_path):
    log_dir = tmp_path / "logs"
    main_path = configure_logging(log_dir)

    assert main_path.parent == log_dir
    assert MAIN_NAME_RE.match(main_path.name), main_path.name
    assert main_path.exists()
    assert (log_dir / "error.log").exists()


def test_info_goes_to_main_only_and_error_to_both(clean_logging, tmp_path):
    main_path = configure_logging(tmp_path)
    log = logging.getLogger("backend.services.some_worker")
    log.info("routine info line")
    log.error("something broke")
    _flush()

    main = main_path.read_text()
    errors = (tmp_path / "error.log").read_text()
    assert "routine info line" in main
    assert "something broke" in main
    assert "routine info line" not in errors
    assert "something broke" in errors


def test_line_format_is_structured_and_utc(clean_logging, tmp_path):
    main_path = configure_logging(tmp_path)
    logging.getLogger("backend.services.x").warning("formatted %s", "ok")
    _flush()

    lines = [l for l in main_path.read_text().splitlines() if "formatted ok" in l]
    assert len(lines) == 1
    line = lines[0]
    assert LINE_RE.match(line), line
    assert "WARNING  [MainThread] backend.services.x: formatted ok" in line

    stamp = datetime.strptime(line[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    assert abs((datetime.now(timezone.utc) - stamp).total_seconds()) < 60


def test_file_handlers_strip_ansi_color_codes(clean_logging, tmp_path):
    # werkzeug colorizes its access lines unconditionally; files must stay plain.
    main_path = configure_logging(tmp_path)
    logging.getLogger("werkzeug").error('\x1b[33mGET /missing HTTP/1.1\x1b[0m 404 -')
    _flush()

    for path in (main_path, tmp_path / "error.log"):
        text = path.read_text()
        assert "GET /missing HTTP/1.1 404 -" in text, path
        assert "\x1b[" not in text, path


def test_error_log_has_run_marker_but_no_other_info(clean_logging, tmp_path):
    main_path = configure_logging(tmp_path)
    logging.getLogger("gh_pr_explorer").info("noise")
    _flush()

    lines = (tmp_path / "error.log").read_text().splitlines()
    assert len(lines) == 1
    assert "Process started" in lines[0]
    assert main_path.name in lines[0]
    assert "noise" not in lines[0]

    # A second start appends a second boundary line rather than truncating.
    configure_logging(tmp_path)
    _flush()
    assert (tmp_path / "error.log").read_text().count("Process started") == 2


def _touch_old(path, days):
    path.write_text("old\n")
    old = time.time() - days * 86400
    os.utime(path, (old, old))


def test_prunes_main_logs_older_than_retention(clean_logging, monkeypatch, tmp_path):
    monkeypatch.setattr(config_mod, "_config", {"log_retention_days": 30})
    old = tmp_path / "pr-explorer_2026-01-01T00-00-00Z.log"
    fresh = tmp_path / "pr-explorer_2026-08-30T00-00-00Z.log"
    _touch_old(old, 40)
    _touch_old(fresh, 2)
    error_log = tmp_path / "error.log"
    _touch_old(error_log, 400)

    configure_logging(tmp_path)

    assert not old.exists()
    assert fresh.exists()
    assert error_log.exists()


def test_retention_zero_disables_pruning(clean_logging, monkeypatch, tmp_path):
    monkeypatch.setattr(config_mod, "_config", {"log_retention_days": 0})
    old = tmp_path / "pr-explorer_2026-01-01T00-00-00Z.log"
    _touch_old(old, 400)

    configure_logging(tmp_path)

    assert old.exists()


def test_uncaught_thread_exception_is_logged_critical(clean_logging, tmp_path):
    # Swallow the default hook so pytest's thread-exception plugin stays quiet.
    threading.excepthook = lambda args: None
    configure_logging(tmp_path)

    def boom():
        raise RuntimeError("worker exploded")

    t = threading.Thread(target=boom, name="doomed-worker")
    t.start()
    t.join()
    _flush()

    errors = (tmp_path / "error.log").read_text()
    assert "CRITICAL" in errors
    assert "doomed-worker" in errors
    assert "RuntimeError: worker exploded" in errors


def test_get_log_retention_days(monkeypatch):
    monkeypatch.setattr(config_mod, "_config", {})
    assert get_log_retention_days() == 30
    monkeypatch.setattr(config_mod, "_config", {"log_retention_days": 7})
    assert get_log_retention_days() == 7
    monkeypatch.setattr(config_mod, "_config", {"log_retention_days": "soon"})
    assert get_log_retention_days() == 30
    monkeypatch.setattr(config_mod, "_config", {"log_retention_days": -3})
    assert get_log_retention_days() == 0
