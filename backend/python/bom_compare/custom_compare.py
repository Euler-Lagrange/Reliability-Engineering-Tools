#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BOM Compare - Custom Compare Module

BOM-vs-BOM comparison engine: compare two BOMs using RefDes as key anchor,
with FMEA-aware scope analysis, duplicate detection, and part usage validation.
"""
import threading
from typing import Dict, List, Optional, Set, Tuple, Any

import pandas as pd

from common import (
    detect_column,
    get_tool_logger,
    check_cancelled,
    CancellationError,
    get_synonyms,
    parse_usage,
    to_reason_code_label,
    to_user_facing_text,
)
from common.exceptions import ColumnMappingError
from common.refdes_utils import (
    canonicalize_refdes,
    get_prefix,
    is_known_prefix,
    get_usage_base_refdes,
    split_refdes_list,
)
from common.validation_utils import (
    validate_part_usage,
    validate_usage_format,
    validate_fmr_usage_product,
)
from common.fmea_utils import (
    is_fmea_file,
    detect_refdes_column_for_fmea,
    classify_fmea_rows,
)
from common.column_synonyms import get_synonyms as _get_synonyms

from .bom_compare_logic import BomCompareResult

_logger = get_tool_logger("bom_compare")

# FMEA detection: Circuit Block / Function Block column synonyms
CIRCUIT_BLOCK_SYNONYMS = _get_synonyms('circuit_block')
FAILURE_MODE_SYNONYMS = _get_synonyms('failure_mode')
FMEA_ID_SYNONYMS = [
    'FMEA ID', 'FMEA_ID', 'FMEAID',
    'FMECA ID', 'FM ID', 'Failure Mode ID', 'Mode ID',
]

def detect_circuit_block_column(df: pd.DataFrame) -> Optional[str]:
    """Detect if DataFrame has a Circuit Block / Function Block column.

    FMEA files have two row types:
    - Circuit Block rows: One RefDes per component (U200, J1-1) - duplicates are real errors
    - Piecepart rows: RefDes repeated per failure mode - duplicates are expected

    This function detects the Circuit Block column so we can filter duplicate
    detection to only circuit block rows.

    Args:
        df: DataFrame to check for Circuit Block column

    Returns:
        Column name if found, None otherwise
    """
    for col in df.columns:
        col_lower = str(col).lower().strip()
        if any(syn in col_lower for syn in CIRCUIT_BLOCK_SYNONYMS):
            return col
    return None


def compare_two_boms(
    bom_a_df: pd.DataFrame,
    bom_b_df: pd.DataFrame,
    refdes_col_a: str,
    refdes_col_b: str,
    compare_columns: Optional[List[Tuple]] = None,
    key_mode: str = "refdes_list",
    log_callback: Optional[callable] = None,
    stop_event: Optional['threading.Event'] = None,
    check_part_usage: bool = True,
    source_name_a: Optional[str] = None,
    source_name_b: Optional[str] = None,
) -> BomCompareResult:
    """
    Compare two BOMs using RefDes as the key anchor.

    Uses FULL EXACT MATCH - RefDes must match exactly (e.g., U312-B17 only matches U312-B17).

    Args:
        bom_a_df: First BOM DataFrame (reference)
        bom_b_df: Second BOM DataFrame (comparison)
        refdes_col_a: RefDes column name in BOM A
        refdes_col_b: RefDes column name in BOM B
        compare_columns: Optional list of (col_a, col_b) tuples for additional comparison
        log_callback: Optional callback for logging progress
        stop_event: Optional threading.Event for cancellation support
        source_name_a: Optional source filename/path for BOM A (used for FMEA gating)
        source_name_b: Optional source filename/path for BOM B (used for FMEA gating)

    Returns:
        BomCompareResult with only_in_a, only_in_b, differences, and summary
    """
    def log(msg: str):
        if log_callback:
            log_callback(msg)
        _logger.info(msg)

    result = BomCompareResult()

    # Validate inputs
    if bom_a_df is None or bom_a_df.empty:
        raise ValueError("BOM A DataFrame cannot be None or empty")
    if bom_b_df is None or bom_b_df.empty:
        raise ValueError("BOM B DataFrame cannot be None or empty")
    if refdes_col_a not in bom_a_df.columns:
        raise ColumnMappingError(f"RefDes column '{refdes_col_a}' not found in BOM A")
    if refdes_col_b not in bom_b_df.columns:
        raise ColumnMappingError(f"RefDes column '{refdes_col_b}' not found in BOM B")

    log(f"Comparing BOM A ({len(bom_a_df)} rows) vs BOM B ({len(bom_b_df)} rows)")

    key_mode_norm = (key_mode or "refdes_list").strip().lower()
    if key_mode_norm not in {"refdes_list", "exact"}:
        raise ValueError(f"Unsupported key_mode: {key_mode}. Expected 'refdes_list' or 'exact'.")

    def extract_keys(value: Any) -> List[str]:
        """Extract comparison keys from a cell value based on key_mode.

        Modes:
        - "exact": Treat each cell as a single key (no range expansion).
          NOTE: Still normalizes whitespace and uppercases for consistent matching.
          Use this for non-RefDes keys or when you want "U1-U3" as a single value.
        - "refdes_list": Split and expand RefDes ranges (e.g., "U1-U3" -> ["U1", "U2", "U3"]).
        """
        # Handle NaN/None safely
        if value is None or (hasattr(pd, "isna") and pd.isna(value)):
            return []
        if key_mode_norm == "exact":
            # Exact mode: single key, but normalized for reliable matching
            s = str(value).strip()
            return [s.upper()] if s else []
        return split_refdes_list(value)

    def normalize_text(value: Any) -> str:
        if value is None or (hasattr(pd, "isna") and pd.isna(value)):
            return ""
        return str(value).strip()

    def values_differ(a_val: Any, b_val: Any, rule: str) -> bool:
        rule_norm = (rule or "Text (ignore case)").strip().lower()
        a_txt = normalize_text(a_val)
        b_txt = normalize_text(b_val)
        if rule_norm.startswith("numeric"):
            try:
                a_num = float(a_txt)
                b_num = float(b_txt)
                return abs(a_num - b_num) > 1e-9
            except (ValueError, TypeError):
                # Fallback to text compare if either value isn't numeric
                return a_txt.upper() != b_txt.upper()
        if "exact" in rule_norm:
            return a_txt != b_txt
        # Default: case-insensitive text compare
        return a_txt.upper() != b_txt.upper()

    def parse_compare_columns(raw: Optional[List[Tuple]]) -> List[Tuple[str, str, str]]:
        pairs: List[Tuple[str, str, str]] = []
        if not raw:
            return pairs
        for item in raw:
            if not isinstance(item, tuple):
                raise TypeError("compare_columns entries must be tuples")
            if len(item) == 2:
                col_a, col_b = item
                rule = "Text (ignore case)"
            elif len(item) == 3:
                col_a, col_b, rule = item
            else:
                raise ValueError("compare_columns entries must be (col_a, col_b) or (col_a, col_b, rule)")
            pairs.append((str(col_a), str(col_b), str(rule)))
        return pairs

    compare_pairs = parse_compare_columns(compare_columns)

    # FMEA detection combines filename signal + row-scan classification.
    filename_fmea_a = is_fmea_file(source_name_a or "")
    filename_fmea_b = is_fmea_file(source_name_b or "")

    # Detect Circuit Block columns as an additional hint for logging.
    cb_col_a = detect_circuit_block_column(bom_a_df)
    cb_col_b = detect_circuit_block_column(bom_b_df)

    if filename_fmea_a:
        log(f"  File 1 filename matches FMEA pattern: {source_name_a}")
    if filename_fmea_b:
        log(f"  File 2 filename matches FMEA pattern: {source_name_b}")
    if cb_col_a:
        log(f"  FMEA hint in BOM A: detected '{cb_col_a}'")
    if cb_col_b:
        log(f"  FMEA hint in BOM B: detected '{cb_col_b}'")

    def _extract_scope_tokens(value: Any) -> List[str]:
        """Extract only RefDes-like tokens for scope analysis."""
        tokens: List[str] = []
        for raw in split_refdes_list(value):
            canon = canonicalize_refdes(raw)
            if not canon:
                continue
            prefix = get_prefix(canon)
            if prefix and is_known_prefix(prefix):
                tokens.append(canon)
        return tokens

    def _extract_usage_tokens(value: Any) -> List[str]:
        """Extract canonical tokens for part-usage validation (no prefix gating)."""
        tokens: List[str] = []
        for raw in split_refdes_list(value):
            canon = canonicalize_refdes(raw)
            if canon:
                tokens.append(canon)
        return tokens

    def _build_scope_sets(
        df: pd.DataFrame,
        ref_col: str,
        source_label: str,
        enable_row_scope_scan: bool,
    ) -> Dict[str, Any]:
        """Build per-file token sets for all rows, circuit-block rows, and piece-part rows."""
        scope = {
            "all": set(),
            "circuit_block": set(),
            "piece_part": set(),
            "is_fmea": False,
            "cb_rows": 0,
            "pp_rows": 0,
            "row_type_by_excel_row": {},
            "scope_ref_col": "",
        }

        row_type_by_excel_row: Dict[int, str] = {}
        detected_scope_col: Optional[str] = None
        if enable_row_scope_scan:
            class _StopToken:
                def check(self):
                    check_cancelled(stop_event, f"Cancelled during scope classification ({source_label})")

            cancel_token = _StopToken() if stop_event else None
            classifications, _, _ = classify_fmea_rows(df, cancel_token=cancel_token)
            row_type_by_excel_row = {c.row_index: c.row_type for c in classifications}
            scope["row_type_by_excel_row"] = row_type_by_excel_row
            scope["cb_rows"] = sum(1 for c in classifications if c.row_type == "circuit_block")
            scope["pp_rows"] = sum(1 for c in classifications if c.row_type == "piece_part")
            scope["is_fmea"] = scope["cb_rows"] > 0 or scope["pp_rows"] > 0
            detected_scope_col = detect_refdes_column_for_fmea(df)

        # Candidate scope columns:
        # 1) selected compare key column
        # 2) auto-detected FMEA RefDes column (if available)
        candidate_cols: List[str] = []
        if ref_col in df.columns:
            candidate_cols.append(ref_col)
        if detected_scope_col and detected_scope_col in df.columns and detected_scope_col not in candidate_cols:
            candidate_cols.append(detected_scope_col)
        if not candidate_cols:
            log(
                f"  {source_label} scope analysis skipped: no valid RefDes candidate column "
                f"(selected='{ref_col}', detected='{detected_scope_col or ''}')"
            )
            return scope

        def score_scope_column(col_name: str) -> Tuple[int, int, int]:
            cb_tokens: Set[str] = set()
            pp_tokens: Set[str] = set()
            all_tokens: Set[str] = set()
            for excel_row, row in enumerate(df.to_dict('records'), start=2):
                row_type = row_type_by_excel_row.get(excel_row, "other")
                if row_type not in {"circuit_block", "piece_part"}:
                    continue
                tokens = _extract_scope_tokens(row.get(col_name, ""))
                all_tokens.update(tokens)
                if row_type == "circuit_block":
                    cb_tokens.update(tokens)
                else:
                    pp_tokens.update(tokens)
            # Prefer columns where the same RefDes tokens appear in both scopes.
            overlap = len(cb_tokens & pp_tokens)
            both_non_empty = 1 if cb_tokens and pp_tokens else 0
            return (overlap, both_non_empty, len(all_tokens))

        scope_ref_col = candidate_cols[0]
        best_score = score_scope_column(scope_ref_col)
        for candidate in candidate_cols[1:]:
            candidate_score = score_scope_column(candidate)
            if candidate_score > best_score:
                scope_ref_col = candidate
                best_score = candidate_score

        scope["scope_ref_col"] = scope_ref_col
        if scope_ref_col != ref_col:
            log(
                f"  {source_label} scope analysis using detected RefDes column "
                f"'{scope_ref_col}' instead of selected key column '{ref_col}'"
            )
        elif detected_scope_col and detected_scope_col != ref_col:
            log(
                f"  {source_label} scope analysis retained selected key column "
                f"'{ref_col}' over detected '{detected_scope_col}'"
            )

        for excel_row, row in enumerate(df.to_dict('records'), start=2):
            # Scope analysis is RefDes-token based regardless of key_mode.
            keys = _extract_scope_tokens(row.get(scope_ref_col, ""))
            row_type = row_type_by_excel_row.get(excel_row, "other")
            for key in keys:
                if not key or not key.strip():
                    continue
                scope["all"].add(key)
                if row_type == "circuit_block":
                    scope["circuit_block"].add(key)
                elif row_type == "piece_part":
                    scope["piece_part"].add(key)
        return scope

    # Build row-scope token sets first so duplicate detection can use row type.
    check_cancelled(stop_event, "Cancelled before building row-scope token sets")
    scope_a = _build_scope_sets(
        bom_a_df,
        refdes_col_a,
        "File 1",
        enable_row_scope_scan=filename_fmea_a,
    )
    scope_b = _build_scope_sets(
        bom_b_df,
        refdes_col_b,
        "File 2",
        enable_row_scope_scan=filename_fmea_b,
    )
    if scope_a["is_fmea"]:
        log(
            f"  File 1 row-scope profile: {scope_a['cb_rows']} circuit-block rows, "
            f"{scope_a['pp_rows']} piece-part rows"
        )
    elif filename_fmea_a:
        log("  File 1 matched FMEA filename, but no circuit-block/piece-part rows were classified")
    if scope_b["is_fmea"]:
        log(
            f"  File 2 row-scope profile: {scope_b['cb_rows']} circuit-block rows, "
            f"{scope_b['pp_rows']} piece-part rows"
        )
    elif filename_fmea_b:
        log("  File 2 matched FMEA filename, but no circuit-block/piece-part rows were classified")

    def normalize_key_text(value: Any) -> str:
        return normalize_text(value).upper()

    def detect_fmea_context_columns(df: pd.DataFrame) -> Tuple[Optional[str], Optional[str]]:
        """Detect optional FMEA context columns used for true duplicate identity."""
        failure_mode_col = detect_column(list(df.columns), FAILURE_MODE_SYNONYMS)
        fmea_id_col = detect_column(list(df.columns), FMEA_ID_SYNONYMS, substring_match=True)
        return failure_mode_col, fmea_id_col

    fm_col_a, fmea_id_col_a = detect_fmea_context_columns(bom_a_df)
    fm_col_b, fmea_id_col_b = detect_fmea_context_columns(bom_b_df)
    if scope_a["is_fmea"]:
        log(f"  File 1 duplicate context: Failure Mode={fm_col_a or 'N/A'}, FMEA ID={fmea_id_col_a or 'N/A'}")
    if scope_b["is_fmea"]:
        log(f"  File 2 duplicate context: Failure Mode={fm_col_b or 'N/A'}, FMEA ID={fmea_id_col_b or 'N/A'}")

    def build_duplicate_identity(
        row: Dict[str, Any],
        token: str,
        row_type: str,
        is_fmea: bool,
        failure_mode_col: Optional[str],
        fmea_id_col: Optional[str],
    ) -> Tuple[Optional[Tuple[Any, ...]], Optional[Dict[str, Any]]]:
        """Build duplicate identity key + metadata for one token occurrence."""
        if not is_fmea:
            return (
                ("refdes", token),
                {
                    "RefDes": token,
                    "RowScope": "all",
                    "DuplicateRule": "RefDes",
                    "Failure Mode": "",
                    "FMEA ID": "",
                },
            )

        if row_type == "circuit_block":
            return (
                ("circuit_block", token),
                {
                    "RefDes": token,
                    "RowScope": "circuit_block",
                    "DuplicateRule": "RefDes (Circuit Block row)",
                    "Failure Mode": "",
                    "FMEA ID": "",
                },
            )

        if row_type == "piece_part":
            fm_val = normalize_text(row.get(failure_mode_col, "")) if failure_mode_col else ""
            fmea_id_val = normalize_text(row.get(fmea_id_col, "")) if fmea_id_col else ""
            fm_key = normalize_key_text(fm_val)
            fmea_id_key = normalize_key_text(fmea_id_val)

            if fmea_id_key and fm_key:
                return (
                    ("piece_part", token, fmea_id_key, fm_key),
                    {
                        "RefDes": token,
                        "RowScope": "piece_part",
                        "DuplicateRule": "RefDes + FMEA ID + Failure Mode",
                        "Failure Mode": fm_val,
                        "FMEA ID": fmea_id_val,
                    },
                )
            if fmea_id_key:
                return (
                    ("piece_part", token, fmea_id_key),
                    {
                        "RefDes": token,
                        "RowScope": "piece_part",
                        "DuplicateRule": "RefDes + FMEA ID",
                        "Failure Mode": "",
                        "FMEA ID": fmea_id_val,
                    },
                )
            if fm_key:
                return (
                    ("piece_part", token, fm_key),
                    {
                        "RefDes": token,
                        "RowScope": "piece_part",
                        "DuplicateRule": "RefDes + Failure Mode",
                        "Failure Mode": fm_val,
                        "FMEA ID": "",
                    },
                )
            # No discriminators available on piece-part rows: skip to avoid false positives.
            return None, None

        # Other FMEA row types are ignored for duplicate checks.
        return None, None

    # Build RefDes indexes + duplicate identity maps
    check_cancelled(stop_event, "Cancelled before indexing BOM A")
    index_a: Dict[str, Dict[str, Any]] = {}
    all_occurrences_a: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
    duplicate_meta_a: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for excel_row, row in enumerate(bom_a_df.to_dict('records'), start=2):
        ref_val = row.get(refdes_col_a, "")
        keys = extract_keys(ref_val)
        row_type = scope_a["row_type_by_excel_row"].get(excel_row, "other")
        for key in keys:
            if not key or not key.strip():
                continue
            if key not in index_a:
                index_a[key] = row
            dup_key, dup_meta = build_duplicate_identity(
                row, key, row_type, scope_a["is_fmea"], fm_col_a, fmea_id_col_a
            )
            if dup_key is not None:
                all_occurrences_a.setdefault(dup_key, []).append(row)
                duplicate_meta_a.setdefault(dup_key, dup_meta or {})

    check_cancelled(stop_event, "Cancelled before indexing BOM B")
    index_b: Dict[str, Dict[str, Any]] = {}
    all_occurrences_b: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
    duplicate_meta_b: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for excel_row, row in enumerate(bom_b_df.to_dict('records'), start=2):
        ref_val = row.get(refdes_col_b, "")
        keys = extract_keys(ref_val)
        row_type = scope_b["row_type_by_excel_row"].get(excel_row, "other")
        for key in keys:
            if not key or not key.strip():
                continue
            if key not in index_b:
                index_b[key] = row
            dup_key, dup_meta = build_duplicate_identity(
                row, key, row_type, scope_b["is_fmea"], fm_col_b, fmea_id_col_b
            )
            if dup_key is not None:
                all_occurrences_b.setdefault(dup_key, []).append(row)
                duplicate_meta_b.setdefault(dup_key, dup_meta or {})

    # Count duplicate identities (not just repeated RefDes in piece-part rows).
    dup_count_a = sum(1 for refs in all_occurrences_a.values() if len(refs) > 1)
    dup_count_b = sum(1 for refs in all_occurrences_b.values() if len(refs) > 1)
    if dup_count_a:
        log(f"[WARNING] Found {dup_count_a} duplicate identities in BOM A")
    if dup_count_b:
        log(f"[WARNING] Found {dup_count_b} duplicate identities in BOM B")

    log(f"BOM A: {len(index_a)} unique RefDes, BOM B: {len(index_b)} unique RefDes")

    # Find set differences (FULL EXACT MATCH)
    set_a = set(index_a.keys())
    set_b = set(index_b.keys())

    only_in_a = sorted(set_a - set_b)
    only_in_b = sorted(set_b - set_a)
    in_both = sorted(set_a & set_b)

    log(f"Only in A: {len(only_in_a)}, Only in B: {len(only_in_b)}, In both: {len(in_both)}")

    # Populate only_in_a results
    for refdes in only_in_a:
        row_data = index_a[refdes]
        result.only_in_a.append({
            'RefDes': refdes,
            **{k: v for k, v in row_data.items() if k != refdes_col_a}
        })

    # Populate only_in_b results
    for refdes in only_in_b:
        row_data = index_b[refdes]
        result.only_in_b.append({
            'RefDes': refdes,
            **{k: v for k, v in row_data.items() if k != refdes_col_b}
        })

    result.in_both_count = len(in_both)

    # Scope warnings: for FMEA-like files, tokens should appear in BOTH row scopes
    # (Circuit Block and Piece-Part). Tokens present in only one scope are flagged.
    scope_warnings: List[Dict[str, Any]] = []

    def add_scope_warnings(
        source: str,
        own_scope: Dict[str, Any],
        other_scope: Dict[str, Any],
    ) -> None:
        if not own_scope["is_fmea"]:
            return
        scope_col = own_scope.get("scope_ref_col", "")
        for token in sorted(own_scope["all"]):
            in_cb = token in own_scope["circuit_block"]
            in_pp = token in own_scope["piece_part"]
            if in_cb and in_pp:
                continue
            if in_cb and not in_pp:
                reason_code = "SCOPE_CB_ONLY"
                status = "Only found in Circuit Block rows"
                details = "Token is present in circuit block rows but missing from piece-part rows."
            elif in_pp and not in_cb:
                reason_code = "SCOPE_PP_ONLY"
                status = "Only found in Piece-Part rows"
                details = "Token is present in piece-part rows but missing from circuit block rows."
            else:
                reason_code = "SCOPE_UNCLASSIFIED_ONLY"
                status = "Found outside Circuit Block/Piece-Part rows"
                details = "Token is present only on rows that are not classified as circuit block or piece-part."

            if scope_col:
                details = f"{details} Scope column: {scope_col}."
            cross_file = "Present in both files" if token in other_scope["all"] else f"Only in {source}"
            scope_warnings.append({
                "Source": source,
                "RefDes": token,
                "ReasonCode": reason_code,
                "Scope Status": status,
                "Cross-File": cross_file,
                "Details": details,
                "InCircuitBlock": "Yes" if in_cb else "No",
                "InPiecePart": "Yes" if in_pp else "No",
                "ScopeColumn": scope_col,
            })

    add_scope_warnings("BOM A", scope_a, scope_b)
    add_scope_warnings("BOM B", scope_b, scope_a)
    result.scope_warnings = scope_warnings
    if scope_warnings:
        log(f"[WARNING] Found {len(scope_warnings)} circuit-block vs piece-part scope warnings")

    # Check for differences in additional columns
    if compare_pairs:
        check_cancelled(stop_event, "Cancelled before comparing columns")
        log(f"Comparing {len(compare_pairs)} additional column(s)")
        for refdes in in_both:
            row_a = index_a[refdes]
            row_b = index_b[refdes]
            for col_a, col_b, rule in compare_pairs:
                val_a = row_a.get(col_a, "")
                val_b = row_b.get(col_b, "")
                if values_differ(val_a, val_b, rule):
                    a_txt = normalize_text(val_a)
                    b_txt = normalize_text(val_b)
                    col_label = col_a if col_a == col_b else f"{col_a} ↔ {col_b}"
                    result.differences.append({
                        'RefDes': refdes,
                        'Column': col_label,
                        'Value_A': a_txt,
                        'Value_B': b_txt,
                        'Rule': rule,
                    })

        if result.differences:
            log(f"Found {len(result.differences)} differences in compared columns")

    # Build enhanced duplicate lists with category and full row data.
    # Duplicate identity is RefDes-only for normal BOMs, and scope-aware
    # composite keys for FMEA-like piece-part rows.
    duplicates_a: List[Dict[str, Any]] = []
    for dup_key, occurrences in all_occurrences_a.items():
        if len(occurrences) > 1:
            meta = duplicate_meta_a.get(dup_key, {})
            refdes = meta.get('RefDes', '')
            if refdes in in_both:
                category = 'in_both'
            elif refdes in only_in_a:
                category = 'only_in_A'
            else:
                category = 'unknown'  # Should not happen

            for idx, row in enumerate(occurrences):
                duplicates_a.append({
                    'RefDes': refdes,
                    'Source': 'BOM A',
                    'OccurrenceNum': idx + 1,
                    'Category': category,
                    'UsedForComparison': 'Yes' if idx == 0 else 'No',
                    'RowScope': meta.get('RowScope', ''),
                    'DuplicateRule': meta.get('DuplicateRule', 'RefDes'),
                    'FMEA ID': meta.get('FMEA ID', ''),
                    'Failure Mode': meta.get('Failure Mode', ''),
                    'RowData': row,  # Full row data
                })

    duplicates_b: List[Dict[str, Any]] = []
    for dup_key, occurrences in all_occurrences_b.items():
        if len(occurrences) > 1:
            meta = duplicate_meta_b.get(dup_key, {})
            refdes = meta.get('RefDes', '')
            if refdes in in_both:
                category = 'in_both'
            elif refdes in only_in_b:
                category = 'only_in_B'
            else:
                category = 'unknown'  # Should not happen

            for idx, row in enumerate(occurrences):
                duplicates_b.append({
                    'RefDes': refdes,
                    'Source': 'BOM B',
                    'OccurrenceNum': idx + 1,
                    'Category': category,
                    'UsedForComparison': 'Yes' if idx == 0 else 'No',
                    'RowScope': meta.get('RowScope', ''),
                    'DuplicateRule': meta.get('DuplicateRule', 'RefDes'),
                    'FMEA ID': meta.get('FMEA ID', ''),
                    'Failure Mode': meta.get('Failure Mode', ''),
                    'RowData': row,  # Full row data
                })

    # Add duplicates to result
    result.duplicates_a = duplicates_a
    result.duplicates_b = duplicates_b

    # Part usage validation for both files (if enabled)
    usage_warnings = []
    if check_part_usage:
        def check_usage_for_df(df, refdes_col, source_label, scope_meta):
            """Check part usage (and FMR×PU product when FMR is available)."""
            # substring_match=True to match group_analysis: catches compound
            # headers like "Part Usage / Quantity". Was inconsistent with group
            # mode, which detected usage columns the custom path silently missed.
            usage_col = detect_column(df.columns, get_synonyms('part_usage'), substring_match=True)
            if not usage_col:
                return []

            # Try to detect FMR column for combined validation
            # Use fmr_strict to avoid false matches on generic "Percentage" columns
            fmr_col = detect_column(df.columns, get_synonyms('fmr_strict'))

            log(f"Checking Part Usage in {source_label} (column: {usage_col}"
                f"{', FMR: ' + fmr_col if fmr_col else ''})...")
            refdes_list = []
            usage_list = []
            fmr_list = []
            parse_failures = []
            skipped_cb_rows = 0
            used_rows = 0
            # Reuse row classifications from scope build (no in-place heuristic mutation).
            row_type_map = scope_meta.get("row_type_by_excel_row", {}) if scope_meta else {}
            is_fmea_scope = bool(scope_meta and scope_meta.get("is_fmea"))

            for excel_row, row in enumerate(df.to_dict('records'), start=2):
                check_cancelled(stop_event, "Cancelled during part usage check")
                if is_fmea_scope and row_type_map.get(excel_row) == "circuit_block":
                    skipped_cb_rows += 1
                    continue

                ref_val = row.get(refdes_col)
                usage_val = row.get(usage_col, 1)
                fmr_val = row.get(fmr_col, None) if fmr_col else None
                if pd.isna(ref_val):
                    continue
                used_rows += 1
                numeric_usage, _ = parse_usage(usage_val)
                if numeric_usage is None:
                    parse_failures.append((str(ref_val), str(usage_val)))
                    numeric_usage = 1.0
                numeric_fmr = None
                if fmr_val is not None and pd.notna(fmr_val):
                    try:
                        numeric_fmr = float(fmr_val)
                    except (ValueError, TypeError):
                        numeric_fmr = None
                for token in _extract_usage_tokens(ref_val):
                    refdes_list.append(token)
                    usage_list.append(numeric_usage)
                    fmr_list.append(numeric_fmr)

            if is_fmea_scope and skipped_cb_rows:
                log(
                    f"  {source_label}: skipped {skipped_cb_rows} circuit-block row(s) "
                    f"for Part Usage/FMR validation; validated {used_rows} row(s)"
                )

            if not refdes_list:
                return []

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

            all_warnings = raw_warnings + format_warnings
            return [
                {
                    'Source': source_label,
                    'RefDes': w['RefDes'],
                    'Base': w.get('Base', ''),
                    'Usage': w.get('Usage', ''),
                    'Expected': w.get('Expected', ''),
                    'Count': w.get('Count', ''),
                    'ReasonCode': w.get('ReasonCode', ''),
                    'Reason': w['Reason'],
                }
                for w in all_warnings
            ]

        usage_warnings.extend(check_usage_for_df(bom_a_df, refdes_col_a, 'File 1', scope_a))
        usage_warnings.extend(check_usage_for_df(bom_b_df, refdes_col_b, 'File 2', scope_b))

        if usage_warnings:
            log(f"[WARNING] Found {len(usage_warnings)} part usage mismatches")

    result.part_usage_warnings = usage_warnings

    # Build summary
    # Count unique RefDes that have duplicates (for clearer reporting)
    unique_dup_refdes_a = len({
        duplicate_meta_a.get(k, {}).get("RefDes")
        for k, rows in all_occurrences_a.items()
        if len(rows) > 1 and duplicate_meta_a.get(k, {}).get("RefDes")
    })
    unique_dup_refdes_b = len({
        duplicate_meta_b.get(k, {}).get("RefDes")
        for k, rows in all_occurrences_b.items()
        if len(rows) > 1 and duplicate_meta_b.get(k, {}).get("RefDes")
    })
    scope_warnings_a = sum(1 for w in scope_warnings if w.get("Source") == "BOM A")
    scope_warnings_b = sum(1 for w in scope_warnings if w.get("Source") == "BOM B")
    result.summary = {
        'bom_a_rows': len(bom_a_df),
        'bom_b_rows': len(bom_b_df),
        'bom_a_unique_refdes': len(index_a),
        'bom_b_unique_refdes': len(index_b),
        'only_in_a': len(only_in_a),
        'only_in_b': len(only_in_b),
        'in_both': len(in_both),
        'differences': len(result.differences),
        'duplicates_a': unique_dup_refdes_a,  # Count of unique RefDes with duplicates
        'duplicates_b': unique_dup_refdes_b,
        'duplicate_rows_a': len(duplicates_a),  # Total duplicate occurrence rows
        'duplicate_rows_b': len(duplicates_b),
        'part_usage_warnings': len(usage_warnings),  # Part usage validation warnings
        'scope_warnings_a': scope_warnings_a,
        'scope_warnings_b': scope_warnings_b,
        'scope_warnings_total': len(scope_warnings),
    }

    return result


