#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Validation Utilities

This module provides shared validation functions used across reliability
engineering tools, including FMR (Failure Mode Ratio) validation and
duplicate detection.

Usage:
    from common.validation_utils import validate_fmr_sums, find_duplicates, FMR_TOLERANCE

    # Validate FMR sums
    results = validate_fmr_sums({'U1': 1.0, 'U2': 0.8})

    # Find duplicates in a list
    dupes = find_duplicates(['R1', 'R2', 'R1', 'R3'])
"""
import re
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Tuple, Any

from .utils import clean_string

# =============================================================================
# CONSTANTS
# =============================================================================

# Tolerance for FMR (Failure Mode Ratio) sum comparison
# FMR should sum to 1.0 per RefDes; this epsilon handles float precision issues
FMR_TOLERANCE = 0.001

# Tolerance for Part Usage validation
# More lenient than FMR (1% vs 0.1%) because usage values in real data
# often have small rounding differences (e.g., 0.333 vs 0.3333)
USAGE_TOLERANCE = 0.01


# =============================================================================
# FMR VALIDATION
# =============================================================================

def validate_fmr_sums(
    refdes_ratio_sums: Dict[str, float],
    tolerance: float = FMR_TOLERANCE
) -> List[Tuple[str, float, bool]]:
    """
    Validate that Failure Mode Ratios sum to 1.0 for each RefDes.

    In reliability engineering, the failure mode ratios for a component
    should sum to exactly 1.0 (100%). This function checks each RefDes
    and returns validation results.

    Args:
        refdes_ratio_sums: Dictionary mapping RefDes to summed ratio values
        tolerance: Acceptable deviation from 1.0 (default: 0.001)

    Returns:
        List of tuples: (refdes, sum_value, is_valid)

    Example:
        >>> validate_fmr_sums({'U1': 1.0, 'U2': 0.95, 'R1': 1.001})
        [('U1', 1.0, True), ('U2', 0.95, False), ('R1', 1.001, True)]
    """
    results = []
    for refdes, total in refdes_ratio_sums.items():
        # C7: Compare directly without rounding to respect FMR_TOLERANCE precision
        is_valid = abs(total - 1.0) <= tolerance
        results.append((refdes, total, is_valid))
    return results


def get_invalid_fmr_sums(
    refdes_ratio_sums: Dict[str, float],
    tolerance: float = FMR_TOLERANCE
) -> Dict[str, float]:
    """
    Get only the RefDes entries with invalid FMR sums.

    Convenience function that filters to just the failures.

    Args:
        refdes_ratio_sums: Dictionary mapping RefDes to summed ratio values
        tolerance: Acceptable deviation from 1.0 (default: 0.001)

    Returns:
        Dictionary of RefDes -> sum for entries that don't sum to 1.0

    Example:
        >>> get_invalid_fmr_sums({'U1': 1.0, 'U2': 0.8})
        {'U2': 0.8}
    """
    return {
        refdes: total
        for refdes, total, is_valid in validate_fmr_sums(refdes_ratio_sums, tolerance)
        if not is_valid
    }


# =============================================================================
# PART USAGE VALIDATION
# =============================================================================

def validate_part_usage(
    refdes_list: List[str],
    usage_values: List[float],
    get_base_func,
    tolerance: float = USAGE_TOLERANCE,
) -> List[Dict[str, Any]]:
    """
    Validate part usage values against expected values based on instance counts.

    For components with multiple instances (e.g., U300-1, U300-2, U300-3),
    each instance's usage should equal 1/count (e.g., 1/3 = 0.333).
    Single-instance components (e.g., U200) should have usage = 1.0.

    The function groups RefDes by their usage base (stripping all suffixes
    including pins) and validates that each row's usage matches 1/count.

    Args:
        refdes_list: List of RefDes tokens (one per row)
        usage_values: Corresponding usage values (numeric, same length)
        get_base_func: Function to extract usage base (get_usage_base_refdes)
        tolerance: Acceptable deviation from expected (default: 0.01 = 1%)

    Returns:
        List of warning dicts with keys:
        - RefDes: The specific RefDes token
        - Base: The usage base (grouped component)
        - Usage: Actual usage value from data
        - Expected: Expected usage (1/count)
        - Count: Total instance count for this base
        - ReasonCode: Stable warning code
        - Reason: Human-readable description of mismatch

    Example:
        >>> from common.refdes_utils import get_usage_base_refdes
        >>> refs = ['U300-1', 'U300-2', 'U300-3']
        >>> usages = [0.5, 0.5, 0.5]  # Should be 1/3 each
        >>> validate_part_usage(refs, usages, get_usage_base_refdes)
        [{'RefDes': 'U300-1', 'Base': 'U300', 'Usage': 0.5, 'Expected': 0.333..., ...}, ...]
    """
    if len(refdes_list) != len(usage_values):
        raise ValueError("refdes_list and usage_values must have the same length")

    warnings = []

    # 1. Count unique instances per usage base.
    # In piece-part FMEAs, the same RefDes appears once per failure mode;
    # counting rows would inflate the instance count.  Count unique tokens
    # so that C106 appearing in 3 failure-mode rows still counts as 1.
    bases = [get_base_func(r) for r in refdes_list]
    unique_tokens_per_base = defaultdict(set)
    for refdes, base in zip(refdes_list, bases):
        unique_tokens_per_base[base].add(refdes)
    base_counts = {base: len(tokens) for base, tokens in unique_tokens_per_base.items()}

    # 2. Build base→expected_usage lookup
    # Expected usage = 1 / count (each instance is 1/N of the whole component)
    base_expected = {base: 1.0 / count for base, count in base_counts.items()}

    # 3. Check each row against expected
    for refdes, base, usage in zip(refdes_list, bases, usage_values):
        expected = base_expected[base]
        count = base_counts[base]

        if abs(usage - expected) > tolerance:
            warnings.append({
                'RefDes': refdes,
                'Base': base,
                'Usage': usage,
                'Expected': expected,
                'Count': count,
                'ReasonCode': 'PU_EXPECTED_MISMATCH_BASIC',
                'Reason': f"Expected {expected:.4g} (1/{count}), got {usage:.4g}"
            })

    return warnings


# =============================================================================
# PART USAGE FORMAT VALIDATION
# =============================================================================

def validate_usage_format(
    refdes_list: List[str],
    usage_values: List[float],
    max_decimals: int = 3,
) -> List[Dict[str, Any]]:
    """
    Flag part usage values that are outside the expected format.

    Valid part usage values are in the range (0, 1.0].

    Note:
        `max_decimals` is retained for backwards compatibility with older
        call sites but is intentionally not enforced. Fractional values like
        1/3 may deserialize as repeating decimals and should still be treated
        as valid.

    Returns:
        List of warning dicts with keys matching the part-usage schema:
        RefDes, Base, Usage, Expected, Count, Reason.
    """
    warnings: List[Dict[str, Any]] = []
    for refdes, usage in zip(refdes_list, usage_values):
        reason = None
        reason_code = None
        if usage > 1.0:
            reason_code = "PU_RANGE_ABOVE_ONE"
            reason = f"Value {usage:.4g} exceeds 1.0 (possible percentage instead of fraction)"
        elif usage <= 0:
            reason_code = "PU_RANGE_NON_POSITIVE"
            reason = f"Value {usage:.4g} is zero or negative"
        if reason:
            warnings.append({
                'RefDes': refdes,
                'Base': '',
                'Usage': usage,
                'Expected': '',
                'Count': '',
                'ReasonCode': reason_code,
                'Reason': reason,
            })
    return warnings


# =============================================================================
# COMBINED FMR × PART USAGE VALIDATION
# =============================================================================

def validate_fmr_usage_product(
    refdes_list: List[str],
    usage_values: List[float],
    fmr_values: List[Optional[float]],
    get_base_func,
    fmr_tolerance: float = FMR_TOLERANCE,
    usage_tolerance: float = USAGE_TOLERANCE,
) -> List[Dict[str, Any]]:
    """
    Two-tier validation of FMR and Part Usage consistency.

    Tier 1 — per unique RefDes token: Σ(FMR) must equal 1.0.
    Tier 2 — per usage-base component: Σ(FMR × PU) must equal 1.0.

    Evaluation is **per-base**: bases with complete FMR data get the
    full two-tier check; bases with any missing FMR values get a
    "missing FMR" warning and fall back to unique-token part-usage
    validation for that base only.

    Returns:
        List of warning dicts matching the part-usage output schema:
        RefDes, Base, Usage, Expected, Count, Reason.
    """
    if len(refdes_list) != len(usage_values):
        raise ValueError("refdes_list and usage_values must have the same length")
    if len(refdes_list) != len(fmr_values):
        raise ValueError("refdes_list and fmr_values must have the same length")

    bases = [get_base_func(r) for r in refdes_list]
    warnings: List[Dict[str, Any]] = []

    # ---- Group rows by usage base ----------------------------------------
    base_rows: Dict[str, List[int]] = defaultdict(list)
    for i, base in enumerate(bases):
        base_rows[base].append(i)

    for base, indices in base_rows.items():
        # Collect data for this base
        tokens_in_base = [refdes_list[i] for i in indices]
        usages_in_base = [usage_values[i] for i in indices]
        fmrs_in_base = [fmr_values[i] for i in indices]

        has_complete_fmr = all(f is not None for f in fmrs_in_base)

        if not has_complete_fmr:
            # Fallback: unique-token PU check for this base only
            unique_tokens = set(tokens_in_base)
            count = len(unique_tokens)
            expected = 1.0 / count
            # Informational: signal that this base used fallback validation
            missing_count = sum(1 for f in fmrs_in_base if f is None)
            token_preview = ", ".join(sorted(unique_tokens)[:6])
            warnings.append({
                'RefDes': tokens_in_base[0],
                'Base': base,
                'Usage': '',
                'Expected': '',
                'Count': count,
                'ReasonCode': 'FMR_MISSING_PP',
                'Reason': f"FMR blank/NaN for {missing_count} row(s) in {base} "
                          f"— fell back to basic part usage check (tokens: {token_preview})",
            })
            # Check each unique token and detect inconsistent usage values
            seen_usage: Dict[str, float] = {}
            for idx in indices:
                rd = refdes_list[idx]
                usage = usage_values[idx]
                if rd not in seen_usage:
                    # First occurrence: validate against expected
                    seen_usage[rd] = usage
                    if abs(usage - expected) > usage_tolerance:
                        warnings.append({
                            'RefDes': rd,
                            'Base': base,
                            'Usage': usage,
                            'Expected': expected,
                            'Count': count,
                            'ReasonCode': 'PU_EXPECTED_MISMATCH',
                            'Reason': f"Expected {expected:.4g} (1/{count}), got {usage:.4g} "
                                      f"(FMR unavailable — basic PU check)",
                        })
                else:
                    # Subsequent occurrence: flag if usage differs from first-seen
                    if abs(usage - seen_usage[rd]) > usage_tolerance:
                        warnings.append({
                            'RefDes': rd,
                            'Base': base,
                            'Usage': usage,
                            'Expected': seen_usage[rd],
                            'Count': count,
                            'ReasonCode': 'PU_INCONSISTENT_DUPLICATE',
                            'Reason': f"Inconsistent usage for {rd}: "
                                      f"row has {usage:.4g} but earlier row had {seen_usage[rd]:.4g}",
                        })
            continue

        # ---- Tier 1: FMR sum per unique RefDes token = 1.0 ---------------
        token_fmr_sums: Dict[str, float] = defaultdict(float)
        for i, idx in enumerate(indices):
            token_fmr_sums[refdes_list[idx]] += fmrs_in_base[i]

        for token, fmr_sum in token_fmr_sums.items():
            if abs(fmr_sum - 1.0) > fmr_tolerance:
                warnings.append({
                    'RefDes': token,
                    'Base': base,
                    'Usage': '',
                    'Expected': 1.0,
                    'Count': len(token_fmr_sums),
                    'ReasonCode': 'FMR_SUM_MISMATCH',
                    'Reason': f"FMR sum: expected 1.0, got {fmr_sum:.4g}",
                })

        # ---- Tier 2: Σ(FMR × PU) per base = 1.0 -------------------------
        product_sum = sum(
            fmrs_in_base[i] * usages_in_base[i]
            for i in range(len(indices))
        )

        if abs(product_sum - 1.0) > usage_tolerance:
            # Report against the first token in this base for traceability
            unique_tokens = set(tokens_in_base)
            first_token = tokens_in_base[0]
            warnings.append({
                'RefDes': first_token,
                'Base': base,
                'Usage': product_sum,
                'Expected': 1.0,
                'Count': len(unique_tokens),
                'ReasonCode': 'FMR_USAGE_PRODUCT_MISMATCH',
                'Reason': f"FMR×PU sum: expected 1.0, got {product_sum:.4g}",
            })

    return warnings


# =============================================================================
# CROSS-FILE PART USAGE VALIDATION
# =============================================================================

def validate_cross_file_usage_counts(
    refdes_list: List[str],
    usage_values: List[float],
    get_base_func,
    other_base_counts: Dict[str, int],
    other_label: str = "the other file",
    tolerance: float = USAGE_TOLERANCE,
) -> List[Dict[str, Any]]:
    """
    Validate Part Usage against the OTHER file's instance count.

    Part Usage 1/N asserts the base component has N unique instance/pin
    tokens — in EVERY file that lists it, not just the file carrying the
    usage column (project convention: dash suffixes are pins of one base
    component, so usage 1/4 means four tokens like U60-1..U60-100 appear
    in both the BOM and the grouping file).

    The within-file checks (``validate_part_usage`` /
    ``validate_fmr_usage_product``) already cover usage-vs-THIS-file's
    count, so this emits at most ONE warning per base and only when the
    two files' counts actually differ:

    - ``PU_COUNT_MATCHES_THIS_FILE_ONLY``: usage agrees with this file's
      count; the other file lists a different number of instances.
    - ``PU_COUNT_MATCHES_OTHER_FILE_ONLY``: usage agrees with the other
      file's count but not this file's.
    - ``PU_CROSS_COUNT_CONFLICT``: usage agrees with neither count.

    Bases absent from ``other_base_counts`` are skipped — a base missing
    from the other file entirely is a membership finding (Missing /
    Not-Grouped sheets) and must not be double-reported here.

    Args:
        refdes_list: RefDes tokens from the file carrying the usage column
        usage_values: Corresponding numeric usage values (same length)
        get_base_func: Base extractor (``get_usage_base_refdes``)
        other_base_counts: base -> unique-instance count in the other file
        other_label: Human name for the other file, used in Reason text
        tolerance: Acceptable deviation from 1/count

    Returns:
        List of warning dicts matching the part-usage output schema:
        RefDes, Base, Usage, Expected, Count, ReasonCode, Reason.
    """
    if len(refdes_list) != len(usage_values):
        raise ValueError("refdes_list and usage_values must have the same length")

    tokens_per_base: Dict[str, set] = defaultdict(set)
    first_usage: Dict[str, float] = {}
    first_token: Dict[str, str] = {}
    for token, usage in zip(refdes_list, usage_values):
        base = get_base_func(token)
        tokens_per_base[base].add(token)
        # Rows of one base share the usage value; divergence is already
        # flagged by PU_INCONSISTENT_DUPLICATE, so first-seen represents.
        if base not in first_usage:
            first_usage[base] = usage
            first_token[base] = token

    warnings: List[Dict[str, Any]] = []
    for base, tokens in tokens_per_base.items():
        other_count = other_base_counts.get(base, 0)
        if other_count <= 0:
            continue  # membership finding, not a usage finding
        local_count = len(tokens)
        if local_count == other_count:
            continue  # within-file checks fully cover the agreeing case
        usage = first_usage[base]
        if usage is None or usage <= 0:
            continue  # non-positive usage is flagged by the format check
        matches_local = abs(usage - 1.0 / local_count) <= tolerance
        matches_other = abs(usage - 1.0 / other_count) <= tolerance
        if matches_local and matches_other:
            # Counts differ but 1/N and 1/M are within tolerance of each
            # other (large N) — nothing actionable to report.
            continue

        if matches_local:
            code = "PU_COUNT_MATCHES_THIS_FILE_ONLY"
            reason = (
                f"Part Usage {usage:.4g} matches this file's {local_count} "
                f"instance(s) of {base}, but {other_label} lists {other_count}"
            )
        elif matches_other:
            code = "PU_COUNT_MATCHES_OTHER_FILE_ONLY"
            reason = (
                f"Part Usage {usage:.4g} matches the {other_count} "
                f"instance(s) of {base} in {other_label}, but this file "
                f"lists {local_count}"
            )
        else:
            code = "PU_CROSS_COUNT_CONFLICT"
            reason = (
                f"Part Usage {usage:.4g} matches neither this file's "
                f"{local_count} instance(s) of {base} nor the "
                f"{other_count} in {other_label}"
            )
        warnings.append({
            'RefDes': first_token[base],
            'Base': base,
            'Usage': usage,
            'Expected': 1.0 / local_count,
            'Count': local_count,
            'ReasonCode': code,
            'Reason': reason,
        })

    return warnings


# =============================================================================
# PART USAGE PARSING
# =============================================================================

def parse_usage(s: Any) -> tuple[float | None, str | float | int | None]:
    """
    Parse usage value from string, handling ratio formats like '1/2' or '1 of 2'.

    Returns:
        tuple: (numeric_value, excel_repr) where:
            - On success: excel_repr is a formula string like "=1/250" for
              fraction inputs, or a numeric value (int/float) for direct inputs
            - On empty/blank input: returns (1.0, 1) as a reasonable default
              (single-instance component assumption)
            - On non-empty parse failure or division by zero: returns
              (None, None) so callers can detect and report the error
    """
    try:
        ss = clean_string(s)
        if not ss:
            return (1.0, 1)
        m = re.match(r'^(\d+(?:\.\d+)?)\s*(?:/|of)\s*(\d+(?:\.\d+)?)$', ss, re.I)
        if m:
            numerator = float(m.group(1))
            denominator = float(m.group(2))
            if denominator == 0:
                return (None, None)
            num_str = str(int(numerator)) if numerator == int(numerator) else str(numerator)
            den_str = str(int(denominator)) if denominator == int(denominator) else str(denominator)
            excel_formula = f"={num_str}/{den_str}"
            return (numerator / denominator, excel_formula)

        val = float(ss)
        if val == int(val):
            return (val, int(val))
        return (val, val)
    except (ValueError, TypeError):
        return (None, None)


# =============================================================================
# DUPLICATE DETECTION
# =============================================================================

def find_duplicates(items: List[str]) -> Dict[str, int]:
    """
    Find duplicate items and return their counts.

    Only returns items that appear more than once.

    Args:
        items: List of strings to check for duplicates

    Returns:
        Dictionary mapping duplicate items to their occurrence count

    Example:
        >>> find_duplicates(['R1', 'R2', 'R1', 'R3', 'R1'])
        {'R1': 3}
    """
    counts = Counter(items)
    return {item: count for item, count in counts.items() if count > 1}


def find_duplicates_with_context(
    items: List[str],
    context: List[Any]
) -> Dict[str, List[Any]]:
    """
    Find duplicate items and collect their associated context.

    Useful when you need to know not just which items are duplicated,
    but also where/how they appear (e.g., which groups contain them).

    Args:
        items: List of strings to check for duplicates
        context: List of context values (same length as items)

    Returns:
        Dictionary mapping duplicate items to list of their contexts

    Example:
        >>> items = ['R1', 'R2', 'R1']
        >>> context = ['GroupA', 'GroupB', 'GroupC']
        >>> find_duplicates_with_context(items, context)
        {'R1': ['GroupA', 'GroupC']}
    """
    if not items:
        return {}
    if len(items) != len(context):
        raise ValueError("items and context must have the same length")

    item_contexts: Dict[str, List[Any]] = {}
    for item, ctx in zip(items, context):
        if item not in item_contexts:
            item_contexts[item] = []
        item_contexts[item].append(ctx)

    # Only return items with multiple occurrences
    return {item: ctxs for item, ctxs in item_contexts.items() if len(ctxs) > 1}


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    'FMR_TOLERANCE',
    'USAGE_TOLERANCE',
    'validate_fmr_sums',
    'get_invalid_fmr_sums',
    'validate_part_usage',
    'validate_usage_format',
    'validate_fmr_usage_product',
    'parse_usage',
    'find_duplicates',
    'find_duplicates_with_context',
]
