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
    is_instance_notation,
    is_pin_notation,
    split_refdes_list,
)

# NOTE: DEFAULT_DNP_REGEX is deliberately NOT imported at module level.
# bom_compare_logic re-exports this module (facade pattern), so a
# module-level import here would make `import bom_compare.unified_bom`
# order-dependent (ImportError when imported before the facade).
# build_unified_bom lazy-imports it at call time instead.

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


_PLAIN_DECIMAL = re.compile(r"^[+-]?\d+(?:\.\d*)?$")


def _canonical_decimal(text: str) -> Optional[str]:
    """Canonical form for plain decimal literals, else None.

    Only plain decimals qualify (no exponents, underscores, or thousands
    separators): numeric equivalence exists to absorb Excel float
    formatting ("10" vs "10.0"), never to equate rewritten identifiers
    ("0123" vs "123" IS a change worth reporting).
    """
    if not _PLAIN_DECIMAL.match(text):
        return None
    sign = "-" if text.startswith("-") else ""
    body = text.lstrip("+-")
    if "." in body:
        int_part, frac = body.split(".", 1)
        frac = frac.rstrip("0")
    else:
        int_part, frac = body, ""
    return f"{sign}{int_part}.{frac}" if frac else f"{sign}{int_part}"


def _values_equal(a: Any, b: Any) -> bool:
    """Trimmed, case-insensitive, numeric-equivalent comparison.

    '10' vs '10.0' is NOT a change; 'RES 10K' vs 'res 10k' is NOT a
    change. The new value still lands in the cell either way — this only
    decides whether the difference is *reported*. Numeric equivalence is
    restricted to plain-decimal formatting differences (see
    _canonical_decimal) — it never equates renumbered identifiers like
    "0123" vs "123" or float-precision-losing comparisons.
    """
    ta, tb = _cell_text(a), _cell_text(b)
    if ta.casefold() == tb.casefold():
        return True
    ca = _canonical_decimal(ta)
    if ca is not None:
        cb = _canonical_decimal(tb)
        if cb is not None:
            return ca == cb
    return False


def _row_tokens(cell: Any) -> List[str]:
    """Canonical RefDes tokens for one cell (multi-token cells split)."""
    if cell is None or (pd.api.types.is_scalar(cell) and pd.isna(cell)):
        return []
    tokens: List[str] = []
    for tok in split_refdes_list(cell):
        canon = canonicalize_refdes(tok)
        if canon:
            tokens.append(canon)
    return tokens


def _is_suffix_of(token: str, base: str) -> bool:
    """True when ``token`` is a manual HYPHENATED suffix/pin row of ``base``.

    Only hyphenated instance/pin notation qualifies (U2000-1, U2000-D4,
    J4-P1) — the user's manual expansions are always hyphenated. Range
    tokens (R1-R3) are excluded via is_instance_notation/is_pin_notation
    (a range is not an expansion of its first element), and trailing-letter
    variants (U1A) are excluded as distinct schematic parts. Prefixes
    outside the instance/pin notation sets simply never carry — their
    old rows surface as flagged Delete rows instead (visible, not silent).
    """
    canon = canonicalize_refdes(token)
    if not canon or canon == base or "-" not in canon:
        return False
    if not (is_instance_notation(canon) or is_pin_notation(canon)):
        return False
    return get_usage_base_refdes(canon) == base


def _plan_columns(
    old_df: pd.DataFrame,
    new_df: pd.DataFrame,
    column_pairs: Optional[List[Tuple[str, str]]],
) -> Tuple[List[str], Dict[str, str], Dict[str, str], List[str]]:
    """Build the unified column layout.

    Returns (unified_columns, old_to_unified, tool_columns, plan_notes)
    where:
    - unified_columns: the new file's columns in original order, then
      old-only columns (old-file order), then the three tool-authored
      columns (Status / Source / Change Notes).
    - old_to_unified: every old column name -> the unified column it
      fills. Identity is case-insensitive, trimmed exact header match;
      explicit column_pairs (old_col, new_col, ...) win over the name
      match and are themselves resolved case-insensitively/trimmed
      against both frames' real headers. Extra tuple elements (e.g. a
      rule string) are accepted and ignored.
    - tool_columns: {"status": ..., "source": ..., "notes": ...} — the
      actual (collision-guarded) tool column names.
    - plan_notes: human-readable notes about anything that could not be
      resolved cleanly — an explicit pair that didn't match a loaded
      header, or two old columns that fold onto the same unified target
      (the first claims it; the rest keep their own data under a
      uniquified " (old)"-suffixed name — data is never dropped).

    Every target may be claimed by exactly ONE old column: explicit pairs
    claim first (in the order given), then remaining old columns claim by
    case-insensitive/trimmed name match (old-file order). A losing old
    column never overwrites the winner's column — it keeps its own data
    under its own (uniquified) name instead.
    """
    new_cols = [str(c) for c in new_df.columns]
    old_cols = [str(c) for c in old_df.columns]

    by_fold: Dict[str, str] = {}
    for c in new_cols:
        by_fold.setdefault(c.strip().casefold(), c)

    old_by_fold: Dict[str, str] = {}
    for c in old_cols:
        old_by_fold.setdefault(c.strip().casefold(), c)

    unified: List[str] = list(new_cols)
    unified_fold: set = {c.strip().casefold() for c in unified}
    claimed_by_fold: Dict[str, str] = {}
    old_to_unified: Dict[str, str] = {}
    plan_notes: List[str] = []

    def _uniquify(name: str) -> str:
        final = name
        while final.strip().casefold() in unified_fold:
            final = f"{final} (old)"
        return final

    def _claim(old_col: str, target: str) -> None:
        fold_key = target.strip().casefold()
        prior = claimed_by_fold.get(fold_key)
        if prior is None:
            old_to_unified[old_col] = target
            claimed_by_fold[fold_key] = old_col
            if fold_key not in unified_fold:
                unified.append(target)
                unified_fold.add(fold_key)
            return
        # Collision: this old column never overwrites the winner. It
        # keeps its own data under a uniquified name instead of being
        # silently discarded.
        final = _uniquify(old_col.strip())
        old_to_unified[old_col] = final
        unified.append(final)
        unified_fold.add(final.strip().casefold())
        claimed_by_fold[final.strip().casefold()] = old_col
        plan_notes.append(
            f'Old column "{old_col}" kept separately as "{final}" — '
            f'"{target}" was already filled by old column "{prior}"'
        )

    handled: set = set()

    for pair in column_pairs or []:
        if len(pair) < 2:
            continue
        a, b = str(pair[0]), str(pair[1])
        old_match = old_by_fold.get(a.strip().casefold())
        new_match = by_fold.get(b.strip().casefold())
        if old_match is not None and new_match is not None and old_match not in handled:
            _claim(old_match, new_match)
            handled.add(old_match)
        else:
            plan_notes.append(
                f'Column pair "{a}" -> "{b}" did not match the loaded '
                f"headers and was ignored"
            )

    for c in old_cols:
        if c in handled:
            continue
        handled.add(c)
        c_trim = c.strip()
        target = by_fold.get(c_trim.casefold(), c_trim)
        _claim(c, target)

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
    return unified, old_to_unified, tool_columns, plan_notes
