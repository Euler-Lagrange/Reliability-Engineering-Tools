#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Centralized Logging Module for Reliability Tools Suite

Provides file-based logging with rotation, compliant with security requirements:
- NO network-based logging
- NO telemetry or external data transmission
- Local file storage only (5MB max, 5 backup rotation)

Logs are stored in the user's home directory: ~/.reliability_tools/logs/
"""
import os
import sys
import logging
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict

# =============================================================================
# Configuration Constants
# =============================================================================
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_BYTES = 5 * 1024 * 1024  # 5MB per file
BACKUP_COUNT = 5             # Keep 5 rotated files
LOG_DIR_NAME = ".reliability_tools"


# =============================================================================
# Path Resolution
# =============================================================================
def get_log_directory() -> Path:
    """
    Get the logs directory path.

    Respects RELIABILITY_TOOLS_LOG_DIR env var for test isolation.
    Defaults to ~/.reliability_tools/logs/.
    """
    import os
    custom = os.environ.get("RELIABILITY_TOOLS_LOG_DIR")
    if custom:
        log_dir = Path(custom)
    else:
        log_dir = Path.home() / LOG_DIR_NAME / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


# =============================================================================
# Logger Factory
# =============================================================================
_loggers: Dict[str, logging.Logger] = {}
_logger_lock = threading.Lock()  # Thread safety for logger creation


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """
    Get or create a logger with file rotation.

    Thread-safe: uses a lock to prevent race conditions when multiple
    threads request loggers simultaneously.

    Args:
        name: Logger name (typically module/tool name)
        level: Logging level (default INFO)

    Returns:
        Configured logger instance
    """
    # C9: Use lock for entire operation to prevent TOCTOU race condition
    # Logger creation is infrequent, so lock overhead is minimal
    with _logger_lock:
        if name in _loggers:
            return _loggers[name]

        # Respect SIDECAR_LOG_LEVEL env var to suppress file logging in test/sidecar contexts
        import os
        env_level = os.environ.get("SIDECAR_LOG_LEVEL")
        if env_level:
            level = getattr(logging, env_level.upper(), level)

        logger = logging.getLogger(name)
        logger.setLevel(level)

        # Skip file handler entirely when suppressed (avoids PermissionError on Windows)
        if level >= logging.CRITICAL:
            _loggers[name] = logger
            return logger

        # Prevent duplicate handlers
        if not logger.handlers:
            log_dir = get_log_directory()

            # Sanitize name for filename
            safe_name = name.replace(".", "_").replace(" ", "_")
            log_file = log_dir / f"{safe_name}.log"

            # Rotating file handler
            try:
                file_handler = RotatingFileHandler(
                    log_file,
                    maxBytes=MAX_BYTES,
                    backupCount=BACKUP_COUNT,
                    encoding='utf-8'
                )
                file_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
                file_handler.setLevel(level)
                logger.addHandler(file_handler)
            except (OSError, PermissionError) as e:
                # M11: Log to stderr since file logging failed (sys already imported at module level)
                # This prevents the app from crashing in restricted environments
                print(f"Warning: Could not create log file for '{name}': {e}", file=sys.stderr)

            # Console handler for development mode only (not in frozen EXE)
            if not getattr(sys, 'frozen', False):
                console_handler = logging.StreamHandler()
                console_handler.setFormatter(
                    logging.Formatter("%(levelname)-8s | %(name)s | %(message)s")
                )
                console_handler.setLevel(logging.DEBUG)
                logger.addHandler(console_handler)

        _loggers[name] = logger
        return logger


def get_tool_logger(tool_name: str) -> logging.Logger:
    """
    Convenience function to get a logger for a specific tool.

    Args:
        tool_name: Short name like 'bom_compare', 'fmea_generator', etc.

    Returns:
        Configured logger for the tool
    """
    return get_logger(f"reliability_tools.{tool_name}")


def log_error(tool_name: str, error: Exception, context: Optional[str] = None) -> None:
    """
    Log an error with full traceback.

    Args:
        tool_name: Name of the tool
        error: The exception that occurred
        context: Optional context about what was happening
    """
    logger = get_tool_logger(tool_name)
    if context:
        logger.error(f"Error during {context}: {error}")
    logger.exception("Full traceback:")


# =============================================================================
# Crash dumps
# =============================================================================
# Decision B: crash dumps can embed source data (e.g. a BOM / part value echoed
# in an exception message or traceback). Warn the user before they share the
# folder, and bound any single embedded value so it can neither leak in full nor
# balloon the file.
CRASH_DUMP_BANNER = (
    "*** WARNING: this crash dump may contain source data (e.g. BOM / part\n"
    "*** values echoed in an error message or traceback). Review it before\n"
    "*** sharing.\n"
)
_CRASH_VALUE_MAX = 500          # per-value / per-line cap
_CRASH_TRACEBACK_MAX = 20_000   # total traceback cap


def _truncate_for_crash(text: str, max_len: int) -> str:
    """Bound a string for a crash dump so an embedded DataFrame / cell value
    can't balloon the file or leak in full (Decision B)."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"... [truncated {len(text) - max_len} chars]"


def write_crash_dump(
    source: str,
    exc_type: type,
    exc_value: BaseException,
    exc_traceback,
    *,
    thread_name: Optional[str] = None,
) -> Optional[Path]:
    """Write a timestamped crash dump to the logs directory.

    Best-effort: used from ``sys.excepthook`` / ``threading.excepthook`` and
    the Rust panic hook (via a separate path) so that users can share a
    single file when they hit an unhandled exception. Never raises — if the
    dump itself fails we return ``None`` and let the caller continue its
    normal shutdown path.

    Args:
        source: Short tag (``"sidecar"``, ``"thread"``, ``"rust"``).
        exc_type: Exception class.
        exc_value: Exception instance.
        exc_traceback: Traceback object (may be ``None``).
        thread_name: Optional thread name for ``threading.excepthook``.

    Returns:
        Path to the written crash dump, or ``None`` on failure.
    """
    import traceback as _traceback

    try:
        log_dir = get_log_directory()
        crash_dir = log_dir / "crashes"
        crash_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        dump_path = crash_dir / f"crash_{source}_{timestamp}.log"

        with dump_path.open("w", encoding="utf-8") as fh:
            fh.write(CRASH_DUMP_BANNER)
            fh.write("-" * 60 + "\n")
            fh.write(f"Crash dump: {source}\n")
            fh.write(f"Timestamp:  {datetime.now().isoformat()}\n")
            fh.write(f"Python:     {sys.version.splitlines()[0]}\n")
            fh.write(f"Platform:   {sys.platform}\n")
            fh.write(f"Frozen:     {getattr(sys, 'frozen', False)}\n")
            if thread_name:
                fh.write(f"Thread:     {thread_name}\n")
            fh.write(
                f"Exception:  {exc_type.__name__}: "
                f"{_truncate_for_crash(str(exc_value), _CRASH_VALUE_MAX)}\n"
            )
            fh.write("-" * 60 + "\n")
            # Truncate each traceback line (bounds a message that echoes a value)
            # then cap the total length.
            tb_text = "".join(
                _traceback.format_exception(exc_type, exc_value, exc_traceback)
            )
            tb_bounded = "".join(
                _truncate_for_crash(line, _CRASH_VALUE_MAX)
                for line in tb_text.splitlines(keepends=True)
            )
            fh.write(_truncate_for_crash(tb_bounded, _CRASH_TRACEBACK_MAX))

        return dump_path
    except Exception:  # noqa: BLE001 — last-resort writer must not raise
        return None
