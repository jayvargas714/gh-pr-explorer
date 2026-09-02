"""Process-wide logging for the launcher: console + per-run file + error.log.

Called once from app.py. Scripts and tests import backend without going
through here and keep the console-only basicConfig from backend.extensions.

Files under <log_dir> (default PROJECT_ROOT/logs):
  pr-explorer_<UTC start>.log  every INFO+ record from this process, including
                               werkzeug access lines
  error.log                    ERROR+ records from every run, appended, with one
                               "Process started" boundary line per start

All timestamps, in file names and in lines, are UTC. Uncaught exceptions in
threads (and the main thread) are logged at CRITICAL so a crashed worker is
visible in both files instead of only on the terminal.

Under Flask's debug reloader the module runs in two processes and each would
open its own per-run file; debug is off for the live instance.
"""

import logging
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backend.config import PROJECT_ROOT, get_log_retention_days

MAIN_LOG_PREFIX = "pr-explorer_"
MAIN_LOG_GLOB = f"{MAIN_LOG_PREFIX}*.log"
ERROR_LOG_NAME = "error.log"

LOG_FORMAT = "%(asctime)s.%(msecs)03dZ %(levelname)-8s [%(threadName)s] %(name)s: %(message)s"
LOG_DATEFMT = "%Y-%m-%dT%H:%M:%S"

logger = logging.getLogger("gh_pr_explorer")

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class _ErrorFileFilter(logging.Filter):
    """Pass ERROR+ records, plus the startup marker tagged run_marker=True."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.ERROR or getattr(record, "run_marker", False)


class _PlainFileFormatter(logging.Formatter):
    """UTC formatter that drops ANSI color codes (werkzeug colors its access lines)."""

    def format(self, record: logging.LogRecord) -> str:
        return _ANSI_RE.sub("", super().format(record))


def _utc_formatter(plain: bool = False) -> logging.Formatter:
    cls = _PlainFileFormatter if plain else logging.Formatter
    formatter = cls(LOG_FORMAT, datefmt=LOG_DATEFMT)
    formatter.converter = time.gmtime
    return formatter


def _prune_old_logs(log_dir: Path, retention_days: int) -> None:
    if retention_days <= 0:
        return
    cutoff = time.time() - retention_days * 86400
    removed = 0
    for path in log_dir.glob(MAIN_LOG_GLOB):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError as exc:
            logger.warning("Could not prune log file %s: %s", path, exc)
    if removed:
        logger.info("Pruned %d log file(s) older than %d days from %s", removed, retention_days, log_dir)


def _install_excepthooks() -> None:
    """Log uncaught exceptions at CRITICAL before deferring to any custom hook.

    The interpreter's default hooks only print the traceback to stderr, which
    the console handler already does for the logged record, so they are not
    chained (that would print every crash twice on the terminal).
    """
    previous_sys_hook = sys.excepthook
    previous_thread_hook = threading.excepthook

    def sys_hook(exc_type, exc_value, exc_tb):
        logger.critical("Uncaught exception in MainThread", exc_info=(exc_type, exc_value, exc_tb))
        if previous_sys_hook is not sys.__excepthook__:
            previous_sys_hook(exc_type, exc_value, exc_tb)

    def thread_hook(args):
        name = args.thread.name if args.thread is not None else "unknown thread"
        logger.critical(
            "Uncaught exception in thread %s", name,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
        if previous_thread_hook is not threading.__excepthook__:
            previous_thread_hook(args)

    sys.excepthook = sys_hook
    threading.excepthook = thread_hook


def configure_logging(log_dir: Optional[Path] = None) -> Path:
    """Replace the root handlers with console + per-run file + error.log.

    Returns the path of this run's main log file.
    """
    log_dir = Path(log_dir) if log_dir is not None else PROJECT_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    started = datetime.now(timezone.utc)
    main_path = log_dir / f"{MAIN_LOG_PREFIX}{started.strftime('%Y-%m-%dT%H-%M-%SZ')}.log"
    error_path = log_dir / ERROR_LOG_NAME

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(_utc_formatter())

    file_formatter = _utc_formatter(plain=True)
    main_file = logging.FileHandler(main_path, encoding="utf-8")
    main_file.setFormatter(file_formatter)

    error_file = logging.FileHandler(error_path, mode="a", encoding="utf-8")
    error_file.setFormatter(file_formatter)
    error_file.addFilter(_ErrorFileFilter())

    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    root.setLevel(logging.INFO)
    for handler in (console, main_file, error_file):
        root.addHandler(handler)

    _install_excepthooks()
    _prune_old_logs(log_dir, get_log_retention_days())

    logger.info(
        "Process started; logging to %s, errors also appended to %s",
        main_path, error_path, extra={"run_marker": True},
    )
    return main_path
