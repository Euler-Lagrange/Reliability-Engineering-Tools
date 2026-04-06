#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Centralized cancellation utilities for GUI background operations.

This module provides thread-safe cancellation primitives that can be used
across all tools in the Reliability Tools suite.

Usage Patterns:

1. Simple function-based (for module-level stop_events):

    from common.cancellation import check_cancelled

    def my_processing_function(data, stop_event=None):
        for item in data:
            check_cancelled(stop_event)  # Raises CancellationError if cancelled
            process(item)

2. Class-based with lifecycle management (for class-scoped operations):

    from common.cancellation import CancellationToken

    class MyProcessor:
        def __init__(self):
            self.cancel = CancellationToken()

        def process(self):
            self.cancel.reset()  # Clear any previous cancellation
            for item in data:
                self.cancel.check()  # Raises if cancelled
                process(item)
"""

import threading
from typing import Optional, Union


class CancellationError(InterruptedError):
    """
    Raised when an operation is cancelled by the user.

    Inherits from InterruptedError for backward compatibility with
    existing exception handlers that catch InterruptedError.
    """

    def __init__(self, message: str = "Operation cancelled by user."):
        super().__init__(message)


class CancellationToken:
    """
    Thread-safe cancellation token with lifecycle management.

    Can wrap an existing threading.Event or create its own.
    Provides explicit methods for checking, requesting, and resetting
    cancellation state.

    Attributes:
        event: The underlying threading.Event object.
    """

    def __init__(self, event: Optional[threading.Event] = None):
        """
        Initialize the cancellation token.

        Args:
            event: Optional existing Event to wrap. If None, creates a new one.
        """
        self._event = event if event is not None else threading.Event()

    @property
    def event(self) -> threading.Event:
        """Get the underlying threading.Event."""
        return self._event

    def check(self, message: str = "Operation cancelled by user.") -> None:
        """
        Check if cancellation was requested and raise if so.

        Args:
            message: Custom message for the exception.

        Raises:
            CancellationError: If the event is set (cancellation requested).
        """
        if self._event.is_set():
            raise CancellationError(message)

    def is_cancelled(self) -> bool:
        """
        Check if cancellation was requested without raising.

        Returns:
            True if cancellation was requested, False otherwise.
        """
        return self._event.is_set()

    def cancel(self) -> None:
        """Request cancellation (sets the event)."""
        self._event.set()

    def reset(self) -> None:
        """Clear the cancellation state for a new operation."""
        self._event.clear()


def check_cancelled(
    stop_event: Optional[Union[threading.Event, CancellationToken]] = None,
    message: str = "Operation cancelled by user."
) -> None:
    """
    Check if cancellation was requested and raise if so.

    This is a convenience function for simple use cases where you don't
    need the full CancellationToken class. It's a drop-in replacement for
    the local check_cancelled() functions used throughout the codebase.

    Args:
        stop_event: A threading.Event or CancellationToken to check.
                    If None, does nothing (allows optional cancellation).
        message: Custom message for the exception.

    Raises:
        CancellationError: If the event is set (cancellation requested).

    Example:
        def process_items(items, stop_event=None):
            for item in items:
                check_cancelled(stop_event)
                process(item)
    """
    if stop_event is None:
        return

    if isinstance(stop_event, CancellationToken):
        stop_event.check(message)
    elif stop_event.is_set():
        raise CancellationError(message)
