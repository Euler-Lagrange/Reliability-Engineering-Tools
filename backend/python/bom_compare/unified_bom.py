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
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple

import pandas as pd

from common import CancellationError, get_tool_logger
from common.exceptions import ColumnMappingError
from common.refdes_utils import (
    CONTROL_CHARS_PATTERN,
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
    # Same-prefix range guard (J1-J5, CN1-CN3): is_pin_notation lacks the
    # range discrimination is_instance_notation has, so apply it here —
    # a range token is not a manual expansion of its first element.
    prefix_match = re.match(r"^([A-Z]+)", canon)
    suffix = canon.split("-", 1)[1]
    if prefix_match and len(suffix) > 1 and suffix.startswith(prefix_match.group(1)):
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
        final = f"{name} (old)"
        n = 2
        while final.strip().casefold() in unified_fold:
            final = f"{name} (old {n})"
            n += 1
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
            plan_notes.append("A malformed column pair entry was ignored")
            continue
        a, b = str(pair[0]), str(pair[1])
        old_match = old_by_fold.get(a.strip().casefold())
        new_match = by_fold.get(b.strip().casefold())
        if old_match is None or new_match is None:
            plan_notes.append(
                f'Column pair "{a}" -> "{b}" did not match the loaded '
                f"headers and was ignored"
            )
            continue
        if old_match in handled:
            plan_notes.append(
                f'Column pair "{a}" -> "{b}" was ignored — "{a}" is '
                f"already mapped by an earlier pair"
            )
            continue
        _claim(old_match, new_match)
        handled.add(old_match)

    for c in old_cols:
        if c in handled:
            continue
        handled.add(c)
        c_trim = c.strip()
        target = by_fold.get(c_trim.casefold(), c_trim)
        _claim(c, target)

    # Tool-authored columns never clobber user data: collision-guard the
    # names against the union case-insensitively (same fold set _uniquify
    # uses), so a case-shadowed header like "status" still forces the
    # escalation to "Merge Status".
    tool_columns: Dict[str, str] = {}
    for key, wanted in (
        ("status", COL_STATUS),
        ("source", COL_SOURCE),
        ("notes", COL_NOTES),
    ):
        name = wanted
        while name.strip().casefold() in unified_fold:
            name = f"Merge {name}"
        unified.append(name)
        unified_fold.add(name.strip().casefold())
        tool_columns[key] = name
    return unified, old_to_unified, tool_columns, plan_notes


class _Entry(NamedTuple):
    """One row awaiting emission into the final Unified BOM frame."""
    values: Dict[str, Any]
    status: str
    source: str
    notes: List[str]


@dataclass
class _MergeContext:
    """Read-only merge state shared by the per-row builder functions below.

    Extracted (2026-08 adversarial-QA hardening pass) so the builders read
    and test as ordinary functions instead of nine closures buried inside
    one long function body. Holds exactly what build_matched_row /
    fill_row_from_old / old_row_is_dnp / the Task-3 suffix-carry stubs
    capture from build_unified_bom's local scope; per-call extras (like
    the DNP regex, or the token/index scans built during the merge) are
    passed as explicit parameters instead of folded in here.
    """

    old_df: pd.DataFrame
    new_df: pd.DataFrame
    old_refdes_col: str
    new_refdes_col: str
    unified_cols: List[str]
    old_to_unified: Dict[str, str]
    new_cols_set: set
    refdes_out_col: str
    old_label: str
    new_label: str


def _blank_row(ctx: _MergeContext) -> Dict[str, Any]:
    return {c: "" for c in ctx.unified_cols}


def _build_matched_row(
    ctx: _MergeContext, new_idx: int, token_to_old_row: Dict[str, int]
) -> Tuple[Dict[str, Any], List[str], int]:
    """New row's values merged with its matched old row(s).

    Returns (values, notes, integrity_flags). New values win; a blank
    new cell keeps the old value (flagged); old-only columns carry
    silently. Multi-token rows diff against every distinct matched old
    row, prefixing notes with the tokens each row covers.
    """
    values = _blank_row(ctx)
    # Per-row .iloc access (here and throughout the builders below) is the
    # readable form, kept deliberately at this scale — QA measured 0.73s
    # for a full merge @ 3000 rows.
    row = ctx.new_df.iloc[new_idx]
    for name in ctx.new_cols_set:
        if not _is_blank(row[name]):
            values[name] = row[name]

    notes: List[str] = []
    integrity_flags = 0
    rows_to_tokens: Dict[int, List[str]] = {}
    for tok, old_idx in token_to_old_row.items():
        rows_to_tokens.setdefault(old_idx, []).append(tok)
    multi = len(rows_to_tokens) > 1
    for old_idx in sorted(rows_to_tokens):
        prefix = f"[{', '.join(sorted(rows_to_tokens[old_idx]))}] " if multi else ""
        old_row = ctx.old_df.iloc[old_idx]
        for old_name, uni_col in ctx.old_to_unified.items():
            # The key columns define matching; their textual difference
            # (multi-token cells, formatting) is already expressed by
            # the row statuses — never diff or blank-keep them.
            if old_name == str(ctx.old_refdes_col) or uni_col == str(ctx.new_refdes_col):
                continue
            old_val = old_row[old_name]
            if _is_blank(old_val):
                continue
            current = values.get(uni_col, "")
            if uni_col in ctx.new_cols_set:
                new_val = row[uni_col]
                if _is_blank(new_val):
                    if _is_blank(current):
                        values[uni_col] = old_val
                        notes.append(
                            f'{prefix}{uni_col}: kept old value '
                            f'"{_cell_text(old_val)}" (new was blank)'
                        )
                        integrity_flags += 1
                    elif not _values_equal(current, old_val):
                        notes.append(
                            f'{prefix}{uni_col}: differing old values — '
                            f'kept "{_cell_text(current)}"'
                        )
                        integrity_flags += 1
                elif not _values_equal(old_val, new_val):
                    notes.append(
                        f'{prefix}{uni_col} changed from '
                        f'"{_cell_text(old_val)}" to "{_cell_text(new_val)}"'
                    )
            else:
                # Old-only column: the general manual-data carry.
                if _is_blank(current):
                    values[uni_col] = old_val
                elif not _values_equal(current, old_val):
                    notes.append(
                        f'{prefix}{uni_col}: differing old values — '
                        f'kept "{_cell_text(current)}"'
                    )
                    integrity_flags += 1
    return values, notes, integrity_flags


def _fill_row_from_old(ctx: _MergeContext, old_idx: int) -> Dict[str, Any]:
    """A row built purely from an old row (Delete / Carried rows)."""
    values = _blank_row(ctx)
    old_row = ctx.old_df.iloc[old_idx]
    for old_name, uni_col in ctx.old_to_unified.items():
        val = old_row[old_name]
        if not _is_blank(val):
            values[uni_col] = val
    return values


def _old_row_is_dnp(
    ctx: _MergeContext,
    old_idx: int,
    *,
    ignore_dnp: bool,
    dnp_re: "re.Pattern[str]",
    old_desc_col: Optional[str],
) -> bool:
    if not ignore_dnp:
        return False
    row = ctx.old_df.iloc[old_idx]
    text = _cell_text(row[ctx.old_refdes_col])
    if old_desc_col and old_desc_col in ctx.old_df.columns:
        text = f"{text} {_cell_text(row[old_desc_col])}"
    # B2: strip control characters before matching, like every sibling
    # site — an embedded control char (e.g. a stray null byte) can split
    # a keyword like "DNP" and defeat the word-boundary match.
    text = CONTROL_CHARS_PATTERN.sub("", text)
    return bool(dnp_re.search(text))


def _collect_suffix_entries(
    ctx: _MergeContext,
    tokens: List[str],
    old_suffix_rows_for_base: Dict[str, List[Tuple[int, str]]],
    new_all_tokens: set,
) -> List[Tuple[int, str]]:
    """Old suffix/pin rows to carry forward under a bare new row.

    Triggers only for a single-token new row whose token IS its own usage
    base — a bare RefDes like "U2000" (not "U2000-1", and not a
    multi-token cell). Suffix tokens the new file lists on their own row
    are excluded: those exact-match their own backbone row instead of
    carrying (see test_carry_skips_suffixes_the_new_file_already_lists).
    Order is preserved from old_suffix_rows_for_base (old-file row order),
    which the SUPERSEDED span note and the carried-row zip in the caller
    both depend on.
    """
    if len(tokens) != 1:
        return []
    tok = tokens[0]
    if get_usage_base_refdes(tok) != tok:
        return []
    return [
        (old_idx, suffix_tok)
        for old_idx, suffix_tok in old_suffix_rows_for_base.get(tok, [])
        if suffix_tok not in new_all_tokens
    ]


def _build_carried_rows(
    ctx: _MergeContext,
    bare_new_idx: int,
    suffix_entries: List[Tuple[int, str]],
    new_all_tokens: set,
) -> Tuple[List[Tuple[Dict[str, Any], List[str]]], int]:
    """Build the carried rows for one superseded bare row's suffix group.

    Carried rows keep the old data verbatim. A shared column (present in
    both files, and not a key column) is overwritten from the bare row's
    value ONLY when every carried old row agrees on that column (the
    uniform-column rule) AND the bare row's value is non-blank and
    genuinely differs — recorded once per column in the returned
    integrity count, with an update note on every carried row. Columns
    the old file left blank on a given row (including columns the old
    file never had at all) fall back to the bare row's value silently —
    there is no old value being "kept verbatim" to protect there.

    Returns (rows, integrity_count) where ``rows`` is a list of
    (values, notes) aligned 1:1 with ``suffix_entries`` — the caller
    zips them together, so order and length must match exactly.
    """
    if not suffix_entries:
        return [], 0

    bare_row = ctx.new_df.iloc[bare_new_idx]
    base = get_usage_base_refdes(suffix_entries[0][1])

    # Uniform-column scan: for every shared, non-key column, check whether
    # all carried old rows agree AND the bare row's value is a genuine,
    # non-blank difference. Computed once per column (not per row) so the
    # integrity count reflects columns, not carried-row multiplicity.
    overwrites: Dict[str, Tuple[str, str]] = {}
    integrity_count = 0
    for old_name, uni_col in ctx.old_to_unified.items():
        if (
            old_name == str(ctx.old_refdes_col)
            or uni_col == str(ctx.new_refdes_col)
            or uni_col == ctx.refdes_out_col
        ):
            continue  # key columns are never diffed/overwritten
        if uni_col not in ctx.new_cols_set:
            continue  # old-only column: pure carry, never a candidate

        group_values = [
            ctx.old_df.iloc[old_idx][old_name] for old_idx, _tok in suffix_entries
        ]
        if any(not _values_equal(group_values[0], v) for v in group_values[1:]):
            continue  # old suffix rows disagree — not uniform

        group_text = _cell_text(group_values[0])
        if not group_text:
            continue  # nothing to "update from"; blank-fill below handles it

        new_text = _cell_text(bare_row[uni_col])
        if not new_text or _values_equal(group_text, new_text):
            continue  # blank new value never overwrites; no genuine diff

        overwrites[uni_col] = (group_text, new_text)
        integrity_count += 1

    rows: List[Tuple[Dict[str, Any], List[str]]] = []
    for old_idx, tok in suffix_entries:
        values = _fill_row_from_old(ctx, old_idx)
        # New-only columns (and any shared column left blank on this
        # particular old row) fall back to the bare row's value silently
        # — pure addition, not an overwrite of real old data.
        for name in ctx.new_cols_set:
            if _is_blank(values[name]) and not _is_blank(bare_row[name]):
                values[name] = bare_row[name]
        values[ctx.refdes_out_col] = tok

        notes = [
            f"Carried forward from {ctx.old_label} (manual suffix row of {base})"
        ]
        for uni_col, (old_text, new_text) in overwrites.items():
            values[uni_col] = bare_row[uni_col]
            notes.append(
                f'{uni_col} updated from "{old_text}" to "{new_text}" '
                f"by {ctx.new_label}"
            )

        rows.append((values, notes))

    return rows, integrity_count


def build_unified_bom(
    old_df: pd.DataFrame,
    new_df: pd.DataFrame,
    *,
    old_refdes_col: str,
    new_refdes_col: str,
    old_label: str = "Old BOM",
    new_label: str = "New BOM",
    column_pairs: Optional[List[Tuple[str, str]]] = None,
    ignore_dnp: bool = True,
    dnp_regex: Optional[str] = None,
    old_desc_col: Optional[str] = None,
    stop_event: Optional[threading.Event] = None,
    log_callback: Optional[Callable[[str], None]] = None,
) -> UnifiedBomResult:
    """Merge old/new BOM frames into the Unified BOM sheet model.

    See the module docstring and the design spec for the full rules.
    Raises ColumnMappingError when a RefDes column is missing from a
    non-empty frame, CancellationError when stop_event fires.
    """
    # Lazy import: bom_compare_logic re-exports this module (facade), so a
    # module-level import would make `import bom_compare.unified_bom`
    # order-dependent. See the NOTE at the top of the file.
    from .bom_compare_logic import DEFAULT_DNP_REGEX

    def log(msg: str) -> None:
        if log_callback:
            log_callback(msg)
        _logger.info(msg)

    old_df = old_df if old_df is not None else pd.DataFrame()
    new_df = new_df if new_df is not None else pd.DataFrame()
    # Normalize headers to strings once: numeric Excel headers are real in
    # this repo, and every downstream lookup (old_to_unified keys, row
    # indexing, unified column list) speaks str.
    old_df = old_df.rename(columns=str)
    new_df = new_df.rename(columns=str)

    if not new_df.empty and new_refdes_col not in new_df.columns:
        raise ColumnMappingError(
            f"RefDes column '{new_refdes_col}' not found in the newer file"
        )
    if not old_df.empty and old_refdes_col not in old_df.columns:
        raise ColumnMappingError(
            f"RefDes column '{old_refdes_col}' not found in the older file"
        )

    # Falsy regex falls back to the canonical default, NEVER re.compile('')
    # (mirrors custom_compare / group_analysis).
    dnp_source = dnp_regex or DEFAULT_DNP_REGEX
    invalid_dnp_regex = False
    try:
        dnp_re = re.compile(dnp_source, re.I)
    except re.error:
        _logger.warning(f"Invalid DNP regex pattern, using default: {dnp_regex}")
        dnp_re = re.compile(DEFAULT_DNP_REGEX, re.I)
        invalid_dnp_regex = True

    unified_cols, old_to_unified, tool_cols, plan_notes = _plan_columns(
        old_df, new_df, column_pairs
    )
    new_cols_set = {str(c) for c in new_df.columns}

    # B6: when the two files' key columns have different headers, the old
    # key's own column renders blank on every surviving row and filled only
    # on Delete rows — a broken-looking column. Row identity lives in the
    # new key column, and Delete rows already carry the original cell in
    # their notes, so drop the old key's target from the union entirely.
    # Skipped when the new file is empty: there's no new key column to
    # anchor identity to, so the old key column remains the output key.
    # Also skipped when the old key's target is a column the NEW file
    # itself owns (e.g. old key header "RefDes" name-collides with a real
    # "RefDes" data column while the new file's actual key is "Reference
    # Designator") — that column isn't the old key's alone to remove; the
    # new file's own values live there and must not be silently dropped.
    old_key_target = old_to_unified.get(str(old_refdes_col))
    if (
        not new_df.empty
        and old_key_target is not None
        and old_key_target != str(new_refdes_col)
        and old_key_target not in new_cols_set
    ):
        old_to_unified.pop(str(old_refdes_col))
        unified_cols.remove(old_key_target)
    status_col = tool_cols["status"]
    source_col = tool_cols["source"]
    notes_col = tool_cols["notes"]

    # The column Delete/Carried rows write their RefDes token into: the
    # new file's key column when it exists, else the old key's target.
    refdes_out_col = (
        str(new_refdes_col)
        if str(new_refdes_col) in unified_cols
        else old_to_unified.get(str(old_refdes_col), str(old_refdes_col))
    )

    ctx = _MergeContext(
        old_df=old_df,
        new_df=new_df,
        old_refdes_col=old_refdes_col,
        new_refdes_col=new_refdes_col,
        unified_cols=unified_cols,
        old_to_unified=old_to_unified,
        new_cols_set=new_cols_set,
        refdes_out_col=refdes_out_col,
        old_label=old_label,
        new_label=new_label,
    )

    def check_cancel(i: int) -> None:
        if stop_event is not None and i % _CANCEL_CHECK_EVERY == 0 and stop_event.is_set():
            raise CancellationError("Unified BOM merge cancelled.")

    # ------------------------------------------------------------------
    # Scan the old file: token -> first row, suffix rows grouped by base.
    # ------------------------------------------------------------------
    old_tokens_by_row: List[List[str]] = []
    old_first_row_for_token: Dict[str, int] = {}
    old_suffix_rows_for_base: Dict[str, List[Tuple[int, str]]] = {}
    # B1: a duplicate old RefDes must never vanish silently. Keyed by the
    # FIRST occurrence's row index so the note can attach wherever that
    # row ends up (a backbone match or a Delete row) — popped from there,
    # never double-counted; anything still unpopped after both passes
    # (e.g. the first occurrence was itself DNP-suppressed) is a leftover
    # surfaced separately.
    old_dup_notes_by_first_row: Dict[int, List[str]] = {}
    for idx in range(len(old_df)):
        check_cancel(idx)
        tokens = _row_tokens(old_df.iloc[idx][old_refdes_col])
        old_tokens_by_row.append(tokens)
        for tok in tokens:
            if tok in old_first_row_for_token:
                old_dup_notes_by_first_row.setdefault(
                    old_first_row_for_token[tok], []
                ).append(
                    f"Duplicate RefDes {tok} in {old_label} — old row "
                    f"{idx + 2} was not merged (first occurrence used)"
                )
                continue  # first old occurrence wins (deterministic)
            old_first_row_for_token[tok] = idx
            base = get_usage_base_refdes(tok)
            if _is_suffix_of(tok, base):
                old_suffix_rows_for_base.setdefault(base, []).append((idx, tok))

    # ------------------------------------------------------------------
    # Scan the new file: token -> first row, duplicate tracking.
    # ------------------------------------------------------------------
    new_tokens_by_row: List[List[str]] = []
    new_token_first_row: Dict[str, int] = {}
    duplicate_notes_by_row: Dict[int, List[str]] = {}
    for idx in range(len(new_df)):
        check_cancel(idx)
        tokens = _row_tokens(new_df.iloc[idx][new_refdes_col])
        new_tokens_by_row.append(tokens)
        for tok in tokens:
            if tok in new_token_first_row:
                duplicate_notes_by_row.setdefault(idx, []).append(
                    f"Duplicate RefDes {tok} — first occurrence "
                    f"(row {new_token_first_row[tok] + 2}) was used for matching"
                )
            else:
                new_token_first_row[tok] = idx
    new_all_tokens = set(new_token_first_row)

    # ------------------------------------------------------------------
    # Backbone emission: every new-file row, in order.
    # ------------------------------------------------------------------
    entries: List[_Entry] = []
    consumed_old_rows: Dict[int, int] = {}  # old row idx -> entry idx
    carried_tokens: set = set()
    counts = {
        "added": 0, "deleted": 0, "changed": 0,
        "carried": 0, "superseded": 0, "unchanged": 0,
    }
    warning_flags = 0

    src_both = "Both"
    src_new_only = f"{new_label} only"
    src_old_only = f"{old_label} only"
    src_carried = f"{old_label} (carried)"
    src_superseded = f"{new_label} (superseded)"

    for new_idx in range(len(new_df)):
        check_cancel(new_idx)
        tokens = new_tokens_by_row[new_idx]
        dup_notes = duplicate_notes_by_row.get(new_idx, [])

        # Exact-token matches (first new occurrence only — duplicates never
        # re-match; first old occurrence supplies the values).
        token_to_old_row = {
            t: old_first_row_for_token[t]
            for t in tokens
            if t in old_first_row_for_token and new_token_first_row.get(t) == new_idx
        }

        suffix_entries = _collect_suffix_entries(
            ctx, tokens, old_suffix_rows_for_base, new_all_tokens
        )

        # B1: any old-file duplicate notes owned by the old row(s) this
        # backbone row consumed — surfaced here, before the status
        # decision, so they count toward Changed like any other note.
        dup_old_notes: List[str] = []
        for old_idx in sorted(set(token_to_old_row.values())):
            dup_old_notes.extend(old_dup_notes_by_first_row.pop(old_idx, []))

        values, notes, integrity_flags = _build_matched_row(ctx, new_idx, token_to_old_row)
        warning_flags += integrity_flags + len(dup_notes) + len(dup_old_notes)
        notes = dup_notes + dup_old_notes + notes

        added_tokens = [t for t in tokens if t not in old_first_row_for_token]
        # B3: Source reflects genuine token membership in the old file, not
        # whether THIS row happened to win the match (a duplicate new row
        # never matches, even when its token is known to the old file).
        known_in_old = any(t in old_first_row_for_token for t in tokens)

        if suffix_entries:
            status = STATUS_SUPERSEDED
            source = src_superseded
            first_tok, last_tok = suffix_entries[0][1], suffix_entries[-1][1]
            span = first_tok if len(suffix_entries) == 1 else f"{first_tok} … {last_tok}"
            notes.insert(
                0,
                f"Superseded by {len(suffix_entries)} carried rows ({span}) "
                f"— delete this row",
            )
            counts["superseded"] += 1
        elif tokens and len(added_tokens) == len(tokens):
            status = STATUS_ADDED
            source = src_new_only
            notes.insert(0, f"Not in {old_label} — new part; add to the FMEAs")
            counts["added"] += 1
        else:
            for t in added_tokens:
                notes.append(f"{t} is not in {old_label} — new on this row")
            if notes:
                status = STATUS_CHANGED
                source = src_both if known_in_old else src_new_only
                counts["changed"] += 1
            else:
                status = ""
                source = src_both if known_in_old else src_new_only
                counts["unchanged"] += 1

        entry_idx = len(entries)
        entries.append(_Entry(values, status, source, notes))
        for old_idx in set(token_to_old_row.values()):
            consumed_old_rows.setdefault(old_idx, entry_idx)

        if suffix_entries:
            carried_rows, cflags = _build_carried_rows(
                ctx, new_idx, suffix_entries, new_all_tokens
            )
            warning_flags += cflags
            for (cvalues, cnotes), (old_idx, tok) in zip(carried_rows, suffix_entries):
                carried_tokens.add(tok)
                centry_idx = len(entries)
                entries.append(_Entry(cvalues, STATUS_CARRIED, src_carried, cnotes))
                consumed_old_rows.setdefault(old_idx, centry_idx)
                counts["carried"] += 1

    # ------------------------------------------------------------------
    # Deletion pass: old-only tokens, inserted inline after their anchor.
    # ------------------------------------------------------------------
    insertions: Dict[int, List[_Entry]] = {}
    dnp_skipped = 0
    anchor = -1
    for old_idx in range(len(old_df)):
        check_cancel(old_idx)
        if old_idx in consumed_old_rows:
            anchor = consumed_old_rows[old_idx]
        tokens = old_tokens_by_row[old_idx]
        deleted_tokens = [
            t for t in tokens
            if t not in new_all_tokens
            and t not in carried_tokens
            and old_first_row_for_token.get(t) == old_idx
        ]
        if not deleted_tokens:
            continue
        if _old_row_is_dnp(
            ctx, old_idx, ignore_dnp=ignore_dnp, dnp_re=dnp_re, old_desc_col=old_desc_col
        ):
            dnp_skipped += len(deleted_tokens)
            continue
        original_cell = _cell_text(old_df.iloc[old_idx][old_refdes_col])
        multi = len(tokens) > 1
        bucket = insertions.setdefault(anchor, [])
        for tok in deleted_tokens:
            values = _fill_row_from_old(ctx, old_idx)
            values[refdes_out_col] = tok
            base = get_usage_base_refdes(tok)
            if tok != base and base in new_all_tokens:
                # The base exists in the new file but this suffix row could
                # not auto-carry (multi-RefDes new row, or a prefix outside
                # the instance/pin notation sets) — flag loudly instead of
                # silently deleting manual data.
                note = (
                    f"{tok} is not in {new_label}, but its base {base} is — "
                    f"manual expansion was not auto-carried; review before deleting"
                )
            else:
                note = f"Not in {new_label} — remove from the FMEAs"
            row_notes = [note]
            if multi:
                row_notes.append(f'From an old row listing "{original_cell}"')
            # B1: this Delete row IS the anchor for any old-file duplicate
            # note owned by old_idx (the first occurrence) — attach and
            # count it here so it's never dropped nor double-counted.
            dup_old_notes_here = old_dup_notes_by_first_row.pop(old_idx, [])
            row_notes.extend(dup_old_notes_here)
            warning_flags += len(dup_old_notes_here)
            bucket.append(_Entry(values, STATUS_DELETE, src_old_only, row_notes))
            counts["deleted"] += 1

    # B1: anything still left in the dict belongs to a duplicate whose
    # first occurrence was never emitted at all (e.g. DNP-suppressed) —
    # it has no row to attach to, so it surfaces in the run notes instead
    # of vanishing.
    leftover_dup_notes: List[str] = []
    for pending_notes in old_dup_notes_by_first_row.values():
        for note in pending_notes:
            leftover_dup_notes.append(note)
            warning_flags += 1

    # ------------------------------------------------------------------
    # Assembly
    # ------------------------------------------------------------------
    final_rows: List[Dict[str, Any]] = []
    row_styles: List[str] = []

    def emit(entry: _Entry) -> None:
        values, status, source, entry_notes = entry
        values[status_col] = status
        values[source_col] = source
        values[notes_col] = "; ".join(entry_notes)
        final_rows.append(values)
        row_styles.append(STATUS_STYLES.get(status, ""))

    for entry in insertions.get(-1, []):
        emit(entry)
    for i, entry in enumerate(entries):
        emit(entry)
        for pending in insertions.get(i, []):
            emit(pending)

    frame = pd.DataFrame(final_rows, columns=unified_cols)

    summary = (
        f"Unified BOM: {len(frame)} rows — {counts['added']} added, "
        f"{counts['deleted']} to delete, {counts['changed']} changed, "
        f"{counts['carried']} carried forward, {counts['superseded']} superseded"
    )
    notes_out = [summary]
    notes_out.extend(plan_notes)
    warning_flags += len(plan_notes)
    notes_out.extend(leftover_dup_notes)
    if invalid_dnp_regex:
        # B4: a bad custom DNP pattern falls back silently in effect, but
        # must not be silent in the notes — the compare side already
        # counts this against warning_count, so it isn't added again here.
        notes_out.append(
            "Unified BOM: the custom DNP pattern was invalid — the default "
            "pattern was used."
        )
    if dnp_skipped:
        notes_out.append(
            f"Unified BOM: {dnp_skipped} DNP-only old RefDes were not emitted "
            f"as deletions (Ignore DNP is on)."
        )
    counts["dnp_skipped"] = dnp_skipped
    log(summary)
    return UnifiedBomResult(
        frame=frame,
        row_styles=row_styles,
        counts=counts,
        warning_count=warning_flags,
        notes=notes_out,
    )
