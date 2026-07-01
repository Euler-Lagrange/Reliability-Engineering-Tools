#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BOM Compare - Group Analysis Module

Group-vs-BOM analysis pipeline: explode grouping/BOM files into token sets,
run comparison checks (missing, extra, warnings, duplicates, FMR, part usage),
and write Excel reports.
"""
import os
import re
import math
import datetime
import threading
from typing import Dict, List, Optional, Set, Tuple, Any

import pandas as pd

from common import (
    detect_column,
    ensure_columns_exist,
    get_tool_logger,
    style_worksheet,
    write_df_to_sheet,
    check_cancelled,
    CancellationError,
    FMR_TOLERANCE,
    get_synonyms,
    parse_usage,
    to_reason_code_label,
    to_user_facing_text,
)
from common.exceptions import ColumnMappingError
from common.refdes_utils import (
    canonicalize_refdes,
    get_base_refdes,
    get_usage_base_refdes,
    expand_refdes_range,
    split_refdes_list,
    TOKEN_SPLIT_REGEX,
    CONTROL_CHARS_PATTERN,
)
from common.validation_utils import (
    validate_part_usage,
    validate_usage_format,
    validate_fmr_usage_product,
)
from common.fmea_utils import (
    is_fmea_file,
    classify_fmea_rows,
)

from .bom_compare_logic import ColumnMapping, AnalyzeOptions, AnalyzeResults, DEFAULT_DNP_REGEX

_logger = get_tool_logger("bom_compare")

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------
MULTIPLIERS = {
    "single": 1, "dual": 2, "triple": 3, "tri": 3, "quad": 4,
    "penta": 5, "hex": 6, "octal": 8, "deca": 10
}
RE_PINCOUNT = re.compile(r"(\d+)\s*[-]?\s*pin(s)?", re.I)
RE_ARRAY = re.compile(r"(\d+)\s*x\s*(\d+)", re.I)
CONNECTOR_WORDS = re.compile(r"\b(connector|header|socket|plug|jack|backplane)\b", re.I)
IGNORE_NUMBER_CONTEXT = re.compile(
    r"\b(?:SOIC|TSSOP|QFN|BGA|QFP|DFN|SOT|LQFP|MSOP)\s*-?\s*\d+\b"
    r"|(?:\b(?:0402|0603|0805|1206)\b)"
    r"|(?:\b\d+\s*(?:bit|mhz|ghz|khz|v|mv|kohm|ohm|mΩ)\b)",
    re.I
)

MAX_RANGE_EXPANSION = 5000  # Maximum range like R1-R5000 to expand

# Backward compatibility aliases for common.refdes_utils functions
expand_range_token = expand_refdes_range
canonicalize_token = canonicalize_refdes
base_of_token = get_base_refdes

# -----------------------------------------------------------------------------
# Token Parsing
# -----------------------------------------------------------------------------

def infer_expected_count(description: Optional[str]) -> int:
    """Infer expected component count from description (e.g., 'DUAL OP AMP' -> 2)."""
    if not description: return 0
    desc = str(description)
    for word, val in MULTIPLIERS.items():
        if re.search(rf"\b{word}\b", desc, re.I): return val
    if IGNORE_NUMBER_CONTEXT.search(desc): return 0
    m = RE_ARRAY.search(desc)
    if m:
        try: return int(m.group(1)) * int(m.group(2))
        except (ValueError, TypeError):
            _logger.debug(f"Could not parse array count from description: {desc[:50]}")
    if CONNECTOR_WORDS.search(desc):
        m = RE_PINCOUNT.search(desc)
        if m: return int(m.group(1))
    return 0

def explode_grouping(
    df: pd.DataFrame,
    ref_col: str,
    group_col: Optional[str],
    ignore_token_re: Optional[re.Pattern] = None,
    stop_event: Optional['threading.Event'] = None,
) -> Tuple[Set[str], Set[str], Dict[str, List[str]], Dict[str, str], Dict[str, str]]:
    """Parse grouping file and explode RefDes tokens."""
    # Input validation
    if df is None or df.empty:
        raise ValueError("Grouping DataFrame cannot be None or empty")
    if ref_col not in df.columns:
        raise ColumnMappingError(f"Required RefDes column '{ref_col}' not found in grouping file")
    if group_col and group_col not in df.columns:
        raise ColumnMappingError(f"Required group column '{group_col}' not found in grouping file")

    full_tokens: Set[str] = set()
    bases: Set[str] = set()
    base_to_tokens: Dict[str, List[str]] = {}
    token_to_group: Dict[str, str] = {}
    base_to_group: Dict[str, str] = {}

    # Create column index mapping for safe access with itertuples
    # (getattr fails silently for column names with spaces)
    col_idx = {col: i for i, col in enumerate(df.columns)}
    ref_idx = col_idx[ref_col]
    grp_idx = col_idx.get(group_col) if group_col else None

    # Use itertuples for 5-10x performance improvement over iterrows
    for row_idx, row in enumerate(df.itertuples(index=False)):
        # M2: Check cancellation every 50 rows for faster cancel response on large files
        if stop_event and row_idx % 50 == 0 and stop_event.is_set():
            raise CancellationError("Cancelled during grouping file parsing.")
        grp_val = row[grp_idx] if grp_idx is not None else None
        grp = str(grp_val).strip() if (group_col and pd.notna(grp_val)) else ""
        ref_val = row[ref_idx]
        # M1: Guard against NaN values before parsing
        if pd.isna(ref_val):
            ref_val = ""
        # Use centralized split_refdes_list for consistent parsing with edge case handling
        refs = split_refdes_list(ref_val)
        for ct in refs:
            if not ct or (ignore_token_re and ignore_token_re.search(ct)):
                continue
            base = base_of_token(ct)
            full_tokens.add(ct)
            bases.add(base)
            base_to_tokens.setdefault(base, []).append(ct)
            if grp:
                token_to_group[ct] = grp
                if base not in base_to_group:
                    base_to_group[base] = grp
    return full_tokens, bases, base_to_tokens, token_to_group, base_to_group

def explode_bom(
    df: pd.DataFrame,
    ref_col: str,
    desc_col: Optional[str],
    ignore_dnp: bool,
    dnp_re: re.Pattern,
    ignore_token_re: Optional[re.Pattern] = None,
    ignore_desc_re: Optional[re.Pattern] = None,
    stop_event: Optional['threading.Event'] = None,
) -> Tuple[Set[str], Set[str], Dict[str, str], Dict[str, List[str]]]:
    """Parse BOM file and explode RefDes tokens."""
    # Input validation
    if df is None or df.empty:
        raise ValueError("BOM DataFrame cannot be None or empty")
    if ref_col not in df.columns:
        raise ColumnMappingError(f"Required RefDes column '{ref_col}' not found in BOM file")
    if desc_col and desc_col not in df.columns:
        raise ColumnMappingError(f"Required description column '{desc_col}' not found in BOM file")

    full_tokens: Set[str] = set()
    bases: Set[str] = set()
    base_to_desc: Dict[str, str] = {}
    base_to_tokens: Dict[str, List[str]] = {}

    # Create column index mapping for safe access with itertuples
    # (getattr fails silently for column names with spaces)
    col_idx = {col: i for i, col in enumerate(df.columns)}
    ref_idx = col_idx[ref_col]
    desc_idx = col_idx.get(desc_col) if desc_col else None

    # Use itertuples for 5-10x performance improvement over iterrows
    for row_idx, row in enumerate(df.itertuples(index=False)):
        # M2: Check cancellation every 50 rows for faster cancel response on large files
        if stop_event and row_idx % 50 == 0 and stop_event.is_set():
            raise CancellationError("Cancelled during BOM file parsing.")
        ref_val = row[ref_idx]
        # M1: Guard against NaN values before parsing
        if pd.isna(ref_val):
            ref_val = ""
        desc_val = row[desc_idx] if (desc_idx is not None and pd.notna(row[desc_idx])) else ""
        if ignore_dnp:
            # C11: Normalize control characters before regex matching (PDFs may contain invisible chars)
            check_str = CONTROL_CHARS_PATTERN.sub("", str(ref_val) + " " + str(desc_val))
            if dnp_re.search(check_str):
                continue
        desc = str(desc_val).strip() if desc_col else ""
        if ignore_desc_re and desc and ignore_desc_re.search(desc):
            continue
        # Use centralized split_refdes_list for consistent parsing with edge case handling
        refs = split_refdes_list(ref_val)
        for ct in refs:
            if not ct or (ignore_token_re and ignore_token_re.search(ct)):
                continue
            base = base_of_token(ct)
            full_tokens.add(ct)
            bases.add(base)
            base_to_tokens.setdefault(base, []).append(ct)
            if desc and base not in base_to_desc:
                base_to_desc[base] = desc
    return full_tokens, bases, base_to_desc, base_to_tokens


# -----------------------------------------------------------------------------
# Analysis Helper Functions (refactored for testability)
# -----------------------------------------------------------------------------

def _compile_patterns(options: AnalyzeOptions) -> Tuple[re.Pattern, Optional[re.Pattern], Optional[re.Pattern]]:
    """Compile regex patterns from options. Returns (dnp_re, ignore_tok_re, ignore_desc_re)."""
    # Bug 1 (defense-in-depth): a falsy dnp_regex (empty string / None) is
    # NOT an error — re.compile('') succeeds and matches every string, which
    # would make explode_bom drop the entire BOM as DNP. Treat any falsy
    # value as "use the canonical default" BEFORE compiling, so the
    # match-everything pattern can never reach explode_bom regardless of how
    # AnalyzeOptions was constructed.
    dnp_source = options.dnp_regex or DEFAULT_DNP_REGEX
    try:
        dnp_re = re.compile(dnp_source, re.I)
    except re.error:
        _logger.warning(f"Invalid DNP regex pattern, using default: {options.dnp_regex}")
        try:
            dnp_re = re.compile(DEFAULT_DNP_REGEX, re.I)
        except re.error as e:
            # Fallback to guaranteed-safe pattern if constant is somehow malformed
            _logger.error(f"Invalid DEFAULT_DNP_REGEX constant: {e}")
            dnp_re = re.compile(r"\bDNP\b", re.I)

    # Protect against invalid user-provided regex patterns
    ignore_tok_re = None
    if options.ignore_refdes_pattern:
        try:
            ignore_tok_re = re.compile(options.ignore_refdes_pattern, re.I)
        except re.error:
            _logger.warning(f"Invalid ignore RefDes pattern, ignoring: {options.ignore_refdes_pattern}")

    ignore_desc_re = None
    if options.ignore_desc_pattern:
        try:
            ignore_desc_re = re.compile(options.ignore_desc_pattern, re.I)
        except re.error:
            _logger.warning(f"Invalid ignore description pattern, ignoring: {options.ignore_desc_pattern}")

    return dnp_re, ignore_tok_re, ignore_desc_re


def _find_missing_in_bom(
    g_full: Set[str], g_tok_grp: Dict, g_base_grp: Dict,
    b_full: Set[str], b_bases: Set[str],
    options: AnalyzeOptions, stop_event: Optional['threading.Event']
) -> pd.DataFrame:
    """Find items in grouping that are missing from BOM."""
    def is_base_covered(base: str) -> bool:
        if base in b_bases:
            return True
        if options.loose_base_match:
            for c in b_bases:
                if c.startswith(base) and not c[len(base):].isdigit():
                    return True
        return False

    missing_rows = []
    for tok in sorted(g_full):
        check_cancelled(stop_event, "Analysis cancelled by user.")
        if options.exact_match:
            if tok not in b_full:
                missing_rows.append({
                    "Group": g_tok_grp.get(tok, ""),
                    "Token": tok,
                    "Base": base_of_token(tok),
                    "Reason": "Exact token missing"
                })
        else:
            base = base_of_token(tok)
            if not is_base_covered(base):
                missing_rows.append({
                    "Group": g_tok_grp.get(tok, g_base_grp.get(base, "")),
                    "Token": tok,
                    "Base": base,
                    "Reason": "Base RefDes missing"
                })

    return pd.DataFrame(missing_rows, columns=["Group", "Token", "Base", "Reason"])


def _find_extra_in_bom(
    g_full: Set[str], g_bases: Set[str],
    b_full: Set[str], b_bases: Set[str], b_base_map: Dict,
    options: AnalyzeOptions, stop_event: Optional['threading.Event']
) -> pd.DataFrame:
    """Find items in BOM that are not in grouping."""
    extra_rows = []
    if options.exact_match:
        for tok in sorted(b_full):
            check_cancelled(stop_event, "Analysis cancelled by user.")
            if tok not in g_full:
                extra_rows.append({
                    "Base": base_of_token(tok),
                    "BOM_Tokens": tok,
                    "Reason": "Exact token missing in Grouping"
                })
    else:
        for base in sorted(b_bases):
            check_cancelled(stop_event, "Analysis cancelled by user.")
            if base not in g_bases and not (options.loose_base_match and any(base.startswith(gb) and not base[len(gb):].isdigit() for gb in g_bases)):
                extra_rows.append({
                    "Base": base,
                    "BOM_Tokens": ", ".join(sorted(set(b_base_map.get(base, [])))),
                    "Reason": "Not found in Grouping"
                })

    return pd.DataFrame(extra_rows, columns=["Base", "BOM_Tokens", "Reason"])


def _check_warnings(
    b_bases: Set[str], b_desc_map: Dict, b_base_map: Dict, g_base_map: Dict,
    options: AnalyzeOptions, stop_event: Optional['threading.Event']
) -> pd.DataFrame:
    """Generate warnings for potential issues (count mismatches, connector coverage)."""
    warn_rows = []
    if not options.run_warning_checks:
        return pd.DataFrame(warn_rows, columns=["Base", "Expected_Approx", "Observed_Grouped_Tokens", "Description"])

    for base in sorted(b_bases):
        check_cancelled(stop_event, "Analysis cancelled by user.")
        desc = b_desc_map.get(base, "")
        exp = infer_expected_count(desc)
        if exp > 0:
            obs = len(set(g_base_map.get(base, [])))
            if obs < exp:
                warn_rows.append({
                    "Base": base,
                    "Expected_Approx": exp,
                    "Observed_Grouped_Tokens": obs,
                    "Description": desc
                })
        if desc and CONNECTOR_WORDS.search(desc):
            bp = len(set(b_base_map.get(base, [])))
            gp = len(set(g_base_map.get(base, [])))
            if bp and gp and gp < bp * 0.5:
                warn_rows.append({
                    "Base": base,
                    "Expected_Approx": bp,
                    "Observed_Grouped_Tokens": gp,
                    "Description": f"Connector coverage low. {desc}"
                })

    return pd.DataFrame(warn_rows, columns=["Base", "Expected_Approx", "Observed_Grouped_Tokens", "Description"])


def _check_duplicates(
    group_df: pd.DataFrame, bom_df: pd.DataFrame, mapping: ColumnMapping,
    ignore_tok_re: Optional[re.Pattern], options: AnalyzeOptions,
    dnp_re: re.Pattern, stop_event: Optional['threading.Event']
) -> pd.DataFrame:
    """Detect duplicate RefDes entries in both grouping and BOM files.

    Checks:
    - Grouping file: RefDes appearing in multiple groups (inter-group duplicates)
    - BOM file: RefDes appearing multiple times (intra-file duplicates)

    Returns DataFrame with columns: Source, Token, Count, Description
    - Source: "Grouping" or "BOM" to indicate which file contains the duplicate
    """
    dup_rows = []
    if not options.run_duplicate_checks:
        return pd.DataFrame(dup_rows, columns=["Source", "Token", "Count", "Description"])

    # Check grouping file for duplicates (RefDes appearing in multiple groups)
    if mapping.grouping_refdes_col and mapping.grouping_group_col:
        # Create column index mapping for safe access with itertuples
        grp_col_idx = {col: i for i, col in enumerate(group_df.columns)}
        grp_grp_idx = grp_col_idx[mapping.grouping_group_col]
        grp_ref_idx = grp_col_idx[mapping.grouping_refdes_col]

        token_to_groups: Dict[str, List[str]] = {}
        for row in group_df.itertuples(index=False):
            check_cancelled(stop_event, "Analysis cancelled by user.")
            ref_val = row[grp_ref_idx]
            # Skip rows with empty/NaN RefDes to avoid false "NAN" duplicates
            if pd.isna(ref_val):
                continue
            # Handle NaN group names (Codex insight: empty groups → "nan" in descriptions)
            grp_raw = row[grp_grp_idx]
            grp = "" if pd.isna(grp_raw) else str(grp_raw).strip()
            # Use exact string match - no range expansion for duplicate detection
            for t in [t for t in TOKEN_SPLIT_REGEX.split(str(ref_val)) if t]:
                ct = canonicalize_token(t)
                if not ct or (ignore_tok_re and ignore_tok_re.search(ct)):
                    continue
                if ct not in token_to_groups:
                    token_to_groups[ct] = []
                token_to_groups[ct].append(grp)

        for tok, groups in token_to_groups.items():
            check_cancelled(stop_event, "Analysis cancelled by user.")
            if len(groups) > 1:
                desc = ", ".join(sorted(groups))
                dup_rows.append({
                    "Source": "Grouping",
                    "Token": tok,
                    "Count": len(groups),
                    "Description": desc
                })

    # Check BOM file for duplicates (same RefDes appearing multiple times)
    if mapping.bom_refdes_col:
        # Create column index mapping for safe access with itertuples
        bom_col_idx = {col: i for i, col in enumerate(bom_df.columns)}
        bom_ref_idx = bom_col_idx[mapping.bom_refdes_col]
        bom_desc_idx = bom_col_idx.get(mapping.bom_desc_col) if mapping.bom_desc_col else None

        bom_token_count: Dict[str, int] = {}
        for row in bom_df.itertuples(index=False):
            check_cancelled(stop_event, "Analysis cancelled by user.")
            ref_val = row[bom_ref_idx]
            # Skip rows with empty/NaN RefDes to avoid false "NAN" duplicates
            if pd.isna(ref_val):
                continue
            desc_val = row[bom_desc_idx] if bom_desc_idx is not None else ""

            # Apply DNP filter for consistency with main analysis
            if options.ignore_dnp:
                check_str = CONTROL_CHARS_PATTERN.sub("", str(ref_val) + " " + str(desc_val))
                if dnp_re.search(check_str):
                    continue

            # Use exact string match - no range expansion for duplicate detection
            for t in [t for t in TOKEN_SPLIT_REGEX.split(str(ref_val)) if t]:
                ct = canonicalize_token(t)
                if not ct or (ignore_tok_re and ignore_tok_re.search(ct)):
                    continue
                bom_token_count[ct] = bom_token_count.get(ct, 0) + 1

        # Report BOM duplicates
        for tok, count in bom_token_count.items():
            check_cancelled(stop_event, "Analysis cancelled by user.")
            if count > 1:
                dup_rows.append({
                    "Source": "BOM",
                    "Token": tok,
                    "Count": count,
                    "Description": f"Appears {count} times in BOM"
                })

    return pd.DataFrame(dup_rows, columns=["Source", "Token", "Count", "Description"])


def _check_fmr(
    group_df: pd.DataFrame, mapping: ColumnMapping,
    options: AnalyzeOptions, log_func, stop_event: Optional['threading.Event']
) -> pd.DataFrame:
    """Validate Failure Mode Ratios sum to 1.0."""
    fmr_rows = []
    if not options.check_fmr:
        return pd.DataFrame(fmr_rows, columns=["RefDes", "Sum", "Status"])

    log_func("Checking FMR Summing...")
    ratio_col = detect_column(group_df.columns, get_synonyms('ratio'))

    if not ratio_col:
        log_func("  [WARNING] Could not detect 'Ratio' column for FMR check.")
        fmr_rows.append({"RefDes": "GLOBAL", "Sum": 0, "Status": "Ratio column not found"})
        return pd.DataFrame(fmr_rows, columns=["RefDes", "Sum", "Status"])

    log_func(f"  Detected FMR column: {ratio_col}")
    ref_sums: Dict[str, float] = {}

    # Create column index mapping for safe access with itertuples
    col_idx = {col: i for i, col in enumerate(group_df.columns)}
    ref_idx = col_idx[mapping.grouping_refdes_col]
    ratio_idx = col_idx.get(ratio_col) if ratio_col else None

    # Track RefDes whose ratio cell was non-numeric / NaN. Such a cell must NOT
    # silently contribute: float(NaN) does not raise, so a NaN ratio would poison
    # the sum and make abs(total - 1.0) > tol always False (the inconsistent
    # component silently passes), and a text cell would silently count as 0.0.
    # We exclude invalid cells from the sum and FLAG the RefDes instead.
    ref_invalid: set = set()
    for row in group_df.itertuples(index=False):
        check_cancelled(stop_event, "Analysis cancelled by user.")
        ref_val = row[ref_idx]
        # Guard against NaN values to prevent "NAN" key pollution
        if pd.isna(ref_val):
            continue
        # Tier-4 pd-checkfmr-key: canonicalize the key (not a raw strip/upper) so
        # a PDF-pasted RefDes carrying invisible characters groups with its clean
        # twin instead of splitting the sum into a false-positive "FMR != 1.0".
        ref_raw = canonicalize_refdes(str(ref_val))
        if not ref_raw:
            continue
        raw_ratio = row[ratio_idx] if ratio_idx is not None else None
        # A blank / NaN ratio cell (e.g. a part-header or continuation row that
        # repeats the RefDes with no ratio) is SKIPPED — not summed and not
        # flagged. float(NaN) would poison the sum so abs(total-1.0)>tol always
        # passes; and flagging it would noise up a RefDes whose real rows already
        # sum to 1.0. A genuinely short sum is still caught below. A non-numeric
        # TEXT or non-finite cell IS a data error: exclude it AND flag the RefDes.
        if raw_ratio is None or pd.isna(raw_ratio):
            continue
        try:
            parsed = float(raw_ratio)
        except (ValueError, TypeError):
            ref_invalid.add(ref_raw)
            continue
        if not math.isfinite(parsed):
            ref_invalid.add(ref_raw)
            continue
        ref_sums[ref_raw] = ref_sums.get(ref_raw, 0.0) + parsed

    for ref, total in ref_sums.items():
        check_cancelled(stop_event, "Analysis cancelled by user.")
        if ref in ref_invalid:
            fmr_rows.append({"RefDes": ref, "Sum": total, "Status": "Non-numeric ratio cell (sum incomplete)"})
        elif abs(total - 1.0) > FMR_TOLERANCE:
            fmr_rows.append({"RefDes": ref, "Sum": total, "Status": "FMR != 1.0"})
    # RefDes whose ratio cells were ALL non-numeric never reached ref_sums.
    for ref in sorted(ref_invalid - set(ref_sums)):
        fmr_rows.append({"RefDes": ref, "Sum": float("nan"), "Status": "Non-numeric ratio cell"})

    return pd.DataFrame(fmr_rows, columns=["RefDes", "Sum", "Status"])


def _check_part_usage(
    bom_df: pd.DataFrame,
    refdes_col: str,
    log_func,
    options: AnalyzeOptions,
    stop_event: Optional['threading.Event'] = None,
    dnp_re: Optional[re.Pattern] = None,
    bom_desc_col: Optional[str] = None,
    source_name: Optional[str] = None,
) -> pd.DataFrame:
    """
    Validate part usage values in BOM file.

    For multi-instance components (e.g., U300-1, U300-2, U300-3), each instance
    should have usage = 1/count (e.g., 1/3). Single instances should have usage = 1.0.

    Args:
        bom_df: BOM DataFrame
        refdes_col: RefDes column name
        log_func: Logging callback
        options: Analysis options (check_part_usage flag, ignore_dnp flag)
        stop_event: Optional cancellation event
        dnp_re: Optional DNP regex pattern to filter out DNP rows
        bom_desc_col: Optional description column name for DNP filtering
        source_name: Optional source filename/path used for FMEA gating

    Returns:
        DataFrame with columns:
        Source, RefDes, Base, Usage, Expected, Count, ReasonCode, Reason
    """
    warning_columns = ["Source", "RefDes", "Base", "Usage", "Expected", "Count", "ReasonCode", "Reason"]

    if not options.check_part_usage:
        return pd.DataFrame(columns=warning_columns)

    # Detect Part Usage column (substring_match for headers like "Part Usage / Quantity")
    usage_col = detect_column(bom_df.columns, get_synonyms('part_usage'), substring_match=True)
    if not usage_col:
        log_func("Part Usage column not found - skipping usage validation")
        return pd.DataFrame(columns=warning_columns)

    # Try to detect FMR column for combined validation
    # Use fmr_strict to avoid false matches on generic "Percentage" columns
    fmr_col = detect_column(bom_df.columns, get_synonyms('fmr_strict'))

    log_func(f"Checking Part Usage (column: {usage_col}"
             f"{', FMR: ' + fmr_col if fmr_col else ''})...")

    # Collect all RefDes tokens, usage values, and FMR values
    refdes_list = []
    usage_list = []
    fmr_list = []
    parse_failures = []
    dnp_skipped = 0
    cb_rows_skipped = 0
    records = bom_df.to_dict('records')

    def _usage_tokens(value: Any) -> List[str]:
        tokens: List[str] = []
        for raw in split_refdes_list(value):
            canon = canonicalize_refdes(raw)
            if canon:
                tokens.append(canon)
        return tokens

    # FMEA rows include circuit-block aggregates with blank FMR/PU values.
    # Skip CB rows so they do not pollute per-component usage checks.
    row_type_by_excel_row: Dict[int, str] = {}
    is_fmea_scope = False
    if is_fmea_file(source_name or ""):
        try:
            class _StopToken:
                def check(self):
                    check_cancelled(stop_event, "Analysis cancelled by user.")

            cancel_token = _StopToken() if stop_event else None
            classifications, _, _ = classify_fmea_rows(bom_df, cancel_token=cancel_token)
            row_type_by_excel_row = {c.row_index: c.row_type for c in classifications}
            cb_rows = sum(1 for c in classifications if c.row_type == "circuit_block")
            pp_rows = sum(1 for c in classifications if c.row_type == "piece_part")
            is_fmea_scope = cb_rows > 0 or pp_rows > 0
            if is_fmea_scope:
                log_func(
                    f"Detected FMEA row scope for Part Usage validation: "
                    f"{cb_rows} circuit-block rows, {pp_rows} piece-part rows"
                )
        except CancellationError:
            # Tier-4 new-cancellation-1: CancellationError -> InterruptedError ->
            # OSError -> Exception, so it would be swallowed by the broad handler
            # below (the exact gotcha CLAUDE.md warns about). Re-raise so a cancel
            # during FMEA classification propagates immediately.
            raise
        except Exception as ex:
            log_func(f"Warning: could not classify FMEA row scope for part usage filtering: {ex}")

    for excel_row, row in enumerate(records, start=2):
        check_cancelled(stop_event, "Analysis cancelled by user.")
        if is_fmea_scope and row_type_by_excel_row.get(excel_row) == "circuit_block":
            cb_rows_skipped += 1
            continue

        ref_val = row.get(refdes_col)
        usage_val = row.get(usage_col, 1)
        fmr_val = row.get(fmr_col, None) if fmr_col else None

        if pd.isna(ref_val):
            continue

        # Apply DNP filter for consistency with other validation checks
        if options.ignore_dnp and dnp_re:
            desc_val = row.get(bom_desc_col, "") if bom_desc_col else ""
            check_str = CONTROL_CHARS_PATTERN.sub("", str(ref_val) + " " + str(desc_val))
            if dnp_re.search(check_str):
                dnp_skipped += 1
                continue

        # Parse usage to numeric
        numeric_usage, _ = parse_usage(usage_val)
        if numeric_usage is None:
            parse_failures.append((str(ref_val), str(usage_val)))
            numeric_usage = 1.0

        # Parse FMR to numeric
        numeric_fmr = None
        if fmr_val is not None and pd.notna(fmr_val):
            try:
                numeric_fmr = float(fmr_val)
            except (ValueError, TypeError):
                numeric_fmr = None

        # Split RefDes cell (may contain "U1, U2, U3")
        for token in _usage_tokens(ref_val):
            refdes_list.append(token)
            usage_list.append(numeric_usage)
            fmr_list.append(numeric_fmr)

    if dnp_skipped > 0:
        log_func(f"Skipped {dnp_skipped} DNP rows in part usage validation")
    if cb_rows_skipped > 0:
        log_func(f"Skipped {cb_rows_skipped} circuit-block row(s) in part usage validation")

    if not refdes_list:
        log_func("No RefDes tokens found for usage validation")
        return pd.DataFrame(columns=warning_columns)

    # Use combined FMR×PU check when FMR data is available,
    # otherwise fall back to corrected basic PU check
    if fmr_col:
        raw_warnings = validate_fmr_usage_product(
            refdes_list, usage_list, fmr_list, get_usage_base_refdes)
    else:
        raw_warnings = validate_part_usage(
            refdes_list, usage_list, get_usage_base_refdes)

    # Value format warnings (range + decimal precision)
    format_warnings = validate_usage_format(refdes_list, usage_list)

    # Add warnings for unparseable Part Usage values
    for ref, raw in parse_failures:
        format_warnings.append({
            'RefDes': ref, 'Base': '', 'Usage': raw,
            'Expected': '', 'Count': '',
            'ReasonCode': 'PU_PARSE_DEFAULTED',
            'Reason': f"Unparseable Part Usage value: '{raw}' (defaulted to 1.0)",
        })

    raw_warnings = raw_warnings + format_warnings

    # Add Source column for consistency with other validation tables
    warnings = []
    for w in raw_warnings:
        warnings.append({
            'Source': 'BOM',
            'RefDes': w['RefDes'],
            'Base': w.get('Base', ''),
            'Usage': w.get('Usage', ''),
            'Expected': w.get('Expected', ''),
            'Count': w.get('Count', ''),
            'ReasonCode': w.get('ReasonCode', ''),
            'Reason': w['Reason'],
        })

    if warnings:
        log_func(f"[WARNING] Found {len(warnings)} part usage mismatches")
    else:
        log_func("Part usage validation passed - all values match expected")

    return pd.DataFrame(warnings, columns=warning_columns)


# -----------------------------------------------------------------------------
# Main Analysis Routine
# -----------------------------------------------------------------------------
def analyze(group_df: pd.DataFrame, bom_df: pd.DataFrame, mapping: ColumnMapping, options: AnalyzeOptions, file_paths: Tuple[str, str], stop_event: Optional['threading.Event'] = None) -> AnalyzeResults:
    """
    Main analysis orchestrator - compares grouping file against BOM.

    This function coordinates the analysis by:
    1. Validating input columns
    2. Compiling regex patterns
    3. Parsing both files into token sets
    4. Delegating to specialized helper functions for each check type
    5. Generating summary results
    """
    log_buffer = []
    def log(msg):
        log_buffer.append(msg)
        _logger.info(msg)

    # Validate required columns
    ensure_columns_exist(group_df, [mapping.grouping_refdes_col, mapping.grouping_group_col], "Grouping file")
    bom_req = [mapping.bom_refdes_col]
    if mapping.bom_desc_col:
        bom_req.append(mapping.bom_desc_col)
    ensure_columns_exist(bom_df, bom_req, "BOM file")

    # Compile regex patterns
    dnp_re, ignore_tok_re, ignore_desc_re = _compile_patterns(options)

    # Parse input files
    log("Parsing Grouping file...")
    g_full, g_bases, g_base_map, g_tok_grp, g_base_grp = explode_grouping(
        group_df, mapping.grouping_refdes_col, mapping.grouping_group_col, ignore_tok_re,
        stop_event=stop_event
    )

    log("Parsing BOM file...")
    b_full, b_bases, b_desc_map, b_base_map = explode_bom(
        bom_df, mapping.bom_refdes_col, mapping.bom_desc_col,
        options.ignore_dnp, dnp_re, ignore_tok_re, ignore_desc_re,
        stop_event=stop_event
    )

    # Handle provisional items
    if not options.treat_prov_as_covered:
        prov = {t for t, g in g_tok_grp.items() if "PROV" in g.upper()}
        g_full -= prov
        g_bases = {base_of_token(t) for t in g_full}

    log("Comparing...")

    # Run analysis checks using helper functions
    df_missing = _find_missing_in_bom(
        g_full, g_tok_grp, g_base_grp, b_full, b_bases, options, stop_event
    )

    df_extra = _find_extra_in_bom(
        g_full, g_bases, b_full, b_bases, b_base_map, options, stop_event
    )

    df_warn = _check_warnings(
        b_bases, b_desc_map, b_base_map, g_base_map, options, stop_event
    )

    df_dup = _check_duplicates(
        group_df, bom_df, mapping, ignore_tok_re, options, dnp_re, stop_event
    )

    df_fmr = _check_fmr(
        group_df, mapping, options, log, stop_event
    )

    df_usage = _check_part_usage(
        bom_df, mapping.bom_refdes_col, log, options, stop_event,
        dnp_re=dnp_re,
        bom_desc_col=mapping.bom_desc_col,
        source_name=file_paths[1] if file_paths and len(file_paths) > 1 else None,
    )

    # Generate summary
    summary_data = [
        ("Run Timestamp", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ("Grouping File", os.path.basename(file_paths[0])),
        ("BOM File", os.path.basename(file_paths[1])),
        ("Missing in BOM", len(df_missing)),
        ("BOM Not in Groups", len(df_extra)),
        ("Warnings", len(df_warn)),
        ("Duplicates", len(df_dup)),
        ("Failure Mode Ratio Errors", len(df_fmr)),
        ("Part Usage Warnings", len(df_usage))
    ]
    df_sum = pd.DataFrame(summary_data, columns=["Item", "Value"])

    return AnalyzeResults(
        summary=df_sum,
        missing_in_bom=df_missing,
        bom_not_in_groups=df_extra,
        description_warnings=df_warn,
        duplicates=df_dup,
        fmr_warnings=df_fmr,
        part_usage_warnings=df_usage,
        log="\n".join(log_buffer)
    )

def write_excel_report(results: AnalyzeResults, output_path: str) -> None:
    """
    Writes the analysis results to an Excel file with modern styling.
    Uses shared styling utility for consistent formatting.
    """
    from openpyxl import Workbook

    wb = Workbook()

    def user_facing_frame(df: pd.DataFrame) -> pd.DataFrame:
        """Translate technical codes/messages for exported reports."""
        if df is None or df.empty:
            return df

        frame = df.copy()
        if "ReasonCode" in frame.columns and "Reason Code" not in frame.columns:
            frame = frame.rename(columns={"ReasonCode": "Reason Code"})

        if "Reason Code" in frame.columns:
            frame["Reason Code"] = frame["Reason Code"].apply(to_reason_code_label)

        for col in frame.columns:
            if col == "Reason Code":
                continue
            frame[col] = frame[col].apply(to_user_facing_text)

        return frame

    # Sheet configurations: (DataFrame, title, row_style)
    # row_style: 'warning' = orange, 'error' = red, 'info' = yellow, 'highlight' = blue, 'neutral' = grey
    sheets = [
        (results.summary, "Summary", None),
        (results.missing_in_bom, "Missing in BOM", "warning"),
        (results.bom_not_in_groups, "BOM Not Grouped", "error"),
        (results.description_warnings, "Warnings", "info"),
        (results.duplicates, "Duplicates", "highlight"),
        (results.fmr_warnings, "Failure Mode Ratio Errors", "neutral"),
        (results.part_usage_warnings, "Part Usage", "warning"),
    ]

    first_sheet = True
    for df, title, style_name in sheets:
        if df.empty and title != "Summary":
            continue

        export_df = user_facing_frame(df)

        if first_sheet:
            ws = wb.active
            ws.title = title
            first_sheet = False
        else:
            ws = wb.create_sheet(title)

        write_df_to_sheet(ws, export_df)

        if style_name:
            # Apply uniform row styling for issue sheets
            style_worksheet(
                ws, export_df,
                row_style_func=lambda r, i, s=style_name: s,
                max_width=60
            )
        else:
            # Summary sheet - no row coloring, just clean formatting
            style_worksheet(ws, export_df, max_width=60)

    wb.save(output_path)
