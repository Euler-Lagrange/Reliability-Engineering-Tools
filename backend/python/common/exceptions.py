#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Custom Exceptions for Reliability Tools Suite

This module provides a hierarchy of custom exceptions used across all
reliability engineering tools. Using specific exception types allows for:
- Better error handling and recovery
- Clearer error messages to users
- Easier debugging and logging

Hierarchy:
    ReliabilityToolError (base)
    |-- ValidationError      - Data validation failures (FMR sums, duplicates)
    |-- FileAccessError      - File I/O problems (locked, missing, corrupt)
    |-- ColumnMappingError   - Required column not found in data
    +-- ProcessingError      - General processing failures

Usage:
    from common.exceptions import ValidationError, ColumnMappingError

    # Raise when FMR validation fails
    raise ValidationError("FMR sum for U200 is 0.85, expected 1.0")

    # Raise when required column not found
    raise ColumnMappingError("RefDes", "BOM file", ["Reference Designator", "RefDes"])
"""

from typing import List, Optional


class ReliabilityToolError(Exception):
    """
    Base exception for all reliability tool errors.

    All custom exceptions in this module inherit from this class,
    allowing callers to catch all tool-specific errors with a single
    except clause if desired.
    """
    pass


class ValidationError(ReliabilityToolError):
    """
    Raised when data validation fails.

    Examples:
        - FMR (Failure Mode Ratio) sum doesn't equal 1.0
        - Duplicate RefDes entries found
        - Invalid numeric values in required fields
        - Data format doesn't match expected pattern

    Attributes:
        message: Human-readable error description
        field: Optional name of the field that failed validation
        value: Optional value that caused the validation failure
    """

    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        value: Optional[str] = None
    ):
        self.field = field
        self.value = value
        super().__init__(message)


class FileAccessError(ReliabilityToolError):
    """
    Raised when a file cannot be read or written.

    Examples:
        - File not found
        - File locked by another application
        - Permission denied
        - File is corrupt or invalid format

    Attributes:
        message: Human-readable error description
        file_path: Path to the file that caused the error
        operation: The operation that failed ('read', 'write', 'delete')
    """

    def __init__(
        self,
        message: str,
        file_path: Optional[str] = None,
        operation: str = "access"
    ):
        self.file_path = file_path
        self.operation = operation
        super().__init__(message)


class ColumnMappingError(ReliabilityToolError):
    """
    Raised when a required column cannot be found in the data.

    This is typically raised during column detection when none of the
    expected synonyms match any column in the DataFrame.

    Attributes:
        column_name: The standard name of the missing column
        source_name: Name of the file/source being processed
        tried_synonyms: List of column names that were searched for
    """

    def __init__(
        self,
        column_name: str,
        source_name: str = "data",
        tried_synonyms: Optional[List[str]] = None
    ):
        self.column_name = column_name
        self.source_name = source_name
        self.tried_synonyms = tried_synonyms or []

        # Build informative message
        msg = f"Required column '{column_name}' not found in {source_name}."
        if self.tried_synonyms:
            synonyms_str = ", ".join(f"'{s}'" for s in self.tried_synonyms[:5])
            if len(self.tried_synonyms) > 5:
                synonyms_str += f" (and {len(self.tried_synonyms) - 5} more)"
            msg += f" Searched for: {synonyms_str}"
        super().__init__(msg)


class ProcessingError(ReliabilityToolError):
    """
    Raised when processing fails for a general reason.

    Use this for errors that don't fit into the more specific categories.
    When possible, prefer using ValidationError, FileAccessError, or
    ColumnMappingError for better error categorization.

    Attributes:
        message: Human-readable error description
        context: Optional description of what was being processed
        original_error: Optional original exception that caused this error
    """

    def __init__(
        self,
        message: str,
        context: Optional[str] = None,
        original_error: Optional[Exception] = None
    ):
        self.context = context
        self.original_error = original_error

        # Build message with context
        if context:
            message = f"{context}: {message}"
        super().__init__(message)


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    'ReliabilityToolError',
    'ValidationError',
    'FileAccessError',
    'ColumnMappingError',
    'ProcessingError',
]
