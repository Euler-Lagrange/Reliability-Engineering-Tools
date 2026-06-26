# -*- coding: utf-8 -*-
"""BOM-coverage reverse-diff for the RefDes Extractor.

The extraction engines already split every *extracted* component into
``(Verified)`` / ``(Unverified)`` against the BOM, so "extracted but absent
from the BOM" is implicit in the Unverified rows. This module adds the two
explicit directions an engineer needs to reconcile a board:

    * **BOM Not Grouped**      — RefDes that are in the BOM but never landed in
      a real extracted group, classified as ``Not Extracted`` (never seen on
      the schematic) vs ``Extracted-Ungrouped`` / ``Extracted-Provisional``
      (seen, but not cleanly grouped). Note: the default **NextGen** backend
      discards words outside every annotation group, so under it those parts
      surface as ``Not Extracted`` and ``Extracted-Ungrouped`` only appears via
      the legacy fallback backend (which emits explicit ``UNGROUPED`` rows).
    * **Extracted Not In BOM** — RefDes pulled off the schematic that are not
      in the BOM.

Coverage is **component level**: instance/pin suffixes collapse to their base
RefDes via :func:`get_usage_base_refdes` (``U200-1`` and ``U200-2`` both cover
BOM ``U200``; ``J1-4`` covers ``J1``). The same base-normalization is applied
to both sides so the diff is self-consistent. ``GROUP NOT DETECTED`` / gap
placeholder rows are never treated as extraction evidence.

The module is pure (no I/O) apart from :func:`write_coverage_sheets`, which
appends the three report sheets to an open ``openpyxl`` workbook.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Set

from common.refdes_utils import get_usage_base_refdes, split_refdes_list

# Status labels for the BOM Not Grouped sheet (kept as module constants so the
# UI/tests reference one source of truth).
STATUS_NOT_EXTRACTED = "Not Extracted"
STATUS_EXTRACTED_UNGROUPED = "Extracted-Ungrouped"
STATUS_EXTRACTED_PROVISIONAL = "Extracted-Provisional"

SHEET_SUMMARY = "Coverage Summary"
SHEET_BOM_NOT_GROUPED = "BOM Not Grouped"
SHEET_EXTRACTED_NOT_IN_BOM = "Extracted Not In BOM"

_BOM_NOT_GROUPED_HEADER = ["RefDes", "Part Number", "Description", "Status", "Pages"]
_EXTRACTED_NOT_IN_BOM_HEADER = ["RefDes", "Group", "Pages"]


@dataclass(frozen=True)
class CoverageResult:
    """Component-level coverage of a BOM against schematic extraction."""

    bom_not_grouped: List[dict] = field(default_factory=list)
    extracted_not_in_bom: List[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def _norm(token: str) -> str:
    """Component-level base RefDes, or '' when the token is not a RefDes.

    A real RefDes is prefix + number, so a usage-base with no digit is not a
    component. This drops the engines' unparented-pin fallback token
    ``PIN-{text}`` (piece-part mode), whose base is the literal ``PIN``, plus
    stray net/power labels — keeping both sides of the diff to real components
    (mirrors nextgen's own ``_extract_base_refdes`` rejecting ``PIN-`` tokens).
    """
    base = get_usage_base_refdes(token)
    if not base or not any(ch.isdigit() for ch in base):
        return ""
    return base


def _cell_str(value) -> str:
    """NaN/None-safe stringification of a result/metadata cell.

    A NaN float is the only value not equal to itself; the project's standing
    gotcha is to guard it before any string op (else ``str(nan)`` -> 'nan' leaks
    a phantom 'NAN' token).
    """
    if value is None:
        return ""
    if isinstance(value, float) and value != value:
        return ""
    return str(value)


def _format_pages(pages: Optional[Iterable[object]]) -> str:
    if not pages:
        return ""
    try:
        ordered = sorted(pages)
    except TypeError:
        # Defensive: a mixed int/str page set must never crash a run — coverage
        # sits on the extraction critical path.
        ordered = sorted(pages, key=str)
    return ", ".join(str(p) for p in ordered)


def _split_pages(value: object) -> set:
    """Split a comma-joined page cell into a set of int (or str) page tokens."""
    out: set = set()
    for part in _cell_str(value).split(","):
        part = part.strip()
        if part:
            out.add(int(part) if part.isdigit() else part)
    return out


def build_coverage(
    bom_set: Set[str],
    results: List[Mapping[str, object]],
    *,
    bom_meta: Optional[Mapping[str, Mapping[str, str]]] = None,
    bom_page_map: Optional[Mapping[str, Iterable[int]]] = None,
) -> CoverageResult:
    """Compute the BOM/extraction reverse-diff.

    Args:
        bom_set: BOM RefDes (as loaded by ``bom_loader`` — base form).
        results: extraction result rows (``group`` / ``failure mode causes`` /
            ``pages`` / ``_is_gap``).
        bom_meta: optional ``{bom_refdes: {"part_number", "description"}}``.
        bom_page_map: optional ``{bom_refdes: {page_numbers}}``.
    """
    bom_meta = bom_meta or {}
    bom_page_map = bom_page_map or {}

    # Group BOM entries by their normalized base so multiple instance/pin rows
    # sharing a usage-base (U200-1/U200-2, connector pins) collapse to one
    # deterministic component-level row WITHOUT losing the others' pages or
    # metadata (set iteration order is non-deterministic, so never pick a single
    # arbitrary winner).
    bom_groups: Dict[str, List[str]] = {}
    for entry in bom_set:
        nb = _norm(entry)
        if nb:
            bom_groups.setdefault(nb, []).append(entry)
    bom_base = set(bom_groups)

    grouped_base: Set[str] = set()
    ungrouped_base: Set[str] = set()
    provisional_base: Set[str] = set()
    # Accumulate ALL group labels + pages a normalized token is seen in, so the
    # over-extraction sheet unions pages across rows and can prefer a real group
    # over PROVISIONAL/UNGROUPED — mirroring the BOM-side merge, never first-wins.
    extracted_groups: Dict[str, set] = {}
    extracted_pages: Dict[str, set] = {}

    for row in results:
        group = _cell_str(row.get("group"))
        if row.get("_is_gap") or "GROUP NOT DETECTED" in group:
            continue
        is_provisional = "PROVISIONAL" in group
        is_ungrouped = "UNGROUPED" in group
        row_pages = _split_pages(row.get("pages"))
        for token in split_refdes_list(_cell_str(row.get("failure mode causes"))):
            nt = _norm(token)
            if not nt:
                continue
            if is_provisional:
                provisional_base.add(nt)
            elif is_ungrouped:
                ungrouped_base.add(nt)
            else:
                grouped_base.add(nt)
            extracted_groups.setdefault(nt, set()).add(group)
            extracted_pages.setdefault(nt, set()).update(row_pages)

    extracted_any_base = grouped_base | ungrouped_base | provisional_base

    # --- BOM Not Grouped: in BOM, not in a real group ---
    bom_not_grouped: List[dict] = []
    not_extracted = ungrouped = provisional = 0
    for nb in sorted(bom_base - grouped_base):
        if nb in provisional_base:
            status = STATUS_EXTRACTED_PROVISIONAL
            provisional += 1
        elif nb in ungrouped_base:
            status = STATUS_EXTRACTED_UNGROUPED
            ungrouped += 1
        else:
            status = STATUS_NOT_EXTRACTED
            not_extracted += 1
        # Merge every BOM row that collapsed to this base: deterministic display
        # (sorted), first non-blank part#/description, unioned pages.
        entries = sorted(bom_groups[nb])
        part_number = ""
        description = ""
        pages = set()
        for entry in entries:
            meta = bom_meta.get(entry) or {}
            if not part_number:
                part_number = _cell_str(meta.get("part_number"))
            if not description:
                description = _cell_str(meta.get("description"))
            entry_pages = bom_page_map.get(entry)
            if entry_pages:
                pages.update(entry_pages)
        bom_not_grouped.append(
            {
                "refdes": entries[0],
                "part_number": part_number,
                "description": description,
                "status": status,
                "pages": _format_pages(pages),
            }
        )

    # --- Extracted Not In BOM: pulled off schematic, absent from BOM ---
    extracted_not_in_bom: List[dict] = []
    for nt in sorted(extracted_any_base - bom_base):
        groups = extracted_groups.get(nt, set())
        real_groups = sorted(
            g for g in groups if g and "UNGROUPED" not in g and "PROVISIONAL" not in g
        )
        if real_groups:
            display_group = real_groups[0]
        else:
            other = sorted(g for g in groups if g)
            display_group = other[0] if other else ""
        extracted_not_in_bom.append(
            {
                "refdes": nt,
                "group": display_group,
                "pages": _format_pages(extracted_pages.get(nt, set())),
            }
        )

    summary = {
        "bom_count": len(bom_base),
        "grouped_from_bom": len(bom_base & grouped_base),
        "bom_not_grouped_count": len(bom_not_grouped),
        "not_extracted_count": not_extracted,
        "extracted_ungrouped_count": ungrouped,
        "extracted_provisional_count": provisional,
        "extracted_not_in_bom_count": len(extracted_not_in_bom),
    }

    return CoverageResult(
        bom_not_grouped=bom_not_grouped,
        extracted_not_in_bom=extracted_not_in_bom,
        summary=summary,
    )


def write_coverage_sheets(wb, coverage: CoverageResult) -> None:
    """Append the three coverage sheets to an open openpyxl workbook."""
    s = coverage.summary

    ws = wb.create_sheet(SHEET_SUMMARY)
    ws.append(["Metric", "Count"])
    ws.append(["BOM components", s.get("bom_count", 0)])
    ws.append(["Grouped from BOM", s.get("grouped_from_bom", 0)])
    ws.append(["BOM not grouped", s.get("bom_not_grouped_count", 0)])
    ws.append(["  - Not extracted", s.get("not_extracted_count", 0)])
    ws.append(["  - Extracted, ungrouped", s.get("extracted_ungrouped_count", 0)])
    ws.append(["  - Extracted, provisional", s.get("extracted_provisional_count", 0)])
    ws.append(["Extracted not in BOM", s.get("extracted_not_in_bom_count", 0)])

    ws = wb.create_sheet(SHEET_BOM_NOT_GROUPED)
    ws.append(_BOM_NOT_GROUPED_HEADER)
    for row in coverage.bom_not_grouped:
        ws.append(
            [
                row.get("refdes", ""),
                row.get("part_number", ""),
                row.get("description", ""),
                row.get("status", ""),
                row.get("pages", ""),
            ]
        )

    ws = wb.create_sheet(SHEET_EXTRACTED_NOT_IN_BOM)
    ws.append(_EXTRACTED_NOT_IN_BOM_HEADER)
    for row in coverage.extracted_not_in_bom:
        ws.append([row.get("refdes", ""), row.get("group", ""), row.get("pages", "")])
