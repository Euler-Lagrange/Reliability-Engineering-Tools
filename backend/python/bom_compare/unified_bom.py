#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BOM Compare - Unified BOM Merge Module

Merges an old and a new BOM into one reviewable "Unified BOM" sheet: the
new file's rows are the backbone (new values win conflicts), the old
file's manual data is carried forward (old-only columns, suffix/pin
expansion rows), and every row carries a Status / Source / Change Notes
triple so additions, deletions, supersessions and value changes are
explicit and filterable.

Design spec: docs/superpowers/specs/2026-08-13-unified-bom-design.md
"""
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from common import CancellationError, get_tool_logger
from common.exceptions import ColumnMappingError
from common.refdes_utils import (
    canonicalize_refdes,
    get_usage_base_refdes,
    split_refdes_list,
)

from .bom_compare_logic import DEFAULT_DNP_REGEX

_logger = get_tool_logger("bom_compare")

SHEET_UNIFIED = "Unified BOM"

STATUS_ADDED = "Added"
STATUS_DELETE = "Delete"
STATUS_SUPERSEDED = "Superseded"
STATUS_CHANGED = "Changed"
STATUS_CARRIED = "Carried"

# Semantic style key (common.excel_styles) per status; rows without a
# status keep default styling. The hex values behind these keys are
# exactly Excel's built-in Good / Bad / Neutral palette.
STATUS_STYLES: Dict[str, str] = {
    STATUS_ADDED: "success",         # green C6EFCE / 006100
    STATUS_DELETE: "error",          # red   FFC7CE / 9C0006
    STATUS_SUPERSEDED: "highlight",  # blue  BDD7EE / 1F4E79
    STATUS_CHANGED: "warning",       # yellow FFEB9C / 9C5700
    STATUS_CARRIED: "warning",
}

COL_STATUS = "Status"
COL_SOURCE = "Source"
COL_NOTES = "Change Notes"

_CANCEL_CHECK_EVERY = 200


@dataclass
class UnifiedBomResult:
    frame: pd.DataFrame = field(default_factory=pd.DataFrame)
    row_styles: List[str] = field(default_factory=list)
    counts: Dict[str, int] = field(default_factory=dict)
    warning_count: int = 0
    notes: List[str] = field(default_factory=list)


def _cell_text(value: Any) -> str:
    """NaN-safe trimmed string for comparisons and notes ('' for blank)."""
    if value is None:
        return ""
    if pd.api.types.is_scalar(value) and pd.isna(value):
        return ""
    return str(value).strip()


def _is_blank(value: Any) -> bool:
    return _cell_text(value) == ""


def _values_equal(a: Any, b: Any) -> bool:
    """Trimmed, case-insensitive, numeric-equivalent comparison.

    '10' vs '10.0' is NOT a change; 'RES 10K' vs 'res 10k' is NOT a
    change. The new value still lands in the cell either way — this only
    decides whether the difference is *reported*.
    """
    ta, tb = _cell_text(a), _cell_text(b)
    if ta.casefold() == tb.casefold():
        return True
    try:
        return float(ta) == float(tb)
    except (TypeError, ValueError):
        return False


def _row_tokens(cell: Any) -> List[str]:
    """Canonical RefDes tokens for one cell (multi-token cells split)."""
    tokens: List[str] = []
    for tok in split_refdes_list(cell):
        canon = canonicalize_refdes(tok)
        if canon:
            tokens.append(canon)
    return tokens


def _is_suffix_of(token: str, base: str) -> bool:
    """True when ``token`` is a manual suffix/pin row of ``base``.

    Pin-style tokens (J4-P1) and instance suffixes (U2000-3) both reduce
    to their component base via get_usage_base_refdes; the token must
    actually differ from the base so a bare row never counts as its own
    suffix.
    """
    return token != base and get_usage_base_refdes(token) == base


def _plan_columns(
    old_df: pd.DataFrame,
    new_df: pd.DataFrame,
    column_pairs: Optional[List[Tuple[str, str]]],
) -> Tuple[List[str], Dict[str, str], Dict[str, str]]:
    """Build the unified column layout.

    Returns (unified_columns, old_to_unified, tool_columns) where:
    - unified_columns: the new file's columns in original order, then
      old-only columns (old-file order), then the three tool-authored
      columns (Status / Source / Change Notes).
    - old_to_unified: every old column name -> the unified column it
      fills. Identity is case-insensitive exact header match; explicit
      column_pairs (old_col, new_col) win over the name match.
    - tool_columns: {"status": ..., "source": ..., "notes": ...} — the
      actual (collision-guarded) tool column names.
    """
    new_cols = [str(c) for c in new_df.columns]
    old_cols = [str(c) for c in old_df.columns]

    by_fold: Dict[str, str] = {}
    for c in new_cols:
        by_fold.setdefault(c.strip().casefold(), c)

    old_to_unified: Dict[str, str] = {}
    for pair in column_pairs or []:
        old_col, new_col = str(pair[0]), str(pair[1])
        if old_col in old_cols and new_col in new_cols:
            old_to_unified[old_col] = new_col
    for c in old_cols:
        if c in old_to_unified:
            continue
        old_to_unified[c] = by_fold.get(c.strip().casefold(), c)

    unified = list(new_cols)
    for c in old_cols:
        target = old_to_unified[c]
        if target not in unified:
            unified.append(target)

    # Tool-authored columns never clobber user data: collision-guard the
    # names against the union ("Status" in a source file -> "Merge Status").
    tool_columns: Dict[str, str] = {}
    for key, wanted in (
        ("status", COL_STATUS),
        ("source", COL_SOURCE),
        ("notes", COL_NOTES),
    ):
        name = wanted
        while name in unified:
            name = f"Merge {name}"
        unified.append(name)
        tool_columns[key] = name
    return unified, old_to_unified, tool_columns
