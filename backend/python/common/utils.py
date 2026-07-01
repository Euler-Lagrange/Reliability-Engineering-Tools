#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Common Utilities for Reliability Tools Suite

This module contains shared utility functions used across all tools
to avoid code duplication and ensure consistent behavior.
"""
import errno
import os
import sys
import io
import re
import json
import time
import shutil
import hashlib
import tempfile
import subprocess
import secrets
from pathlib import Path
from datetime import datetime
from typing import Optional, List
from urllib.parse import urlparse, unquote

# Lazy imports
pd = None
_logger = None
_SUBPROCESS_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

def _ensure_logger():
    """Lazy load logger to avoid circular import."""
    global _logger
    if _logger is None:
        from .logger import get_tool_logger
        _logger = get_tool_logger("utils")
    return _logger

def _ensure_pandas():
    """Lazy load pandas to reduce startup time."""
    global pd
    if pd is None:
        import pandas as _pd
        pd = _pd
    return pd


# =============================================================================
# File Handling Utilities
# =============================================================================

def _is_file_readable(path: Path) -> bool:
    """
    Check if a file is immediately readable.

    Args:
        path: Path to the file

    Returns:
        True if file can be opened and read, False otherwise
    """
    try:
        with open(path, "rb") as f:
            f.read(1)
        return True
    except (PermissionError, OSError, IOError):
        return False


def _is_onedrive_cloud_only(path: Path) -> bool:
    """
    Check if a file is OneDrive cloud-only (not locally available).

    OneDrive cloud-only files have the 'O' (Offline) attribute.

    Args:
        path: Path to the file

    Returns:
        True if file appears to be cloud-only, False otherwise
    """
    try:
        result = subprocess.run(
            ["attrib", str(path)],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=_SUBPROCESS_NO_WINDOW,
        )
        # attrib output format: "A    O        C:\path\file.xlsx"
        # The 'O' flag indicates Offline (cloud-only)
        if result.returncode == 0:
            output = (result.stdout or "").strip()
            if not output:
                return False
            first_line = output.splitlines()[0].strip()
            path_str = str(path)
            # Parse only the attribute region before the path to avoid
            # false positives from path text (e.g., "...\\OneDrive\\...").
            attr_section = first_line.split(path_str, 1)[0] if path_str in first_line else first_line
            flags = {
                token.upper()
                for token in attr_section.split()
                if len(token) == 1 and token.isalpha()
            }
            return "O" in flags
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        pass
    return False


def _hydrate_onedrive_file(path: Path, log_func=None, cancel_check=None) -> bool:
    """
    Attempt to hydrate a OneDrive cloud-only file by pinning it.

    Uses 'attrib +P' to pin the file, which forces OneDrive to download
    the content locally. Waits with exponential backoff for the download
    to complete.

    Args:
        path: Path to the OneDrive file
        log_func: Optional logging function
        cancel_check: Optional callable returning True if cancelled

    Returns:
        True if file is now readable, False if hydration failed or cancelled
    """
    log = log_func or (lambda x: None)

    # Pin the file to force OneDrive download
    try:
        result = subprocess.run(
            ["attrib", "+P", str(path)],
            capture_output=True,
            timeout=10,
            creationflags=_SUBPROCESS_NO_WINDOW,
        )
        if result.returncode != 0:
            _ensure_logger().debug(f"attrib +P returned {result.returncode} for {path}")
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError) as e:
        _ensure_logger().debug(f"attrib +P failed for {path}: {e}")
        return False

    # Wait with exponential backoff for file to become readable
    # Backoff sequence: 0.5s, 1s, 2s, 4s, 8s (total ~15.5s)
    backoff_times = [0.5, 1.0, 2.0, 4.0, 8.0]

    for wait_time in backoff_times:
        # Check for cancellation before sleeping
        if cancel_check and cancel_check():
            log(f"  OneDrive sync cancelled for: {path.name}")
            return False
        time.sleep(wait_time)
        if _is_file_readable(path):
            log(f"  OneDrive file synced after {wait_time}s: {path.name}")
            return True
        log(f"  Waiting for OneDrive sync... ({wait_time}s)")

    return False


def _is_onedrive_path(path: Path) -> bool:
    r"""True when ``path`` lives under a OneDrive root.

    Decision A: prefer the OneDrive environment variables Windows sets
    (``%OneDrive%``, ``%OneDriveCommercial%``, ``%OneDriveConsumer%``) so we
    detect OneDrive mounted at a non-standard location and avoid a false hit on
    a folder merely *named* "onedrive". Falls back to the historical substring
    heuristic when none of the env vars are set (or the path is outside them).

    Uses a normalized directory-boundary prefix match (no filesystem access) so
    ``C:\OneDriveX`` does not match a ``C:\OneDrive`` root.
    """
    path_norm = os.path.normcase(os.path.abspath(str(path)))
    for env_name in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
        root = os.environ.get(env_name)
        if not root:
            continue
        root_norm = os.path.normcase(os.path.abspath(root))
        if path_norm == root_norm or path_norm.startswith(root_norm + os.sep):
            return True
    return "onedrive" in str(path).lower()


def ensure_file_available(path: Path, log_func=None, cancel_check=None) -> Path:
    """
    Ensure a file is available for reading, handling OneDrive cloud files.

    OneDrive may keep files in "cloud-only" state where the file appears
    to exist but content is stored in the cloud. This function detects
    cloud-only files and forces them to sync locally.

    Hydration Strategy:
    1. Quick check - try to read 1 byte (fast path for local files)
    2. Detect cloud-only state via 'attrib' command (look for 'O' flag)
    3. Pin file with 'attrib +P' to force OneDrive download
    4. Wait with exponential backoff (0.5s, 1s, 2s, 4s, 8s) for sync

    Works with both OneDrive Personal and OneDrive for Business.

    Args:
        path: Path to the file
        log_func: Optional logging function for progress updates
        cancel_check: Optional callable returning True if cancelled

    Returns:
        The path (unchanged). If hydration fails, returns the path anyway
        to let downstream code handle the error with appropriate context.
    """
    log = log_func or (lambda x: None)
    path = Path(path)

    # Early exit if file doesn't exist
    if not path.exists():
        return path

    # Fast path: check if file is immediately readable
    if _is_file_readable(path):
        return path

    # File exists but isn't readable - likely OneDrive cloud-only
    log(f"  Detecting OneDrive cloud-only file: {path.name}")

    # Check cloud-only state first.
    is_cloud = _is_onedrive_cloud_only(path)
    is_onedrive_hint = _is_onedrive_path(path)

    # Non-OneDrive unreadable files should not run attrib +P hydration.
    # Let downstream read logic report the actual read error context.
    if not is_cloud and not is_onedrive_hint:
        log(f"  File is not in a OneDrive path; skipping cloud hydration.")
        return path

    if is_cloud:
        log(f"  Confirmed cloud-only, attempting hydration...")
    else:
        log(f"  OneDrive path detected but cloud flag not set; attempting hydration...")

    # Attempt hydration
    if _hydrate_onedrive_file(path, log, cancel_check):
        return path

    # Hydration didn't work within timeout - log warning and return path
    # Let downstream code handle the error with appropriate context
    _ensure_logger().warning(
        f"Could not hydrate OneDrive file within timeout: {path}. "
        "Try opening the file in File Explorer first."
    )
    return path


def normalize_input_path(raw_path: Optional[str]) -> str:
    """
    Normalize a user/file-picker path string for reliable file checks.

    Handles:
    - Leading/trailing whitespace
    - Surrounding single/double quotes
    - file:// URIs (including Windows drive-letter and UNC forms)
    - User-home expansion and path normalization
    """
    if raw_path is None:
        return ""

    path = str(raw_path).strip()
    if not path:
        return ""

    # Remove accidental surrounding quotes from pasted values.
    if len(path) >= 2 and ((path[0] == '"' and path[-1] == '"') or (path[0] == "'" and path[-1] == "'")):
        path = path[1:-1].strip()

    # Convert file:// URIs to local filesystem paths.
    if path.lower().startswith("file://"):
        parsed = urlparse(path)
        decoded_path = unquote(parsed.path or "")
        netloc = unquote((parsed.netloc or "").strip())
        if os.name == "nt":
            if netloc and netloc.lower() != "localhost":
                # Drive-letter shorthand, e.g. file://C:/temp/file.xlsx
                if len(netloc) == 2 and netloc[1] == ":" and netloc[0].isalpha():
                    path = f"{netloc}{decoded_path}".replace("/", "\\")
                else:
                    # UNC path, e.g. file://server/share/folder/file.xlsx
                    path = f"\\\\{netloc}{decoded_path.replace('/', '\\')}"
            else:
                # Drive-letter path, e.g. file:///C:/temp/file.xlsx
                if decoded_path.startswith("/") and len(decoded_path) > 2 and decoded_path[2] == ":":
                    decoded_path = decoded_path[1:]
                path = decoded_path.replace("/", "\\")
        else:
            if netloc and netloc.lower() != "localhost":
                path = f"//{netloc}{decoded_path}"
            else:
                path = decoded_path

    path = os.path.expanduser(path.strip())
    return os.path.normpath(path) if path else ""


def preflight_input_file(label: str, raw_path: Optional[str], required: bool = True) -> dict:
    """
    Validate file-path readiness for GUI preflight checks.

    Returns a dict with normalized path and check outcomes so callers can
    produce precise status/toast/log messaging without repeating logic.
    """
    normalized = normalize_input_path(raw_path)
    exists = False
    is_file = False
    permission_denied = False
    if normalized:
        try:
            os.stat(normalized)
            exists = True
            is_file = os.path.isfile(normalized)
        except PermissionError:
            permission_denied = True
        except OSError as ex:
            if getattr(ex, "errno", None) in (errno.EACCES, errno.EPERM):
                permission_denied = True

    if not normalized:
        if required:
            code = "MISSING_REQUIRED"
            message = f"{label} is required."
            ready = False
        else:
            code = "MISSING_OPTIONAL"
            message = f"{label} not provided."
            ready = True
    elif permission_denied:
        code = "PERMISSION_DENIED"
        message = f"Permission denied accessing {label}: {normalized}"
        ready = False
    elif not exists:
        code = "NOT_FOUND"
        message = f"{label} not found: {normalized}"
        ready = False
    elif not is_file:
        code = "NOT_FILE"
        message = f"{label} is not a file: {normalized}"
        ready = False
    else:
        code = "OK"
        message = f"{label} ready."
        ready = True

    return {
        "label": label,
        "raw": "" if raw_path is None else str(raw_path),
        "path": normalized,
        "required": bool(required),
        "exists": exists,
        "is_file": is_file,
        "ready": ready,
        "code": code,
        "message": message,
    }


def list_excel_sheet_names(path: str, log_func=None) -> list:
    """
    Return sheet names for an Excel file, or empty list for non-Excel/errors.

    Handles OneDrive cloud-only files, locked files (BytesIO fallback),
    and legacy .xls files (via xlrd/pd.ExcelFile). Never raises — returns
    empty list on any error so callers can use ``if sheets:`` to decide
    whether to show a sheet picker.

    Args:
        path: Path to the file
        log_func: Optional logging function

    Returns:
        List of sheet name strings, or [] for non-Excel / errors
    """
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".xlsx", ".xlsm", ".xltx", ".xls"):
        return []

    try:
        path_obj = ensure_file_available(Path(path), log_func)
        resolved = str(path_obj)
    except Exception:
        return []

    def _read_sheet_names(source, engine_ext):
        """Read sheet names from a path or BytesIO, respecting engine choice."""
        if engine_ext == ".xls":
            pandas = _ensure_pandas()
            xls = pandas.ExcelFile(source, engine="xlrd")
            try:
                return list(xls.sheet_names)
            finally:
                xls.close()
        else:
            from openpyxl import load_workbook
            wb = load_workbook(source, read_only=True, data_only=True)
            names = list(wb.sheetnames)
            wb.close()
            return names

    try:
        return _read_sheet_names(resolved, ext)
    except (PermissionError, OSError):
        # File locked — try reading into memory (same pattern as _read_excel_robust)
        try:
            with open(resolved, "rb") as f:
                data = f.read()
            return _read_sheet_names(io.BytesIO(data), ext)
        except Exception as e2:
            if log_func:
                log_func(f"Warning: Could not read sheet names from {Path(resolved).name}: {e2}")
            return []
    except Exception as e:
        if log_func:
            log_func(f"Warning: Could not read sheet names from {Path(resolved).name}: {e}")
        return []


def try_read_table(path: str, header_row: int = 0, sheet_name=None, log_func=None, cancel_check=None) -> 'pd.DataFrame':
    """
    Robustly read a table file (Excel, CSV, or TXT) into a pandas DataFrame.

    Handles:
    - OneDrive cloud files
    - Files locked by other applications
    - Different encodings for CSV files
    - Multiple read attempts with fallbacks

    Args:
        path: Path to the file
        header_row: Row index to use as header (0-based)
        sheet_name: Excel sheet name or index (None = first sheet, backward compatible)
        log_func: Optional logging function
        cancel_check: Optional callable returning True if cancelled

    Returns:
        pandas DataFrame with string dtype

    Raises:
        IOError: If file cannot be read after all attempts or cancelled
    """
    pandas = _ensure_pandas()

    path_obj = ensure_file_available(Path(path), log_func, cancel_check)
    path = str(path_obj)
    ext = os.path.splitext(path)[1].lower()

    # Build shared kwargs for pandas.read_excel (sheet_name flows through all paths).
    # keep_default_na=False + na_values=[""] preserves the long-standing
    # "empty Excel cell -> NaN" behavior while stopping pandas from silently
    # coercing literal text like 'NA' / 'N/A' / 'NULL' to NaN. Without this, the
    # SAME data read from .xlsx and .csv diverged (the CSV branch below already
    # passes keep_default_na=False), so a RefDes/part/description legitimately
    # valued 'NA' vanished only for Excel inputs (Tier-1 fix).
    _excel_kwargs = {
        "header": header_row,
        "dtype": str,
        "keep_default_na": False,
        "na_values": [""],
    }
    if sheet_name is not None:
        _excel_kwargs["sheet_name"] = sheet_name

    def _read_excel_robust(p: str, engine: str = "openpyxl"):
        for attempt in range(3):
            # Check for cancellation before each attempt
            if cancel_check and cancel_check():
                from .cancellation import CancellationError
                raise CancellationError("File read cancelled by user.")
            try:
                return pandas.read_excel(p, engine=engine, **_excel_kwargs)
            except ValueError as ve:
                # Surface clear error for invalid sheet names
                if sheet_name is not None and "not found" in str(ve).lower():
                    raise IOError(
                        f"Sheet '{sheet_name}' not found in {Path(p).name}. "
                        "The file's sheets may have changed."
                    ) from ve
                raise
            except ImportError:
                if engine == "xlrd":
                    raise IOError(
                        "Legacy .xls files require the 'xlrd' package. "
                        "Install xlrd or convert the file to .xlsx."
                    )
                raise
            except (PermissionError, OSError):
                try:
                    # Try reading into memory first
                    with open(p, "rb") as f:
                        data = f.read()
                    with io.BytesIO(data) as bio:
                        return pandas.read_excel(bio, engine=engine, **_excel_kwargs)
                except ValueError as ve:
                    if sheet_name is not None and "not found" in str(ve).lower():
                        raise IOError(
                            f"Sheet '{sheet_name}' not found in {Path(p).name}. "
                            "The file's sheets may have changed."
                        ) from ve
                    raise
                except ImportError:
                    if engine == "xlrd":
                        raise IOError(
                            "Legacy .xls files require the 'xlrd' package. "
                            "Install xlrd or convert the file to .xlsx."
                        )
                    raise
                except (PermissionError, OSError, IOError) as e:
                    # M10: Catch specific exceptions instead of generic Exception
                    _ensure_logger().debug(f"Excel read attempt {attempt + 1} failed for {p}: {e}")
                    if attempt < 2:
                        time.sleep(0.5)
                        continue
                    # Last resort: copy to temp file
                    try:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                            tmp_path = tmp.name
                        shutil.copyfile(p, tmp_path)
                        try:
                            return pandas.read_excel(tmp_path, engine=engine, **_excel_kwargs)
                        except ImportError:
                            if engine == "xlrd":
                                raise IOError(
                                    "Legacy .xls files require the 'xlrd' package. "
                                    "Install xlrd or convert the file to .xlsx."
                                )
                            raise
                        finally:
                            try:
                                os.remove(tmp_path)
                            except OSError:
                                pass
                    except (PermissionError, OSError, IOError) as copy_err:
                        _ensure_logger().debug(f"Temp file fallback failed: {copy_err}")
                        raise
        raise IOError(f"Could not read {p}")

    if ext in (".csv", ".txt", ".tsv"):
        sep = '\t' if ext == ".tsv" else ','
        for attempt in range(3):
            if cancel_check and cancel_check():
                from .cancellation import CancellationError
                raise CancellationError("File read cancelled by user.")
            try:
                try:
                    return pandas.read_csv(path, header=header_row, dtype=str, keep_default_na=False, encoding="utf-8", sep=sep)
                except UnicodeDecodeError:
                    return pandas.read_csv(path, header=header_row, dtype=str, keep_default_na=False, encoding="latin-1", sep=sep)
            except (PermissionError, OSError) as e:
                _ensure_logger().debug(f"CSV/TSV read attempt {attempt + 1} failed for {path}: {e}")
                if attempt < 2:
                    time.sleep(0.5)
                    continue
                raise

    if ext in (".xlsx", ".xlsm", ".xltx"):
        return _read_excel_robust(path)

    if ext == ".xls":
        return _read_excel_robust(path, engine="xlrd")

    return pandas.read_excel(path, **_excel_kwargs)


def normalize_df_columns(df: 'pd.DataFrame') -> 'pd.DataFrame':
    """
    Clean DataFrame column names by removing hidden characters and normalizing whitespace.
    
    Args:
        df: Input DataFrame
        
    Returns:
        DataFrame with cleaned column names
    """
    cleaned = []
    for c in df.columns:
        s = str(c).replace("\ufeff", "").replace("\u200b", "").replace("\r", " ").replace("\n", " ")
        s = re.sub(r"\s+", " ", s).strip()
        cleaned.append(s)
    out = df.copy()
    out.columns = cleaned
    return out


# =============================================================================
# Column Detection Utilities
# =============================================================================

def detect_column(
    columns: List[str],
    synonyms: List[str],
    substring_match: bool = False
) -> Optional[str]:
    """
    Find a column by checking against a list of possible names/synonyms.

    Matching priority:
    1. Exact case-insensitive match
    2. Normalized match (ignoring special characters)
    3. Substring match (if enabled) - synonym appears within column name
       - Short synonyms (< 5 chars) require word boundaries to avoid false positives
       - Longer synonyms use simple substring matching

    Args:
        columns: List of actual column names
        synonyms: List of possible names to match
        substring_match: If True, also try substring matching as a fallback

    Returns:
        Matched column name or None

    Example:
        >>> detect_column(['Part Number', 'Qty'], ['PN', 'Part Number'])
        'Part Number'

        >>> detect_column(['BAE Part Number'], ['Part Number'], substring_match=True)
        'BAE Part Number'

        >>> detect_column(['partner_id'], ['part'], substring_match=True)
        None  # 'part' requires word boundary, doesn't match 'partner_id'
    """
    # Preserve first match when columns differ only by case (e.g., "ID" vs "id")
    cols_ci: dict[str, str] = {}
    for c in columns:
        cols_ci.setdefault(c.lower(), c)

    def norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", s.lower())

    cols_norm: dict[str, str] = {}
    for c in columns:
        cols_norm.setdefault(norm(c), c)

    # Pass 1: Exact case-insensitive match
    for syn in synonyms:
        if syn.lower() in cols_ci:
            return cols_ci[syn.lower()]

    # Pass 2: Normalized match (strip special chars)
    for syn in synonyms:
        if norm(syn) in cols_norm:
            return cols_norm[norm(syn)]

    # Pass 3: Substring match (optional)
    if substring_match:
        for col in columns:
            col_lower = col.lower().strip()
            for syn in synonyms:
                syn_lower = syn.lower().strip()
                # Use word-boundary matching for short synonyms to avoid false positives
                # e.g., "part" should NOT match "partner_id" or "department"
                if len(syn_lower) < 5:
                    # Word boundary match for short synonyms
                    pattern = r'\b' + re.escape(syn_lower) + r'\b'
                    if re.search(pattern, col_lower):
                        return col
                else:
                    # Substring match OK for longer synonyms (less ambiguous)
                    if syn_lower in col_lower:
                        return col

    return None


def ensure_columns_exist(df: 'pd.DataFrame', columns: List[str], source_name: str):
    """
    Verify that required columns exist in a DataFrame.
    
    Args:
        df: DataFrame to check
        columns: List of required column names
        source_name: Name of the data source (for error messages)
        
    Raises:
        ColumnMappingError: If any required columns are missing
    """
    missing = [col for col in columns if col and col not in df.columns]
    if missing:
        from .exceptions import ColumnMappingError
        raise ColumnMappingError(missing[0], source_name, tried_synonyms=missing)


# =============================================================================
# Hashing & Caching Utilities
# =============================================================================

def sha256_of_path(path: str, truncate: int = 16) -> Optional[str]:
    """
    Calculate SHA256 hash of a file.

    Args:
        path: Path to file
        truncate: Number of hex characters to return (default 16)

    Returns:
        Truncated hex digest, or None if the file cannot be read.

    Note:
        Returns None instead of a placeholder string to prevent cache key
        collisions when multiple files fail to hash (e.g., locked or permission denied).
        Callers should check for None and skip caching if hashing fails.
    """
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()[:truncate]
    except Exception as e:
        _ensure_logger().warning(f"Could not calculate SHA256 for {path}: {e}")
        return None


def get_cache_dir(subdir: str = "cache") -> Path:
    """
    Get the cache directory for storing temporary data.
    
    Args:
        subdir: Subdirectory name within logs folder
        
    Returns:
        Path to cache directory (created if needed)
    """
    # Try to find the logs directory relative to the app
    if getattr(sys, 'frozen', False):
        # Running as compiled EXE
        base = Path(sys.executable).parent
    else:
        # Running as script - go up from common to new_gui
        base = Path(__file__).resolve().parent.parent
    
    cache_dir = base / "logs" / subdir
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


# =============================================================================
# Run ID & Snapshot Utilities
# =============================================================================

def make_run_id() -> str:
    """
    Generate a unique run identifier combining timestamp and random hex.

    Returns:
        String in format "YYYYMMDD-HHMMSS-xxxx"
    """
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{ts}-{secrets.token_hex(2)}"


def build_output_filename(tool_id: str, mode: Optional[str] = None, suffix: str = ".xlsx") -> str:
    """Build a standardized output filename for any tool.

    Format: {ToolId}_{Mode}_{YYYYMMDD_HHMMSS}.{ext}

    Args:
        tool_id: Tool identifier (e.g., "BOM_Compare")
        mode: Optional mode descriptor (e.g., "Group")
        suffix: File extension including leading dot (default ".xlsx")

    Returns:
        Filename string like "BOM_Compare_Group_20260316_143022.xlsx"

    Examples:
        build_output_filename("BOM_Compare", "Group") -> "BOM_Compare_Group_20260316_143022.xlsx"
        build_output_filename("FMEA_Generator") -> "FMEA_Generator_20260316_143022.xlsx"
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    parts = [tool_id]
    if mode:
        parts.append(mode)
    parts.append(ts)
    base = "_".join(parts)
    return f"{base}{suffix}"


def write_snapshot(app_name: str, snapshot: dict, output_path: str = None) -> Optional[Path]:
    """
    Save a configuration snapshot as JSON alongside output files.

    Args:
        app_name: Name of the application
        snapshot: Dictionary of configuration data
        output_path: If provided, save next to this file; otherwise save to snapshots folder

    Returns:
        Path to saved snapshot or None on failure
    """
    snap_path = None  # Initialize to avoid UnboundLocalError in exception handler
    try:
        if output_path:
            # Validate output path to prevent path traversal attacks
            output_p = Path(output_path)
            parent_dir = str(output_p.parent) if output_p.parent != output_p else os.getcwd()
            config_filename = output_p.stem + ".config.json"
            validated_path = validate_output_path(parent_dir, config_filename)
            snap_path = Path(validated_path)
        else:
            snap_dir = get_cache_dir("snapshots")
            snap_path = snap_dir / f"{app_name}_{datetime.now():%Y%m%d_%H%M%S}.json"

        with open(snap_path, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, indent=2)
        return snap_path
    except Exception as e:
        _ensure_logger().warning(f"Could not write snapshot to {snap_path or '<unresolved>'}: {e}")
        return None


def validate_output_path(folder: str, filename: str) -> str:
    """
    Validate and construct safe output path, preventing path traversal attacks.

    Also validates Windows path length limits (260 characters) to prevent
    silent failures with long OneDrive or deeply nested paths.

    Args:
        folder: Output folder path (defaults to cwd if empty)
        filename: Output filename

    Returns:
        Resolved absolute path that is guaranteed to be within folder

    Raises:
        ValueError: If path is invalid, escapes the folder, or exceeds Windows limit
        TypeError: If filename is not a string

    Example:
        >>> validate_output_path("/home/user/output", "report.xlsx")
        '/home/user/output/report.xlsx'
        >>> validate_output_path("/home/user/output", "../../../etc/passwd")
        ValueError: Output path escapes folder: ../../../etc/passwd
    """
    # Windows MAX_PATH limit (B3 fix: prevent silent failures with long paths)
    MAX_WINDOWS_PATH = 260

    if not isinstance(filename, str):
        raise TypeError(f"filename must be a string, got {type(filename).__name__}")
    if not folder:
        folder = os.getcwd()
    # Resolve to absolute path (handles .. and symlinks)
    folder_real = os.path.realpath(folder)
    if not os.path.isdir(folder_real):
        raise ValueError(f"Output folder does not exist: {folder}")
    # Construct full path and verify it's still within folder
    full_path = os.path.realpath(os.path.join(folder_real, filename))
    # Use os.sep to prevent prefix attacks (e.g., "reports_evil" matching "reports")
    if not (full_path.startswith(folder_real + os.sep) or full_path == folder_real):
        raise ValueError(f"Output path escapes folder: {filename}")

    # B3: Validate Windows path length to prevent silent write failures
    if os.name == 'nt' and len(full_path) > MAX_WINDOWS_PATH:
        raise ValueError(
            f"Output path exceeds Windows {MAX_WINDOWS_PATH}-character limit "
            f"({len(full_path)} chars). Use a shorter folder path or filename."
        )

    return full_path


# =============================================================================
# String Cleaning Utilities
# =============================================================================

def clean_string(s) -> str:
    """
    Clean a string value by handling NaN/None and stripping whitespace.

    Args:
        s: Value to clean (can be str, None, NaN, or any type)

    Returns:
        Cleaned string with whitespace stripped, or empty string for None/NaN

    Examples:
        >>> clean_string("  hello  ")
        'hello'
        >>> clean_string(None)
        ''
        >>> clean_string(float('nan'))
        ''
    """
    if s is None:
        return ''
    # Handle pandas NA types
    if hasattr(s, '__class__') and 'NAType' in s.__class__.__name__:
        return ''
    # Handle numpy/pandas NaN
    try:
        if s != s:  # NaN check (NaN != NaN is True)
            return ''
    except (TypeError, ValueError):
        pass
    return str(s).strip()


def canonical_pn(pn: str) -> str:
    """
    Canonicalize a part number by converting to uppercase alphanumeric only.

    Removes all non-alphanumeric characters (spaces, dashes, dots, etc.)
    for consistent part number matching.

    Args:
        pn: Part number string to canonicalize

    Returns:
        Uppercase string with only letters and digits

    Examples:
        >>> canonical_pn("ABC-123-DEF")
        'ABC123DEF'
        >>> canonical_pn("p/n: 456.789")
        'PN456789'
        >>> canonical_pn("  Test-Part  ")
        'TESTPART'
    """
    s = clean_string(pn).upper()
    return re.sub(r'[^A-Z0-9]', '', s)


# =============================================================================
# Output File Utilities
# =============================================================================

def is_writable_directory(path: Path) -> bool:
    """Return True when ``path`` can accept a newly created file.

    Probes by creating a short-lived temporary file inside ``path``. Catches
    ``OSError`` which covers permission errors, read-only drives, exhausted
    disk, OneDrive read-only placeholders, and network hiccups.
    """
    try:
        with tempfile.TemporaryFile(dir=str(path)):
            return True
    except OSError:
        return False


def atomic_write_path(target: Path) -> Path:
    """Compute a sibling temporary path for atomic writes.

    Returns a path in the same directory as ``target`` (so ``os.replace``
    stays on the same filesystem) with a random infix. Callers should
    write to the returned path and then ``os.replace(tmp, target)`` on
    success.

    The returned path PRESERVES ``target``'s extension (e.g. ``.xlsx``) so
    writers that sniff format from the suffix (openpyxl in particular —
    see ``_validate_archive``) keep working on the temp file. This is why
    the layout is ``.<stem>.<hex>.part<suffix>`` instead of
    ``.<name>.<hex>.part``.
    """
    target = Path(target)
    suffix = target.suffix
    stem = target.stem
    return target.with_name(f".{stem}.{secrets.token_hex(4)}.part{suffix}")


def atomic_finalize(tmp_path: Path, target: Path, log_func=None) -> None:
    """Atomically promote ``tmp_path`` to ``target``.

    If ``target`` already exists it is overwritten atomically (via
    ``os.replace``). On any failure the temp file is removed and the
    exception propagates to the caller.
    """
    tmp_path = Path(tmp_path)
    target = Path(target)
    try:
        os.replace(str(tmp_path), str(target))
    except OSError:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        if log_func is not None:
            try:
                log_func(f"Failed to finalize output file to {target}")
            except Exception:  # pragma: no cover - defensive
                pass
        raise


def validate_explicit_output_directory(
    explicit_directory,
    log_func=None,
) -> Optional[Path]:
    """Validate a user-supplied output directory.

    Returns the resolved ``Path`` when ``explicit_directory`` is a real,
    writable directory. Returns ``None`` when ``explicit_directory`` is
    empty / missing / not a directory / not writable, emitting a WARNING
    via ``log_func`` and the module logger so the run log surfaces the
    fallback reason. Callers should fall back to their tool-specific
    "first input file parent" heuristic on ``None``.
    """
    def _warn(message: str) -> None:
        _ensure_logger().warning(message)
        if log_func is not None:
            try:
                log_func(f"WARNING: {message}")
            except Exception:  # pragma: no cover - defensive
                pass

    if not explicit_directory:
        return None
    candidate = str(explicit_directory).strip()
    if not candidate:
        return None
    try:
        path = Path(candidate).expanduser().resolve()
    except (OSError, ValueError) as exc:
        _warn(
            f"Failed to resolve outputDirectory '{candidate}': "
            f"{exc}. Falling back to input-file heuristic."
        )
        return None
    if not path.is_dir():
        _warn(
            f"Explicit outputDirectory '{candidate}' is not a directory; "
            f"falling back to input-file heuristic."
        )
        return None
    if not is_writable_directory(path):
        _warn(
            f"Explicit outputDirectory '{candidate}' is not writable; "
            f"falling back to input-file heuristic."
        )
        return None
    return path


def verify_excel_readable(path: Path) -> bool:
    """Smoke-verify that ``path`` is a loadable Excel workbook.

    Opens the workbook read-only via openpyxl without reading cell values.
    Returns True on success, False on any exception. Intended as a
    post-write sanity check after an atomic finalize.
    """
    try:
        from openpyxl import load_workbook  # local import to keep start-up lazy
        wb = load_workbook(str(path), read_only=True, data_only=True)
        try:
            wb.sheetnames  # touching the metadata is enough
        finally:
            wb.close()
        return True
    except Exception:
        return False



