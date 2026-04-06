#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""User-facing label helpers for reliability validation outputs.

These helpers convert internal shorthand codes/messages into plain-language
labels suitable for exports and GUI tables.
"""

from __future__ import annotations

import re
from typing import Any


REASON_CODE_LABELS = {
    "PU_EXPECTED_MISMATCH_BASIC": "Part Usage Expected Value Mismatch (Basic Validation)",
    "PU_RANGE_ABOVE_ONE": "Part Usage Value Above 1.0",
    "PU_RANGE_NON_POSITIVE": "Part Usage Value Is Zero or Negative",
    "FMR_MISSING_PP": "Failure Mode Ratio Missing for Piece-Part Rows",
    "PU_EXPECTED_MISMATCH": "Part Usage Expected Value Mismatch",
    "PU_INCONSISTENT_DUPLICATE": "Part Usage Inconsistent Across Duplicate Rows",
    "FMR_SUM_MISMATCH": "Failure Mode Ratio Sum Mismatch",
    "FMR_USAGE_PRODUCT_MISMATCH": "Failure Mode Ratio and Part Usage Product Mismatch",
    "PU_PARSE_DEFAULTED": "Part Usage Parse Failed and Was Defaulted to 1.0",
    "SCOPE_CB_ONLY": "Scope Mismatch: Circuit Block Only",
    "SCOPE_PP_ONLY": "Scope Mismatch: Piece-Part Only",
    "SCOPE_UNCLASSIFIED_ONLY": "Scope Mismatch: Unclassified Row Type Only",
}


STATUS_LABELS = {
    "FMR != 1.0": "Failure Mode Ratio does not equal 1.0",
    "FMR sum != 1.0": "Failure Mode Ratio sum does not equal 1.0",
}


def expand_reliability_abbreviations(value: Any) -> Any:
    """Expand reliability abbreviations in user-facing string values.

    Non-string values are returned unchanged.
    """
    if value is None or not isinstance(value, str):
        return value

    text = value
    text = re.sub(
        r"\bFMR\s*[xX\*×]\s*PU\b",
        "Failure Mode Ratio × Part Usage",
        text,
    )
    text = re.sub(r"\bFMR\b", "Failure Mode Ratio", text)
    text = re.sub(r"\bPU\b", "Part Usage", text)
    text = re.sub(r"\bCB\b", "Circuit Block", text)
    text = re.sub(r"\bPP\b", "Piece-Part", text)
    return text


def to_reason_code_label(code: Any) -> str:
    """Convert a technical reason code into a plain-language label."""
    if code is None:
        return ""

    text = str(code).strip()
    if not text:
        return ""

    mapped = REASON_CODE_LABELS.get(text)
    if mapped:
        return mapped

    return expand_reliability_abbreviations(text.replace("_", " "))


def to_user_facing_text(value: Any) -> Any:
    """Convert shorthand status/message text to user-facing wording."""
    if value is None or not isinstance(value, str):
        return value

    mapped = STATUS_LABELS.get(value, value)
    return expand_reliability_abbreviations(mapped)

