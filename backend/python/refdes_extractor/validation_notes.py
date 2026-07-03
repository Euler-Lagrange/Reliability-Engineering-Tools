# -*- coding: utf-8 -*-
"""Validation Notes for the RefDes extraction sheet.

Annotates engine result rows *runtime-side* (the extraction engines are
untouched) with a human-readable ``validation notes`` string plus an internal
``_row_style`` marker consumed only by the Excel styler:

* **Cross-group duplicates** — the 2nd (3rd, ...) occurrence of a component
  across distinct groups gets an ordinal note naming where it was first seen,
  ordered by page number (reading order). A component sitting in both the
  ``(Verified)`` and ``(Unverified)`` rows of ONE group cannot happen (the
  engine's sets are disjoint), so the V/U split never self-flags.
* **Not found in BOM** — populated ``(Unverified)`` rows get an explicit
  reason note, but only when a BOM was provided (nothing is "unverified"
  without one).
* **Sequence gaps** — ``GROUP NOT DETECTED`` placeholder rows get a note
  explaining why the row exists.

Each note is a full sentence; multiple notes join with a single space.
``_row_style`` is ``_``-prefixed so ``_results_dataframe`` drops it before
the DataFrame reaches the worksheet.
"""

from __future__ import annotations

import re
from typing import Iterable, List

from common.refdes_utils import split_refdes_list

# Notes text is user-facing; keep the vocabulary here so tests and future
# tools reference one source of truth.
NOTE_GAP_ROW = "Expected group missing from schematic (sequence gap)."

# Style names must exist in common.excel_styles.StylePresets._semantic_styles.
STYLE_DEFAULT = "default"
STYLE_DUPLICATE = "warning"
STYLE_GAP = "gap"
STYLE_UNVERIFIED = "unverified"

_VU_SUFFIX_RE = re.compile(r"\s*\((?:Verified|Unverified)\)\s*$")
_PAGE_NUM_RE = re.compile(r"\d+")

# Above this many missing components the not-in-BOM note switches to a count —
# the full list already sits in the adjacent Failure Mode Causes cell.
_NOT_IN_BOM_LIST_CAP = 12

_NO_PAGE = 10**9  # sort sentinel for rows without parseable page numbers


def _base_group(group: str) -> str:
    """Group identity with the (Verified)/(Unverified) split stripped."""
    return _VU_SUFFIX_RE.sub("", str(group or "")).strip()


def _is_gap_row(row: dict) -> bool:
    return bool(row.get("_is_gap")) or "GROUP NOT DETECTED" in str(row.get("group", ""))


def _tokens(row: dict) -> List[str]:
    """Component tokens for a row, skipping punctuation fragments.

    Uses the same splitter as ``coverage_report.build_coverage`` so both
    consumers of the joined cell agree. Pin-uncertainty markers like ``[?]``
    split off as their own fragment — drop anything without an alphanumeric.
    """
    raw = split_refdes_list(str(row.get("failure mode causes", "") or ""))
    return [t for t in raw if any(ch.isalnum() for ch in t)]


def _min_page(row: dict) -> int:
    nums = [int(p) for p in _PAGE_NUM_RE.findall(str(row.get("pages", "") or ""))]
    return min(nums) if nums else _NO_PAGE


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def annotate_results(results: Iterable[dict], *, bom_provided: bool) -> List[dict]:
    """Return copies of ``results`` rows with validation notes attached.

    Adds two keys to every row:

    * ``"validation notes"`` — space-joined reason sentences (may be ``""``)
    * ``"_row_style"`` — semantic style name for the Excel styler (internal;
      dropped from the sheet DataFrame by ``_results_dataframe``)
    """
    rows = [dict(row) for row in results]

    # token -> occurrence sites, ordered by first page then emitted row order.
    # V/U rows of one group share a base identity but their token sets are
    # disjoint, so each (token, row) pair is a genuine extraction site.
    sites: dict[str, list[tuple[int, int, int]]] = {}  # token -> [(page, row_idx)]
    for idx, row in enumerate(rows):
        if _is_gap_row(row):
            continue
        page = _min_page(row)
        for token in _tokens(row):
            sites.setdefault(token, []).append((page, idx))

    duplicate_notes: dict[int, list[str]] = {}
    for token, occurrences in sites.items():
        if len(occurrences) < 2:
            continue
        ordered = sorted(occurrences, key=lambda item: item)
        first_page, first_idx = ordered[0]
        first_group = _base_group(rows[first_idx].get("group", ""))
        first_seen = f"first seen in {first_group}"
        if first_page != _NO_PAGE:
            first_seen += f" (p. {first_page})"
        for position, (_page, row_idx) in enumerate(ordered[1:], start=2):
            duplicate_notes.setdefault(row_idx, []).append(
                f"{_ordinal(position)} extraction of {token} — {first_seen}."
            )

    for idx, row in enumerate(rows):
        notes: list[str] = []
        style = STYLE_DEFAULT

        if _is_gap_row(row):
            notes.append(NOTE_GAP_ROW)
            style = STYLE_GAP
        else:
            dup_notes = duplicate_notes.get(idx, [])
            notes.extend(dup_notes)

            group = str(row.get("group", ""))
            is_unverified = group.rstrip().endswith("(Unverified)")
            tokens = _tokens(row) if is_unverified else []
            if bom_provided and is_unverified and tokens:
                if len(tokens) > _NOT_IN_BOM_LIST_CAP:
                    notes.append(f"Not found in BOM: {len(tokens)} components.")
                else:
                    notes.append(f"Not found in BOM: {', '.join(tokens)}.")

            if dup_notes:
                style = STYLE_DUPLICATE
            elif bom_provided and is_unverified and tokens:
                style = STYLE_UNVERIFIED

        row["validation notes"] = " ".join(notes)
        row["_row_style"] = style

    return rows
