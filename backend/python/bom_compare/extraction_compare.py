# -*- coding: utf-8 -*-
"""Extraction Compare — diff two RefDes-extraction output workbooks.

Given the "RefDes Extraction" sheets of two runs (rev A vs rev B), report:

* **Appeared**    — components extracted in B but not in A
* **Disappeared** — components extracted in A but not in B
* **Moved**       — components in both whose group changed

Group identity is normalized before diffing: the ``(Verified)`` /
``(Unverified)`` split suffixes are stripped (they are BOM-verification
state, not group membership) and ``GROUP NOT DETECTED`` gap-placeholder rows
are skipped entirely — without this every rev-to-rev diff reports phantom
"moved group" churn.

Purpose-built rather than reusing ``compare_two_boms``: "changed group" is a
membership semantic, not a per-column value diff.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List

import pandas as pd

from common.excel_styles import (
    StylePresets,
    style_header_only,
    style_worksheet,
    write_df_to_sheet,
)
from common.refdes_utils import split_refdes_list

SHEET_SUMMARY = "Summary"
SHEET_APPEARED = "Appeared"
SHEET_DISAPPEARED = "Disappeared"
SHEET_MOVED = "Moved Groups"

_VU_SUFFIX_RE = re.compile(r"\s*\((?:Verified|Unverified)\)\s*$")

# Column names as written by the extractor (Title Case display headers).
_GROUP_COL = "Group"
_CAUSES_COL = "Failure Mode Causes"


@dataclass
class ExtractionCompareResult:
    appeared: List[dict] = field(default_factory=list)      # {component, group}
    disappeared: List[dict] = field(default_factory=list)   # {component, group}
    moved: List[dict] = field(default_factory=list)         # {component, from_group, to_group}
    in_both_count: int = 0
    total_a: int = 0
    total_b: int = 0


def _normalize_group(group: str) -> str:
    return _VU_SUFFIX_RE.sub("", str(group or "")).strip()


def _column(df: pd.DataFrame, wanted: str) -> str:
    """Resolve a column case-insensitively so hand-edited sheets still load."""
    for col in df.columns:
        if str(col).strip().lower() == wanted.lower():
            return str(col)
    raise ValueError(
        f"Input does not look like a RefDes extraction sheet: missing the "
        f"'{wanted}' column (found: {', '.join(str(c) for c in df.columns)})."
    )


def load_component_groups(df: pd.DataFrame) -> Dict[str, str]:
    """Build ``{component: group membership}`` from one extraction sheet.

    Skips gap-placeholder rows; strips the (Verified)/(Unverified) split.
    UNGROUPED/PROVISIONAL rows are kept as named buckets — a component moving
    out of UNGROUPED into a real group is exactly the churn worth seeing.

    Two traps this must guard (both shipped as review findings):

    * ``try_read_table`` maps BLANK cells to ``float('nan')``, and nearly
      every real sheet has blank causes cells (the empty half of the
      Verified/Unverified split). ``str(nan)`` would fabricate a phantom
      ``"NAN"`` component — always ``pd.notna`` before ``str()``.
    * A component can sit in SEVERAL groups (cross-group duplicate). The
      value is therefore the sorted, comma-joined membership set — never
      first-row-wins, which made the moved-group report depend on sheet
      row order.
    """
    group_col = _column(df, _GROUP_COL)
    causes_col = _column(df, _CAUSES_COL)

    membership: Dict[str, set] = {}
    for _, row in df.iterrows():
        raw_group = row.get(group_col, "")
        raw_causes = row.get(causes_col, "")
        if not pd.notna(raw_group) or not pd.notna(raw_causes):
            continue
        raw_group = str(raw_group)
        if "GROUP NOT DETECTED" in raw_group:
            continue
        group = _normalize_group(raw_group)
        if not group:
            continue
        for token in split_refdes_list(str(raw_causes)):
            if not any(ch.isalnum() for ch in token):
                continue
            membership.setdefault(token, set()).add(group)
    return {
        token: ", ".join(sorted(groups))
        for token, groups in membership.items()
    }


def compare_extractions(df_a: pd.DataFrame, df_b: pd.DataFrame) -> ExtractionCompareResult:
    groups_a = load_component_groups(df_a)
    groups_b = load_component_groups(df_b)

    keys_a = set(groups_a)
    keys_b = set(groups_b)

    result = ExtractionCompareResult(total_a=len(keys_a), total_b=len(keys_b))
    for token in sorted(keys_b - keys_a):
        result.appeared.append({"component": token, "group": groups_b[token]})
    for token in sorted(keys_a - keys_b):
        result.disappeared.append({"component": token, "group": groups_a[token]})
    for token in sorted(keys_a & keys_b):
        result.in_both_count += 1
        if groups_a[token] != groups_b[token]:
            result.moved.append(
                {
                    "component": token,
                    "from_group": groups_a[token],
                    "to_group": groups_b[token],
                }
            )
    return result


def _write_sheet(wb, title: str, df: pd.DataFrame, presets: StylePresets) -> None:
    ws = wb.create_sheet(title)
    write_df_to_sheet(ws, df)
    if df.empty:
        style_header_only(ws, len(df.columns), presets)
    else:
        style_worksheet(ws, df, presets=presets, alternate_rows=True)


def write_extraction_compare_excel(
    result: ExtractionCompareResult,
    wb,
    *,
    name_a: str,
    name_b: str,
    presets: StylePresets = None,
) -> None:
    """Write the four report sheets into an open openpyxl workbook.

    The caller owns the workbook lifecycle (atomic write + verify), matching
    the other bom_compare writers.
    """
    presets = presets or StylePresets()

    summary_df = pd.DataFrame(
        [
            [f"Components in {name_a}", result.total_a],
            [f"Components in {name_b}", result.total_b],
            ["In both", result.in_both_count],
            [f"Appeared (only in {name_b})", len(result.appeared)],
            [f"Disappeared (only in {name_a})", len(result.disappeared)],
            ["Moved groups", len(result.moved)],
        ],
        columns=["Metric", "Count"],
    )
    # The workbook arrives with a default active sheet; reuse it for Summary.
    ws = wb.active
    ws.title = SHEET_SUMMARY
    write_df_to_sheet(ws, summary_df)
    style_worksheet(ws, summary_df, presets=presets, auto_filter=False)

    appeared_df = pd.DataFrame(
        [[r["component"], r["group"]] for r in result.appeared],
        columns=["Component", f"Group in {name_b}"],
    )
    _write_sheet(wb, SHEET_APPEARED, appeared_df, presets)

    disappeared_df = pd.DataFrame(
        [[r["component"], r["group"]] for r in result.disappeared],
        columns=["Component", f"Group in {name_a}"],
    )
    _write_sheet(wb, SHEET_DISAPPEARED, disappeared_df, presets)

    moved_df = pd.DataFrame(
        [[r["component"], r["from_group"], r["to_group"]] for r in result.moved],
        columns=["Component", f"Group in {name_a}", f"Group in {name_b}"],
    )
    _write_sheet(wb, SHEET_MOVED, moved_df, presets)
