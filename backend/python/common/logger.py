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
from typing import Optional, Callable, Dict

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


# =============================================================================
# GUI Integration Helper
# =============================================================================
class GUILogHandler(logging.Handler):
    """
    Custom handler that bridges logging to Flet UI components.

    Usage:
        logger = get_tool_logger("my_tool")
        gui_handler = GUILogHandler(update_callback=my_log_display_func)
        logger.addHandler(gui_handler)
    """

    def __init__(self, update_callback: Callable[[str], None]):
        """
        Initialize with a callback function for UI updates.

        Args:
            update_callback: Function that receives log messages for display
        """
        super().__init__()
        self.update_callback = update_callback
        self.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            self.update_callback(msg)
        except Exception:
            self.handleError(record)


# =============================================================================
# Session Logging
# =============================================================================
def log_session_start(tool_name: str) -> None:
    """
    Log the start of a tool session with system info.

    Args:
        tool_name: Name of the tool being started
    """
    logger = get_tool_logger(tool_name)
    logger.info("=" * 60)
    logger.info(f"Session Start: {tool_name}")
    logger.info(f"Timestamp: {datetime.now().isoformat()}")
    logger.info(f"Python: {sys.version.split()[0]}")
    logger.info(f"Platform: {sys.platform}")
    logger.info(f"Frozen (EXE): {getattr(sys, 'frozen', False)}")
    logger.info("=" * 60)


def log_session_end(tool_name: str, success: bool = True) -> None:
    """
    Log the end of a tool session.

    Args:
        tool_name: Name of the tool
        success: Whether the session ended successfully
    """
    logger = get_tool_logger(tool_name)
    status = "SUCCESS" if success else "FAILED"
    logger.info(f"Session End: {status}")
    logger.info("=" * 60)


def log_operation(tool_name: str, operation: str, details: Optional[str] = None) -> None:
    """
    Log a specific operation within a tool.

    Args:
        tool_name: Name of the tool
        operation: Description of the operation
        details: Optional additional details
    """
    logger = get_tool_logger(tool_name)
    if details:
        logger.info(f"{operation}: {details}")
    else:
        logger.info(operation)


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
