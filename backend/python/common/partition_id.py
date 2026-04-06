#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared parsing and normalization helpers for partition/group IDs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Optional, Tuple

STATUS_SUFFIXES = ("(UNVERIFIED)", "(VERIFIED)", "(PARTIAL)")
MODE_SUFFIXES = ("-FN", "-PN")

_SANITIZE_RE = re.compile(r"[^A-Za-z0-9 _\-/.]")
_PLAIN_SEQUENCE_RE = re.compile(r"^(.+?)(\d{2,})$")
_DOTTED_SEQUENCE_RE = re.compile(r"^(.+?)(\d+(?:\.\d+)+)$")
_VOLTAGE_RE = re.compile(r"^\d+(?:\.\d+)?\s*[VA]$", re.I)
_REFDES_LIKE_RE = re.compile(r"^[A-Z]{1,2}\d+[A-Z]?$")

STOP_WORDS = {
    "NOTE",
    "NOTES",
    "TODO",
    "TBD",
    "NA",
    "N/A",
    "REV",
    "REVISION",
    "DOC",
    "PAGE",
    "SHEET",
    "TITLE",
    "DATE",
    "BY",
    "CHECKED",
    "APPROVED",
    "DNP",
    "DO",
    "NOT",
    "POPULATE",
    "VCC",
    "GND",
}


@dataclass(frozen=True)
class SequenceInfo:
    prefix: str
    number: int
    width: int
    kind: Literal["plain", "dotted"]


@dataclass(frozen=True)
class PartitionId:
    display_label: str
    comparison_key: str
    status_suffixes: Tuple[str, ...]
    mode_suffixes: Tuple[str, ...]
    sequence_info: Optional[SequenceInfo]
    classification: Literal["strong", "weak", "noise"]
    source: Literal["annotation", "text_layer", "image_only", "unknown"] = "unknown"


def sanitize_group_label(raw: str) -> str:
    """Normalize a raw label for partition/group-ID use."""
    if not raw:
        return ""
    txt = raw.splitlines()[0].strip()
    txt = _SANITIZE_RE.sub("", txt)
    return txt.strip().upper()


def strip_status_suffixes(raw: str) -> tuple[str, Tuple[str, ...]]:
    """Strip known trailing verification/status suffixes from raw text."""
    if raw is None:
        return "", ()

    result = str(raw).strip()
    suffixes = []
    while result:
        result_upper = result.upper()
        matched = False
        for suffix in STATUS_SUFFIXES:
            if result_upper.endswith(suffix):
                result = result[: -len(suffix)].rstrip()
                suffixes.append(suffix)
                matched = True
                break
        if not matched:
            break
    return result, tuple(reversed(suffixes))


def strip_mode_suffixes(raw: str) -> tuple[str, Tuple[str, ...]]:
    """Strip a known terminal mode suffix from raw text."""
    if raw is None:
        return "", ()

    result = str(raw).strip()
    result_upper = result.upper()
    for suffix in MODE_SUFFIXES:
        if result_upper.endswith(suffix):
            stripped = result[: -len(suffix)].rstrip()
            if stripped:
                return stripped, (suffix,)
    return result, ()


def classify_group_label(label: str) -> Literal["strong", "weak", "noise"]:
    """Classify a sanitized group label conservatively."""
    if not label:
        return "noise"
    if label in STOP_WORDS:
        return "noise"
    if len(label) > 60:
        return "noise"
    if label.isdigit():
        return "noise"
    if _VOLTAGE_RE.fullmatch(label):
        return "noise"
    if _REFDES_LIKE_RE.fullmatch(label):
        return "noise"

    has_alpha = any(ch.isalpha() for ch in label)
    has_digit = any(ch.isdigit() for ch in label)
    if has_alpha and has_digit:
        return "strong"
    if has_alpha and len(label) <= 20:
        return "weak"
    return "noise"


def parse_sequence_info(label: str) -> Optional[SequenceInfo]:
    """Parse a safe terminal sequence from a sanitized label."""
    if not label:
        return None

    dotted = _DOTTED_SEQUENCE_RE.fullmatch(label)
    if dotted:
        prefix = dotted.group(1)
        numeric_tail = dotted.group(2)
        parts = numeric_tail.split(".")
        if len(parts) >= 2 and all(part.isdigit() for part in parts):
            fixed_prefix = prefix + ".".join(parts[:-1]) + "."
            last = parts[-1]
            return SequenceInfo(
                prefix=fixed_prefix,
                number=int(last),
                width=len(last),
                kind="dotted",
            )

    plain = _PLAIN_SEQUENCE_RE.fullmatch(label)
    if plain:
        number_str = plain.group(2)
        return SequenceInfo(
            prefix=plain.group(1),
            number=int(number_str),
            width=len(number_str),
            kind="plain",
        )

    return None


def parse_partition_id(
    raw: str,
    *,
    source: Literal["annotation", "text_layer", "image_only", "unknown"] = "unknown",
    parse_mode_suffixes: bool = False,
) -> PartitionId:
    """Parse and classify a partition/group ID."""
    without_status, status_suffixes = strip_status_suffixes(raw)
    without_mode = without_status
    mode_suffixes: Tuple[str, ...] = ()
    if parse_mode_suffixes:
        without_mode, mode_suffixes = strip_mode_suffixes(without_status)

    display_label = sanitize_group_label(without_mode)
    comparison_key = display_label
    classification = classify_group_label(display_label)
    sequence_info = parse_sequence_info(display_label)

    return PartitionId(
        display_label=display_label,
        comparison_key=comparison_key,
        status_suffixes=status_suffixes,
        mode_suffixes=mode_suffixes,
        sequence_info=sequence_info,
        classification=classification,
        source=source,
    )
