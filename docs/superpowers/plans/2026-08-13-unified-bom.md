# Unified BOM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Create Unified BOM" option to BOM Compare (Group + Custom modes) that appends a color-coded merged-BOM tab to the compare output workbook.

**Architecture:** A new pure-logic module `backend/python/bom_compare/unified_bom.py` builds the merge (new file = backbone, old file's manual data carried forward, per-row Status/Source/Change Notes) and writes one styled sheet into the workbook the existing writers already build, before their single atomic save. Two new option keys (`create_unified_bom`, `unified_newer_file`) flow from a frontend checkbox + picker through `runtime.py`.

**Tech Stack:** Python (pandas, openpyxl) sidecar; React 19 + TypeScript frontend; pytest + Vitest/RTL.

**Spec:** `docs/superpowers/specs/2026-08-13-unified-bom-design.md` — read it first; it defines every rule implemented here.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `backend/python/bom_compare/unified_bom.py` | **Create** | Merge logic (`build_unified_bom`) + sheet writer (`write_unified_bom_sheet`). Pure; no I/O except the openpyxl sheet append. |
| `backend/python/bom_compare/bom_compare_logic.py` | Modify (bottom re-export block) | Re-export the new module's public names (facade pattern used by every sibling). |
| `backend/python/bom_compare/group_analysis.py` | Modify (`write_excel_report`) | Optional `unified=` param; writes the tab before `wb.save`. |
| `backend/python/bom_compare/excel_export.py` | Modify (`write_bom_compare_excel`) | Same optional `unified=` param. |
| `backend/python/bom_compare/runtime.py` | Modify | Read the two option keys in group + custom runners; validate-time rejection of a bad `unified_newer_file`. |
| `backend/tests/test_unified_bom.py` | **Create** | All merge-logic + writer tests. |
| `backend/tests/test_bom_compare_runtime.py` | Modify | Option wiring / validation / output-tab runtime tests. |
| `frontend/src/features/bom-compare/BomCompareTool.tsx` | Modify | Checkbox (data-driven loop), newer-file `CustomSelect`, payload keys. |
| `frontend/src/features/bom-compare/BomCompareTool.test.tsx` | Modify | UI + payload tests. |
| `frontend/src/mocks/scenarios.ts` | Modify | Unified-BOM notes line in group + custom demo results. |
| `CLAUDE.md`, `README.md`, `docs/TESTING.md` | Modify | Test-count sync (Wiring Invariant #10). |

Run backend tests from the repo root with the project venv:
`.venv\Scripts\python.exe -m pytest backend/tests/test_unified_bom.py -v`

---

### Task 1: Module skeleton — column plan, value helpers, re-exports

**Files:**
- Create: `backend/python/bom_compare/unified_bom.py`
- Modify: `backend/python/bom_compare/bom_compare_logic.py` (bottom re-export block, after the `excel_export` imports at line ~194)
- Test: `backend/tests/test_unified_bom.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_unified_bom.py`:

```python
"""Unit tests for bom_compare/unified_bom.py — the Unified BOM merge.

Spec: docs/superpowers/specs/2026-08-13-unified-bom-design.md
"""
from __future__ import annotations

import threading

import pandas as pd
import pytest

from bom_compare.unified_bom import (
    _plan_columns,
    _values_equal,
)


def test_plan_columns_union_order_and_tool_columns():
    old = pd.DataFrame(columns=["RefDes", "Sheet Number", "Commodity L1"])
    new = pd.DataFrame(columns=["RefDes", "Part Number"])
    cols, old_map, tool = _plan_columns(old, new, None)
    # New file's columns first (original order), then old-only columns
    # (old-file order), then the three tool-authored columns.
    assert cols == [
        "RefDes", "Part Number", "Sheet Number", "Commodity L1",
        "Status", "Source", "Change Notes",
    ]
    assert old_map == {
        "RefDes": "RefDes",
        "Sheet Number": "Sheet Number",
        "Commodity L1": "Commodity L1",
    }
    assert tool == {"status": "Status", "source": "Source", "notes": "Change Notes"}


def test_plan_columns_case_insensitive_identity():
    old = pd.DataFrame(columns=["REFDES", "part number"])
    new = pd.DataFrame(columns=["RefDes", "Part Number"])
    cols, old_map, _tool = _plan_columns(old, new, None)
    assert old_map == {"REFDES": "RefDes", "part number": "Part Number"}
    # Identity match must not duplicate the columns.
    assert cols[:2] == ["RefDes", "Part Number"]
    assert "REFDES" not in cols


def test_plan_columns_explicit_pairs_win():
    old = pd.DataFrame(columns=["Ref", "Desc"])
    new = pd.DataFrame(columns=["RefDes", "Part Description"])
    cols, old_map, _tool = _plan_columns(
        old, new, [("Ref", "RefDes"), ("Desc", "Part Description")]
    )
    assert old_map == {"Ref": "RefDes", "Desc": "Part Description"}
    assert cols[:2] == ["RefDes", "Part Description"]
    assert "Ref" not in cols and "Desc" not in cols


def test_plan_columns_tool_name_collision_guard():
    old = pd.DataFrame(columns=["RefDes"])
    new = pd.DataFrame(columns=["RefDes", "Status"])
    cols, _old_map, tool = _plan_columns(old, new, None)
    assert tool["status"] == "Merge Status"
    assert cols.count("Status") == 1
    assert cols.count("Merge Status") == 1


@pytest.mark.parametrize(
    ("a", "b", "equal"),
    [
        ("10", "10.0", True),
        (10, "10", True),
        ("RES 10K", "res 10k", True),
        ("  x ", "x", True),
        ("", None, True),
        (float("nan"), "", True),
        ("10", "10.5", False),
        ("A", "B", False),
    ],
)
def test_values_equal(a, b, equal):
    assert _values_equal(a, b) is equal
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_unified_bom.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'bom_compare.unified_bom'`

- [ ] **Step 3: Create the module skeleton**

Create `backend/python/bom_compare/unified_bom.py`:

```python
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
    split_refdes_list,
)

from .bom_compare_logic import DEFAULT_DNP_REGEX

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


def _values_equal(a: Any, b: Any) -> bool:
    """Trimmed, case-insensitive, numeric-equivalent comparison.

    '10' vs '10.0' is NOT a change; 'RES 10K' vs 'res 10k' is NOT a
    change. The new value still lands in the cell either way — this only
    decides whether the difference is *reported*.
    """
    ta, tb = _cell_text(a), _cell_text(b)
    if ta.casefold() == tb.casefold():
        return True
    try:
        return float(ta) == float(tb)
    except (TypeError, ValueError):
        return False


def _row_tokens(cell: Any) -> List[str]:
    """Canonical RefDes tokens for one cell (multi-token cells split)."""
    tokens: List[str] = []
    for tok in split_refdes_list(cell):
        canon = canonicalize_refdes(tok)
        if canon:
            tokens.append(canon)
    return tokens


def _is_suffix_of(token: str, base: str) -> bool:
    """True when ``token`` is a manual suffix/pin row of ``base``.

    Pin-style tokens (J4-P1) and instance suffixes (U2000-3) both reduce
    to their component base via get_usage_base_refdes; the token must
    actually differ from the base so a bare row never counts as its own
    suffix.
    """
    return token != base and get_usage_base_refdes(token) == base


def _plan_columns(
    old_df: pd.DataFrame,
    new_df: pd.DataFrame,
    column_pairs: Optional[List[Tuple[str, str]]],
) -> Tuple[List[str], Dict[str, str], Dict[str, str]]:
    """Build the unified column layout.

    Returns (unified_columns, old_to_unified, tool_columns) where:
    - unified_columns: the new file's columns in original order, then
      old-only columns (old-file order), then the three tool-authored
      columns (Status / Source / Change Notes).
    - old_to_unified: every old column name -> the unified column it
      fills. Identity is case-insensitive exact header match; explicit
      column_pairs (old_col, new_col) win over the name match.
    - tool_columns: {"status": ..., "source": ..., "notes": ...} — the
      actual (collision-guarded) tool column names.
    """
    new_cols = [str(c) for c in new_df.columns]
    old_cols = [str(c) for c in old_df.columns]

    by_fold: Dict[str, str] = {}
    for c in new_cols:
        by_fold.setdefault(c.strip().casefold(), c)

    old_to_unified: Dict[str, str] = {}
    for pair in column_pairs or []:
        old_col, new_col = str(pair[0]), str(pair[1])
        if old_col in old_cols and new_col in new_cols:
            old_to_unified[old_col] = new_col
    for c in old_cols:
        if c in old_to_unified:
            continue
        old_to_unified[c] = by_fold.get(c.strip().casefold(), c)

    unified = list(new_cols)
    for c in old_cols:
        target = old_to_unified[c]
        if target not in unified:
            unified.append(target)

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
    return unified, old_to_unified, tool_columns
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_unified_bom.py -v`
Expected: PASS (12 tests: 4 plan-columns + 8 parametrized equality)

- [ ] **Step 5: Add the facade re-exports**

In `backend/python/bom_compare/bom_compare_logic.py`, after the `from .excel_export import (...)` block at the bottom of the file, add:

```python
from .unified_bom import (  # noqa: E402
    SHEET_UNIFIED,
    UnifiedBomResult,
    build_unified_bom,
    write_unified_bom_sheet,
)
```

NOTE: `build_unified_bom` / `write_unified_bom_sheet` do not exist yet (Tasks 2/4), so this edit would break the import at this point. **Skip this step** — Task 4 Step 4 performs exactly this edit once both names exist. (Listed here only so the facade change is visible in the task's file map.)

- [ ] **Step 6: Run the security audit + commit**

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/test_unified_bom.py backend/tests/test_security_audit.py -q
git add backend/python/bom_compare/unified_bom.py backend/tests/test_unified_bom.py
git commit -m "BOM Compare: Add unified-BOM column plan + merge helpers"
```
Expected: all green (the security audit live-tree scan must accept the new module — it imports nothing networked).

---

### Task 2: Core merge — matching, statuses, conflict rule, inline deletions

**Files:**
- Modify: `backend/python/bom_compare/unified_bom.py`
- Test: `backend/tests/test_unified_bom.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_unified_bom.py` (and extend the module import at the top):

```python
from bom_compare.unified_bom import (  # noqa: F811 — extend the Task-1 import
    COL_NOTES,
    COL_SOURCE,
    COL_STATUS,
    STATUS_ADDED,
    STATUS_CHANGED,
    STATUS_DELETE,
    build_unified_bom,
)
from common import CancellationError


def _merge(old_rows, new_rows, **kwargs):
    """Shorthand: both files use a 'RefDes' key column unless overridden."""
    old_df = pd.DataFrame(old_rows)
    new_df = pd.DataFrame(new_rows)
    kwargs.setdefault("old_refdes_col", "RefDes")
    kwargs.setdefault("new_refdes_col", "RefDes")
    return build_unified_bom(old_df, new_df, **kwargs)


# ---------------------------------------------------------------------------
# Statuses, sources, styles
# ---------------------------------------------------------------------------

def test_added_row_is_green_and_noted():
    result = _merge(
        [{"RefDes": "R1", "Part Number": "PN-1"}],
        [{"RefDes": "R1", "Part Number": "PN-1"},
         {"RefDes": "R9", "Part Number": "PN-9"}],
    )
    frame = result.frame
    assert list(frame["RefDes"]) == ["R1", "R9"]
    added = frame.iloc[1]
    assert added[COL_STATUS] == STATUS_ADDED
    assert added[COL_SOURCE] == "New BOM only"
    assert "add to the FMEAs" in added[COL_NOTES]
    assert result.row_styles[1] == "success"
    assert result.counts["added"] == 1


def test_unchanged_row_has_no_status_and_source_both():
    result = _merge([{"RefDes": "R1"}], [{"RefDes": "R1"}])
    row = result.frame.iloc[0]
    assert row[COL_STATUS] == ""
    assert row[COL_SOURCE] == "Both"
    assert row[COL_NOTES] == ""
    assert result.row_styles[0] == ""
    assert result.counts["unchanged"] == 1


def test_deleted_row_inserted_inline_after_anchor():
    result = _merge(
        [{"RefDes": "R1"}, {"RefDes": "R99"}, {"RefDes": "R2"}],
        [{"RefDes": "R1"}, {"RefDes": "R2"}],
    )
    assert list(result.frame["RefDes"]) == ["R1", "R99", "R2"]
    row = result.frame.iloc[1]
    assert row[COL_STATUS] == STATUS_DELETE
    assert row[COL_SOURCE] == "Old BOM only"
    assert "remove from the FMEAs" in row[COL_NOTES]
    assert result.row_styles[1] == "error"
    assert result.counts["deleted"] == 1


def test_deleted_first_row_goes_to_top():
    result = _merge(
        [{"RefDes": "R99"}, {"RefDes": "R1"}],
        [{"RefDes": "R1"}],
    )
    assert list(result.frame["RefDes"]) == ["R99", "R1"]


def test_consecutive_deletions_keep_old_file_order():
    result = _merge(
        [{"RefDes": "R1"}, {"RefDes": "R97"}, {"RefDes": "R98"}, {"RefDes": "R99"}],
        [{"RefDes": "R1"}],
    )
    assert list(result.frame["RefDes"]) == ["R1", "R97", "R98", "R99"]


# ---------------------------------------------------------------------------
# Conflict rule
# ---------------------------------------------------------------------------

def test_changed_value_new_wins_and_noted():
    result = _merge(
        [{"RefDes": "R1", "Part Description": "RES 10K 1%"}],
        [{"RefDes": "R1", "Part Description": "RES 10.5K 1%"}],
    )
    row = result.frame.iloc[0]
    assert row["Part Description"] == "RES 10.5K 1%"
    assert row[COL_STATUS] == STATUS_CHANGED
    assert row[COL_SOURCE] == "Both"
    assert (
        'Part Description changed from "RES 10K 1%" to "RES 10.5K 1%"'
        in row[COL_NOTES]
    )
    assert result.row_styles[0] == "warning"
    assert result.counts["changed"] == 1
    # Value changes are the feature's point, not data-integrity warnings.
    assert result.warning_count == 0


def test_numeric_equivalent_values_are_not_changes():
    result = _merge(
        [{"RefDes": "R1", "Qty": 10}],
        [{"RefDes": "R1", "Qty": "10.0"}],
    )
    row = result.frame.iloc[0]
    assert row[COL_STATUS] == ""
    assert row[COL_NOTES] == ""


def test_blank_new_value_keeps_old_and_warns():
    result = _merge(
        [{"RefDes": "R1", "Part Description": "RES 10K"}],
        [{"RefDes": "R1", "Part Description": ""}],
    )
    row = result.frame.iloc[0]
    assert row["Part Description"] == "RES 10K"
    assert 'Part Description: kept old value "RES 10K" (new was blank)' in row[COL_NOTES]
    assert row[COL_STATUS] == STATUS_CHANGED
    assert result.warning_count == 1


def test_old_only_column_carries_manual_data_silently():
    result = _merge(
        [{"RefDes": "R1", "Sheet Number": "12"}],
        [{"RefDes": "R1"}],
    )
    row = result.frame.iloc[0]
    assert row["Sheet Number"] == "12"
    # Old-only column carry is expected behavior — no note, no status.
    assert row[COL_STATUS] == ""


# ---------------------------------------------------------------------------
# Duplicates, DNP, multi-token rows, empties, NaN, cancellation
# ---------------------------------------------------------------------------

def test_duplicate_new_refdes_first_wins_and_flagged():
    result = _merge(
        [{"RefDes": "R1", "Part Number": "PN-1"}],
        [{"RefDes": "R1", "Part Number": "PN-1"},
         {"RefDes": "R1", "Part Number": "PN-DUP"}],
    )
    dup = result.frame.iloc[1]
    assert "Duplicate RefDes R1" in dup[COL_NOTES]
    assert dup[COL_STATUS] == STATUS_CHANGED
    assert result.warning_count == 1


def test_dnp_old_only_row_not_emitted_as_delete():
    result = _merge(
        [{"RefDes": "R1", "Description": "Res"},
         {"RefDes": "R99", "Description": "DNP spare"}],
        [{"RefDes": "R1", "Description": "Res"}],
        old_desc_col="Description",
        ignore_dnp=True,
    )
    assert list(result.frame["RefDes"]) == ["R1"]
    assert result.counts["deleted"] == 0
    assert result.counts["dnp_skipped"] == 1


def test_dnp_old_only_row_emitted_when_ignore_dnp_off():
    result = _merge(
        [{"RefDes": "R1", "Description": "Res"},
         {"RefDes": "R99", "Description": "DNP spare"}],
        [{"RefDes": "R1", "Description": "Res"}],
        old_desc_col="Description",
        ignore_dnp=False,
    )
    assert list(result.frame["RefDes"]) == ["R1", "R99"]


def test_multi_token_old_row_partial_delete_names_origin():
    result = _merge(
        [{"RefDes": "R1, R2, R3", "Group": "CPU"}],
        [{"RefDes": "R1"}, {"RefDes": "R2"}],
    )
    # The old row survives via R1's match (entry 0), so its deleted token
    # anchors right after that backbone row.
    assert list(result.frame["RefDes"]) == ["R1", "R3", "R2"]
    deleted = result.frame.iloc[1]
    assert deleted[COL_STATUS] == STATUS_DELETE
    assert 'From an old row listing "R1, R2, R3"' in deleted[COL_NOTES]
    assert deleted["Group"] == "CPU"


def test_multi_token_new_row_mixed_status_is_changed():
    result = _merge(
        [{"RefDes": "R1", "Group": "CPU"}],
        [{"RefDes": "R1, R9", "Group": "CPU"}],
    )
    row = result.frame.iloc[0]
    assert row[COL_STATUS] == STATUS_CHANGED  # not Added: only R9 is new
    assert "R9 is not in Old BOM" in row[COL_NOTES]


def test_multi_token_new_row_all_new_is_added():
    result = _merge(
        [{"RefDes": "R1"}],
        [{"RefDes": "R8, R9"}],
    )
    assert result.frame.iloc[0][COL_STATUS] == STATUS_ADDED


def test_empty_new_file_emits_all_deletes():
    result = _merge([{"RefDes": "R1"}], [])
    assert list(result.frame["RefDes"]) == ["R1"]
    assert result.frame.iloc[0][COL_STATUS] == STATUS_DELETE


def test_empty_old_file_all_added():
    result = _merge([], [{"RefDes": "R1"}])
    assert result.frame.iloc[0][COL_STATUS] == STATUS_ADDED


def test_nan_refdes_cells_do_not_crash():
    result = _merge(
        [{"RefDes": None, "X": "1"}, {"RefDes": "R1", "X": "2"}],
        [{"RefDes": "R1", "X": "2"}, {"RefDes": float("nan"), "X": "3"}],
    )
    assert len(result.frame) == 2  # NaN old row has no tokens -> no delete


def test_summary_note_wording_and_counts():
    result = _merge(
        [{"RefDes": "R1"}, {"RefDes": "R99"}],
        [{"RefDes": "R1"}, {"RefDes": "R9"}],
    )
    assert result.counts["added"] == 1
    assert result.counts["deleted"] == 1
    note = result.notes[0]
    assert note.startswith("Unified BOM: ")
    assert "1 added" in note and "1 to delete" in note


def test_cancellation_via_stop_event():
    stop = threading.Event()
    stop.set()
    rows = [{"RefDes": f"R{i}"} for i in range(10)]
    with pytest.raises(CancellationError):
        build_unified_bom(
            pd.DataFrame(rows),
            pd.DataFrame(rows),
            old_refdes_col="RefDes",
            new_refdes_col="RefDes",
            stop_event=stop,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_unified_bom.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_unified_bom'`

- [ ] **Step 3: Implement `build_unified_bom`**

Append to `backend/python/bom_compare/unified_bom.py`. This is the complete core (Task 3 extends the two marked seams for carry-forward — they are already wired here so Task 3 only fills in `_collect_suffix_entries` / `_build_carried_rows`):

```python
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
    def log(msg: str) -> None:
        if log_callback:
            log_callback(msg)
        _logger.info(msg)

    old_df = old_df if old_df is not None else pd.DataFrame()
    new_df = new_df if new_df is not None else pd.DataFrame()

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
    try:
        dnp_re = re.compile(dnp_source, re.I)
    except re.error:
        dnp_re = re.compile(DEFAULT_DNP_REGEX, re.I)

    unified_cols, old_to_unified, tool_cols = _plan_columns(old_df, new_df, column_pairs)
    status_col = tool_cols["status"]
    source_col = tool_cols["source"]
    notes_col = tool_cols["notes"]

    # str(name) -> actual column object, so numeric Excel headers survive.
    old_col_by_name = {str(c): c for c in old_df.columns}
    new_col_by_name = {str(c): c for c in new_df.columns}
    new_cols_set = set(new_col_by_name)

    # The column Delete/Carried rows write their RefDes token into: the
    # new file's key column when it exists, else the old key's target.
    refdes_out_col = (
        str(new_refdes_col)
        if str(new_refdes_col) in unified_cols
        else old_to_unified.get(str(old_refdes_col), str(old_refdes_col))
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
    for idx in range(len(old_df)):
        check_cancel(idx)
        tokens = _row_tokens(old_df.iloc[idx][old_refdes_col])
        old_tokens_by_row.append(tokens)
        for tok in tokens:
            if tok in old_first_row_for_token:
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
    # Row builders
    # ------------------------------------------------------------------
    def blank_row() -> Dict[str, Any]:
        return {c: "" for c in unified_cols}

    def build_matched_row(
        new_idx: int, token_to_old_row: Dict[str, int]
    ) -> Tuple[Dict[str, Any], List[str], int]:
        """New row's values merged with its matched old row(s).

        Returns (values, notes, integrity_flags). New values win; a blank
        new cell keeps the old value (flagged); old-only columns carry
        silently. Multi-token rows diff against every distinct matched old
        row, prefixing notes with the tokens each row covers.
        """
        values = blank_row()
        row = new_df.iloc[new_idx]
        for name, col in new_col_by_name.items():
            if not _is_blank(row[col]):
                values[name] = row[col]

        notes: List[str] = []
        flags = 0
        rows_to_tokens: Dict[int, List[str]] = {}
        for tok, old_idx in token_to_old_row.items():
            rows_to_tokens.setdefault(old_idx, []).append(tok)
        multi = len(rows_to_tokens) > 1
        for old_idx in sorted(rows_to_tokens):
            prefix = f"[{', '.join(sorted(rows_to_tokens[old_idx]))}] " if multi else ""
            old_row = old_df.iloc[old_idx]
            for old_name, uni_col in old_to_unified.items():
                # The key columns define matching; their textual difference
                # (multi-token cells, formatting) is already expressed by
                # the row statuses — never diff or blank-keep them.
                if old_name == str(old_refdes_col) or uni_col == str(new_refdes_col):
                    continue
                old_val = old_row[old_col_by_name[old_name]]
                if _is_blank(old_val):
                    continue
                current = values.get(uni_col, "")
                if uni_col in new_cols_set:
                    new_val = row[new_col_by_name[uni_col]]
                    if _is_blank(new_val):
                        if _is_blank(current):
                            values[uni_col] = old_val
                            notes.append(
                                f'{prefix}{uni_col}: kept old value '
                                f'"{_cell_text(old_val)}" (new was blank)'
                            )
                            flags += 1
                        elif not _values_equal(current, old_val):
                            notes.append(
                                f'{prefix}{uni_col}: differing old values — '
                                f'kept "{_cell_text(current)}"'
                            )
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
        return values, notes, flags

    def fill_row_from_old(old_idx: int) -> Dict[str, Any]:
        """A row built purely from an old row (Delete / Carried rows)."""
        values = blank_row()
        old_row = old_df.iloc[old_idx]
        for old_name, uni_col in old_to_unified.items():
            val = old_row[old_col_by_name[old_name]]
            if not _is_blank(val):
                values[uni_col] = val
        return values

    # Task 3 fills these two in; the core treats "no suffix entries" as
    # "no supersession" so Task 2 is complete without them.
    def _collect_suffix_entries(tokens: List[str]) -> List[Tuple[int, str]]:
        return []

    def _build_carried_rows(
        bare_new_idx: int, suffix_entries: List[Tuple[int, str]]
    ) -> Tuple[List[Tuple[Dict[str, Any], List[str]]], int]:
        return [], 0

    # ------------------------------------------------------------------
    # Backbone emission: every new-file row, in order.
    # ------------------------------------------------------------------
    entries: List[Tuple[Dict[str, Any], str, str, List[str]]] = []
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

        suffix_entries = _collect_suffix_entries(tokens)

        values, notes, flags = build_matched_row(new_idx, token_to_old_row)
        warning_flags += flags + len(dup_notes)
        notes = dup_notes + notes

        added_tokens = [t for t in tokens if t not in old_first_row_for_token]
        matched_any = bool(token_to_old_row)

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
                source = src_both if matched_any else src_new_only
                counts["changed"] += 1
            else:
                status = ""
                source = src_both if matched_any else src_new_only
                counts["unchanged"] += 1

        entry_idx = len(entries)
        entries.append((values, status, source, notes))
        for old_idx in set(token_to_old_row.values()):
            consumed_old_rows.setdefault(old_idx, entry_idx)

        if suffix_entries:
            carried_rows, cflags = _build_carried_rows(new_idx, suffix_entries)
            warning_flags += cflags
            for (cvalues, cnotes), (old_idx, tok) in zip(carried_rows, suffix_entries):
                carried_tokens.add(tok)
                centry_idx = len(entries)
                entries.append((cvalues, STATUS_CARRIED, src_carried, cnotes))
                consumed_old_rows.setdefault(old_idx, centry_idx)
                counts["carried"] += 1

    # ------------------------------------------------------------------
    # Deletion pass: old-only tokens, inserted inline after their anchor.
    # ------------------------------------------------------------------
    def old_row_is_dnp(old_idx: int) -> bool:
        if not ignore_dnp:
            return False
        row = old_df.iloc[old_idx]
        text = _cell_text(row[old_refdes_col])
        if old_desc_col and old_desc_col in old_df.columns:
            text = f"{text} {_cell_text(row[old_desc_col])}"
        return bool(dnp_re.search(text))

    insertions: Dict[int, List[Tuple[Dict[str, Any], str, str, List[str]]]] = {}
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
        if old_row_is_dnp(old_idx):
            dnp_skipped += len(deleted_tokens)
            continue
        original_cell = _cell_text(old_df.iloc[old_idx][old_refdes_col])
        multi = len(tokens) > 1
        bucket = insertions.setdefault(anchor, [])
        for tok in deleted_tokens:
            values = fill_row_from_old(old_idx)
            values[refdes_out_col] = tok
            base = get_usage_base_refdes(tok)
            if tok != base and base in new_all_tokens:
                # The base exists in the new file but inside a multi-RefDes
                # row, so the suffix carry could not trigger — flag loudly
                # instead of silently deleting manual data.
                note = (
                    f"{tok} is not in {new_label}, but its base {base} is — "
                    f"manual expansion was not auto-carried; review before deleting"
                )
            else:
                note = f"Not in {new_label} — remove from the FMEAs"
            row_notes = [note]
            if multi:
                row_notes.append(f'From an old row listing "{original_cell}"')
            bucket.append((values, STATUS_DELETE, src_old_only, row_notes))
            counts["deleted"] += 1

    # ------------------------------------------------------------------
    # Assembly
    # ------------------------------------------------------------------
    final_rows: List[Dict[str, Any]] = []
    row_styles: List[str] = []

    def emit(entry: Tuple[Dict[str, Any], str, str, List[str]]) -> None:
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_unified_bom.py -v`
Expected: PASS (all Task-1 + Task-2 tests)

- [ ] **Step 5: Commit**

```powershell
git add backend/python/bom_compare/unified_bom.py backend/tests/test_unified_bom.py
git commit -m "BOM Compare: Add unified-BOM core merge (statuses, inline deletes)"
```

---

### Task 3: Suffix/pin carry-forward, supersession, uniform-column rule

**Files:**
- Modify: `backend/python/bom_compare/unified_bom.py` (replace the two Task-2 seam stubs)
- Test: `backend/tests/test_unified_bom.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_unified_bom.py` (extend the import with `STATUS_CARRIED, STATUS_SUPERSEDED`):

```python
from bom_compare.unified_bom import STATUS_CARRIED, STATUS_SUPERSEDED  # noqa: F811


def test_suffix_carry_forward_supersedes_bare_row():
    result = _merge(
        [{"RefDes": "U2000-1", "Part Number": "PN-123", "Sheet Number": "5"},
         {"RefDes": "U2000-2", "Part Number": "PN-123", "Sheet Number": "6"}],
        [{"RefDes": "U2000", "Part Number": "PN-123"}],
    )
    frame = result.frame
    assert list(frame["RefDes"]) == ["U2000", "U2000-1", "U2000-2"]
    bare = frame.iloc[0]
    assert bare[COL_STATUS] == STATUS_SUPERSEDED
    assert bare[COL_SOURCE] == "New BOM (superseded)"
    assert (
        "Superseded by 2 carried rows (U2000-1 … U2000-2) — delete this row"
        in bare[COL_NOTES]
    )
    assert result.row_styles[0] == "highlight"
    for i in (1, 2):
        assert frame.iloc[i][COL_STATUS] == STATUS_CARRIED
        assert frame.iloc[i][COL_SOURCE] == "Old BOM (carried)"
        assert result.row_styles[i] == "warning"
    # Per-suffix manual data survives verbatim.
    assert frame.iloc[1]["Sheet Number"] == "5"
    assert frame.iloc[2]["Sheet Number"] == "6"
    assert result.counts["superseded"] == 1
    assert result.counts["carried"] == 2
    # Nothing was deleted — the suffix rows were carried, not dropped.
    assert result.counts["deleted"] == 0


def test_pin_style_rows_carry_exactly_like_suffix_rows():
    result = _merge(
        [{"RefDes": "J4-P1", "Signal": "GND"},
         {"RefDes": "J4-20", "Signal": "VCC"}],
        [{"RefDes": "J4"}],
    )
    frame = result.frame
    assert list(frame["RefDes"]) == ["J4", "J4-P1", "J4-20"]
    assert frame.iloc[0][COL_STATUS] == STATUS_SUPERSEDED
    assert frame.iloc[1][COL_STATUS] == STATUS_CARRIED
    assert frame.iloc[1]["Signal"] == "GND"
    assert frame.iloc[2]["Signal"] == "VCC"


def test_uniform_column_rule_updates_pn_but_not_per_row_data():
    result = _merge(
        [{"RefDes": "U2000-1", "Part Number": "123-456", "Sheet Number": "5"},
         {"RefDes": "U2000-2", "Part Number": "123-456", "Sheet Number": "6"}],
        [{"RefDes": "U2000", "Part Number": "123-789", "Sheet Number": "9"}],
    )
    frame = result.frame
    carried = frame.iloc[1:3]
    # Uniform across the old group -> the new value wins, flagged.
    assert list(carried["Part Number"]) == ["123-789", "123-789"]
    assert (
        'Part Number updated from "123-456" to "123-789" by New BOM'
        in frame.iloc[1][COL_NOTES]
    )
    # Varying per suffix row -> manual data, never touched.
    assert list(carried["Sheet Number"]) == ["5", "6"]
    # One flagged overwrite, counted once per column (not per row).
    assert result.warning_count == 1


def test_blank_new_value_never_overwrites_carried_rows():
    result = _merge(
        [{"RefDes": "U1-1", "Part Number": "PN-A"},
         {"RefDes": "U1-2", "Part Number": "PN-A"}],
        [{"RefDes": "U1", "Part Number": ""}],
    )
    carried = result.frame.iloc[1:3]
    assert list(carried["Part Number"]) == ["PN-A", "PN-A"]


def test_new_only_columns_fill_carried_rows_from_bare_row():
    result = _merge(
        [{"RefDes": "U1-1", "Part Number": "PN-A"},
         {"RefDes": "U1-2", "Part Number": "PN-A"}],
        [{"RefDes": "U1", "Part Number": "PN-A", "Supplier": "ACME"}],
    )
    carried = result.frame.iloc[1:3]
    assert list(carried["Supplier"]) == ["ACME", "ACME"]


def test_old_bare_and_suffix_rows_supersession_still_wins():
    result = _merge(
        [{"RefDes": "U1", "Part Number": "PN-A"},
         {"RefDes": "U1-1", "Part Number": "PN-A"}],
        [{"RefDes": "U1", "Part Number": "PN-A"}],
    )
    frame = result.frame
    assert list(frame["RefDes"]) == ["U1", "U1-1"]
    assert frame.iloc[0][COL_STATUS] == STATUS_SUPERSEDED
    assert frame.iloc[1][COL_STATUS] == STATUS_CARRIED


def test_suffixes_present_in_both_files_match_exactly():
    result = _merge(
        [{"RefDes": "U1-1"}, {"RefDes": "U1-2"}],
        [{"RefDes": "U1-1"}, {"RefDes": "U1-2"}],
    )
    assert list(result.frame[COL_STATUS]) == ["", ""]
    assert result.counts["carried"] == 0


def test_carry_skips_suffixes_the_new_file_already_lists():
    result = _merge(
        [{"RefDes": "U1-1", "Sheet Number": "5"},
         {"RefDes": "U1-2", "Sheet Number": "6"}],
        [{"RefDes": "U1"},
         {"RefDes": "U1-1", "Sheet Number": "50"}],
    )
    frame = result.frame
    # U1-2 is carried under the bare row; U1-1 exact-matches its own new row.
    assert list(frame["RefDes"]) == ["U1", "U1-2", "U1-1"]
    assert frame.iloc[0][COL_STATUS] == STATUS_SUPERSEDED
    assert frame.iloc[1][COL_STATUS] == STATUS_CARRIED
    assert frame.iloc[2][COL_STATUS] == STATUS_CHANGED  # 5 -> 50 noted
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_unified_bom.py -v`
Expected: the new tests FAIL (bare rows come out as Added/unchanged because the seams return empty), Task-1/2 tests still PASS.

- [ ] **Step 3: Replace the two seam stubs**

In `build_unified_bom`, replace the stub `_collect_suffix_entries` and `_build_carried_rows` (defined just above the backbone loop) with:

```python
    def _collect_suffix_entries(tokens: List[str]) -> List[Tuple[int, str]]:
        """Old suffix/pin rows superseding a single bare new token.

        Triggers only for a single-token row whose token IS its own usage
        base (a bare RefDes). Suffix tokens the new file lists itself are
        excluded — those exact-match their own backbone rows instead.
        """
        if len(tokens) != 1:
            return []
        tok = tokens[0]
        if get_usage_base_refdes(tok) != tok:
            return []
        return [
            (r, t)
            for (r, t) in old_suffix_rows_for_base.get(tok, [])
            if t not in new_all_tokens
        ]

    def _build_carried_rows(
        bare_new_idx: int, suffix_entries: List[Tuple[int, str]]
    ) -> Tuple[List[Tuple[Dict[str, Any], List[str]]], int]:
        """Carried suffix rows for one superseded bare row.

        Old data is kept verbatim. The bare new row's values overwrite a
        shared column ONLY when every carried row agrees on that column
        (uniform-column rule: uniform = inherited from the base part;
        varying = per-suffix manual data) AND the new value is non-blank
        and differs — each such overwrite is flagged once per column.
        New-only columns are filled from the bare row (pure addition).
        """
        bare_row = new_df.iloc[bare_new_idx]
        flags = 0

        overwrite: Dict[str, Tuple[str, str]] = {}  # uni_col -> (old, new) text
        for old_name, uni_col in old_to_unified.items():
            if uni_col not in new_cols_set:
                continue
            new_val = bare_row[new_col_by_name[uni_col]]
            if _is_blank(new_val):
                continue
            group_vals = [
                old_df.iloc[i][old_col_by_name[old_name]] for i, _t in suffix_entries
            ]
            uniform = all(_values_equal(v, group_vals[0]) for v in group_vals[1:])
            if uniform and not _values_equal(group_vals[0], new_val):
                overwrite[uni_col] = (_cell_text(group_vals[0]), _cell_text(new_val))
                flags += 1

        rows: List[Tuple[Dict[str, Any], List[str]]] = []
        for old_idx, tok in suffix_entries:
            values = fill_row_from_old(old_idx)
            # New-only columns inherit the bare row's data (pure addition —
            # the old file had no such column to disagree with).
            for name, col in new_col_by_name.items():
                if _is_blank(values.get(name, "")) and not _is_blank(bare_row[col]):
                    values[name] = bare_row[col]
            # The key column always shows the carried token itself.
            values[refdes_out_col] = tok
            row_notes = [
                f"Carried forward from {old_label} "
                f"(manual suffix row of {get_usage_base_refdes(tok)})"
            ]
            for uni_col, (old_text, new_text) in overwrite.items():
                values[uni_col] = bare_row[new_col_by_name[uni_col]]
                row_notes.append(
                    f'{uni_col} updated from "{old_text}" to "{new_text}" '
                    f'by {new_label}'
                )
            rows.append((values, row_notes))
        return rows, flags
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_unified_bom.py -v`
Expected: PASS (all tests so far)

- [ ] **Step 5: Commit**

```powershell
git add backend/python/bom_compare/unified_bom.py backend/tests/test_unified_bom.py
git commit -m "BOM Compare: Add suffix/pin carry-forward with supersession"
```

---

### Task 4: Styled sheet writer + facade re-export

**Files:**
- Modify: `backend/python/bom_compare/unified_bom.py`, `backend/python/bom_compare/bom_compare_logic.py`
- Test: `backend/tests/test_unified_bom.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_unified_bom.py`:

```python
from openpyxl import Workbook, load_workbook  # add to the file's imports

from bom_compare.unified_bom import (  # noqa: F811
    SHEET_UNIFIED,
    write_unified_bom_sheet,
)


def test_write_unified_bom_sheet_styles_and_layout(tmp_path):
    result = _merge(
        [{"RefDes": "R1", "Part Description": "RES 10K"},
         {"RefDes": "R99", "Part Description": "OLD ONLY"},
         {"RefDes": "U1-1", "Part Description": "SECTION"}],
        [{"RefDes": "R1", "Part Description": "RES 12K"},
         {"RefDes": "R5", "Part Description": "NEW PART"},
         {"RefDes": "U1", "Part Description": "SECTION"}],
    )
    wb = Workbook()
    write_unified_bom_sheet(wb, result)
    out = tmp_path / "unified.xlsx"
    wb.save(out)

    read = load_workbook(out)
    assert SHEET_UNIFIED in read.sheetnames
    ws = read[SHEET_UNIFIED]
    assert ws.freeze_panes == "A2"
    assert ws.auto_filter.ref is not None

    headers = [c.value for c in ws[1]]
    status_idx = headers.index(COL_STATUS) + 1
    fills_by_status = {}
    for row_idx in range(2, ws.max_row + 1):
        status = ws.cell(row=row_idx, column=status_idx).value
        if status:
            fills_by_status[status] = str(
                ws.cell(row=row_idx, column=1).fill.start_color.rgb
            )
    assert fills_by_status[STATUS_CHANGED].endswith("FFEB9C")   # yellow
    assert fills_by_status[STATUS_ADDED].endswith("C6EFCE")     # green
    assert fills_by_status[STATUS_DELETE].endswith("FFC7CE")    # red
    assert fills_by_status[STATUS_SUPERSEDED].endswith("BDD7EE")  # blue
    assert fills_by_status[STATUS_CARRIED].endswith("FFEB9C")   # yellow


def test_write_unified_bom_sheet_empty_frame_headers_only():
    result = build_unified_bom(
        pd.DataFrame(), pd.DataFrame(),
        old_refdes_col="RefDes", new_refdes_col="RefDes",
    )
    wb = Workbook()
    write_unified_bom_sheet(wb, result)
    ws = wb[SHEET_UNIFIED]
    assert ws.freeze_panes == "A2"


def test_facade_reexports_unified_names():
    from bom_compare import bom_compare_logic
    assert bom_compare_logic.build_unified_bom is build_unified_bom
    assert bom_compare_logic.SHEET_UNIFIED == SHEET_UNIFIED
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_unified_bom.py -v`
Expected: FAIL with `ImportError: cannot import name 'write_unified_bom_sheet'`

- [ ] **Step 3: Implement the writer**

Append to `backend/python/bom_compare/unified_bom.py`:

```python
def write_unified_bom_sheet(wb, unified: UnifiedBomResult, presets=None) -> None:
    """Append the styled Unified BOM tab to an open workbook.

    The caller owns the workbook lifecycle (atomic write + verify),
    matching write_extraction_compare_excel.
    """
    from common.excel_styles import (
        PRESETS,
        style_header_only,
        style_worksheet,
        write_df_to_sheet,
    )

    presets = presets or PRESETS
    ws = wb.create_sheet(SHEET_UNIFIED)
    write_df_to_sheet(ws, unified.frame)
    if unified.frame.empty:
        style_header_only(ws, len(unified.frame.columns), presets)
        return
    styles = unified.row_styles
    style_worksheet(
        ws,
        unified.frame,
        presets=presets,
        row_style_func=lambda _row, i: styles[i] if 0 <= i < len(styles) else "default",
        max_width=60,
    )
```

- [ ] **Step 4: Add the facade re-export**

In `backend/python/bom_compare/bom_compare_logic.py`, after the `from .excel_export import (...)` block at the bottom, add:

```python
from .unified_bom import (  # noqa: E402
    SHEET_UNIFIED,
    UnifiedBomResult,
    build_unified_bom,
    write_unified_bom_sheet,
)
```

(`unified_bom` itself imports only `DEFAULT_DNP_REGEX` from `bom_compare_logic`, which is defined at line ~89 — well before this re-export block — so the partial-module import is safe, same as `custom_compare` line 51.)

- [ ] **Step 5: Run tests to verify they pass, then commit**

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/test_unified_bom.py backend/tests/test_bom_compare_logic.py -q
git add backend/python/bom_compare/unified_bom.py backend/python/bom_compare/bom_compare_logic.py backend/tests/test_unified_bom.py
git commit -m "BOM Compare: Add styled Unified BOM sheet writer"
```
Expected: all green (`test_bom_compare_logic.py` proves the facade change broke nothing).

---

### Task 5: Group + Custom writers accept the unified result

**Files:**
- Modify: `backend/python/bom_compare/group_analysis.py` (`write_excel_report`, line ~943)
- Modify: `backend/python/bom_compare/excel_export.py` (`write_bom_compare_excel`, line ~68)
- Test: `backend/tests/test_unified_bom.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_unified_bom.py`:

```python
def test_group_report_includes_unified_tab(tmp_path):
    from bom_compare.bom_compare_logic import AnalyzeResults, write_excel_report

    unified = _merge([{"RefDes": "R1"}], [{"RefDes": "R1"}])
    results = AnalyzeResults(
        summary=pd.DataFrame([("Files", "2")], columns=["Item", "Value"])
    )
    out = tmp_path / "group.xlsx"
    write_excel_report(results, str(out), unified=unified)
    assert SHEET_UNIFIED in load_workbook(out).sheetnames


def test_group_report_without_unified_is_unchanged(tmp_path):
    from bom_compare.bom_compare_logic import AnalyzeResults, write_excel_report

    results = AnalyzeResults(
        summary=pd.DataFrame([("Files", "2")], columns=["Item", "Value"])
    )
    out = tmp_path / "group_plain.xlsx"
    write_excel_report(results, str(out))
    assert SHEET_UNIFIED not in load_workbook(out).sheetnames


def test_custom_report_includes_unified_tab(tmp_path):
    from bom_compare.bom_compare_logic import BomCompareResult, write_bom_compare_excel

    unified = _merge([{"RefDes": "R1"}], [{"RefDes": "R1"}])
    out = tmp_path / "custom.xlsx"
    write_bom_compare_excel(BomCompareResult(), str(out), unified=unified)
    assert SHEET_UNIFIED in load_workbook(out).sheetnames


def test_custom_report_without_unified_is_unchanged(tmp_path):
    from bom_compare.bom_compare_logic import BomCompareResult, write_bom_compare_excel

    out = tmp_path / "custom_plain.xlsx"
    write_bom_compare_excel(BomCompareResult(), str(out))
    assert SHEET_UNIFIED not in load_workbook(out).sheetnames
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_unified_bom.py -v -k "report"`
Expected: FAIL with `TypeError: write_excel_report() got an unexpected keyword argument 'unified'`

- [ ] **Step 3: Add the optional parameter to both writers**

`backend/python/bom_compare/group_analysis.py` — change the signature and the save line of `write_excel_report`:

```python
def write_excel_report(results: AnalyzeResults, output_path: str, unified=None) -> None:
```

and immediately before `wb.save(output_path)` at the end of the function:

```python
    if unified is not None:
        # Lazy import keeps the module graph acyclic (unified_bom imports
        # from bom_compare_logic, which re-exports this module).
        from .unified_bom import write_unified_bom_sheet
        write_unified_bom_sheet(wb, unified)

    wb.save(output_path)
```

`backend/python/bom_compare/excel_export.py` — change the signature of `write_bom_compare_excel`:

```python
def write_bom_compare_excel(
    result: BomCompareResult,
    filename: str,
    bom_a_name: str = "BOM A",
    bom_b_name: str = "BOM B",
    unified=None,
) -> None:
```

and immediately before `wb.save(filename)` at the end:

```python
    if unified is not None:
        from .unified_bom import write_unified_bom_sheet
        write_unified_bom_sheet(wb, unified)

    wb.save(filename)
```

- [ ] **Step 4: Run tests to verify they pass, then commit**

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/test_unified_bom.py backend/tests/test_bom_compare_logic.py backend/tests/test_bom_compare_runtime.py -q
git add backend/python/bom_compare/group_analysis.py backend/python/bom_compare/excel_export.py backend/tests/test_unified_bom.py
git commit -m "BOM Compare: Write Unified BOM tab from group/custom writers"
```

---

### Task 6: Runtime wiring + validate-time rejection

**Files:**
- Modify: `backend/python/bom_compare/runtime.py`
- Test: `backend/tests/test_bom_compare_runtime.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_bom_compare_runtime.py` (add `from openpyxl import load_workbook` to the file's imports):

```python
# ---------------------------------------------------------------------------
# Unified BOM option wiring (2026-08-13 feature)
# ---------------------------------------------------------------------------

def test_group_run_with_unified_bom_adds_tab_and_notes(tmp_path: Path) -> None:
    body = _build_group_body(tmp_path, options={
        "ignore_dnp": True,
        "create_unified_bom": True,
        "unified_newer_file": "file2",
    })
    result = bom_runtime.execute_run_request(body)
    assert result["status"] == "success"
    wb = load_workbook(result["output_file"])
    assert "Unified BOM" in wb.sheetnames
    assert any(str(n).startswith("Unified BOM:") for n in result["notes"])


def test_group_run_without_option_has_no_unified_tab(tmp_path: Path) -> None:
    body = _build_group_body(tmp_path)
    result = bom_runtime.execute_run_request(body)
    wb = load_workbook(result["output_file"])
    assert "Unified BOM" not in wb.sheetnames


def _build_custom_unified_body(tmp_path: Path) -> dict:
    """Old BOM (File 1) carries manual U2000 suffix rows; new BOM (File 2)
    has only the bare U2000 — the classic carry-forward scenario."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    old_path = tmp_path / "old_bom.xlsx"
    new_path = tmp_path / "new_bom.xlsx"
    pd.DataFrame([
        {"Reference Designator": "U2000-1", "Part Number": "PN-1", "Sheet Number": 5},
        {"Reference Designator": "U2000-2", "Part Number": "PN-1", "Sheet Number": 6},
    ]).to_excel(old_path, index=False)
    pd.DataFrame([
        {"Reference Designator": "U2000", "Part Number": "PN-2"},
    ]).to_excel(new_path, index=False)
    return {
        "workflowId": "bom_compare_custom",
        "outputStrategyId": "new_workbook_standard",
        "outputDirectory": str(tmp_path),
        "inputs": [
            _input_state("bomA", "File 1", old_path),
            _input_state("bomB", "File 2", new_path),
        ],
        "mappings": [
            {"canonical": "refdes_col_a", "mappedTo": "Reference Designator", "status": "mapped"},
            {"canonical": "refdes_col_b", "mappedTo": "Reference Designator", "status": "mapped"},
        ],
        "options": {
            "create_unified_bom": True,
            "unified_newer_file": "file2",
        },
    }


def test_custom_run_unified_carries_suffix_rows(tmp_path: Path) -> None:
    body = _build_custom_unified_body(tmp_path)
    result = bom_runtime.execute_run_request(body)
    assert result["status"] == "success"
    wb = load_workbook(result["output_file"])
    ws = wb["Unified BOM"]
    refdes = [ws.cell(row=r, column=1).value for r in range(2, ws.max_row + 1)]
    assert refdes == ["U2000", "U2000-1", "U2000-2"]
    # PN-1 -> PN-2 is a uniform-column overwrite on the carried rows: it
    # must qualify the run's warning_count.
    assert result["warning_count"] >= 1


def test_validate_rejects_bad_unified_newer_file(tmp_path: Path) -> None:
    body = _build_group_body(tmp_path, options={
        "create_unified_bom": True,
        "unified_newer_file": "banana",
    })
    result = bom_runtime.validate_run_request(body)
    assert result["ok"] is False
    assert result["reason_code"] == "invalid_unified_newer_file"


def test_validate_ignores_newer_file_when_option_off(tmp_path: Path) -> None:
    body = _build_group_body(tmp_path, options={"unified_newer_file": "banana"})
    result = bom_runtime.validate_run_request(body)
    assert result["ok"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_bom_compare_runtime.py -v -k "unified"`
Expected: the tab/notes/reason-code assertions FAIL (option is silently ignored today).

- [ ] **Step 3: Wire the runtime**

All edits in `backend/python/bom_compare/runtime.py`.

**(a)** Extend the facade import (line ~31) with the new names:

```python
from bom_compare.bom_compare_logic import (
    ColumnMapping,
    AnalyzeOptions,
    AnalyzeResults,
    BomCompareResult,
    DEFAULT_DNP_REGEX,
    analyze,
    write_excel_report,
    compare_two_boms,
    write_bom_compare_excel,
    build_unified_bom,
)
```

**(b)** Add a module-level helper below `_build_output_name`:

```python
_UNIFIED_WORKFLOWS = {"bom_compare_group", "bom_compare_custom"}


def _unified_newer_file(options: dict[str, Any]) -> str:
    """Normalized picker value; validate_run_request guarantees validity."""
    return str(options.get("unified_newer_file", "file2")).strip().lower() or "file2"
```

**(c)** In `validate_run_request`, right after the `if workflow_id not in SUPPORTED_WORKFLOWS:` block (line ~270), add:

```python
    # Unified BOM (2026-08-13): the newer-file picker must carry a known
    # slot value. Checked only when the option is on and only for the two
    # workflows that offer it (extraction never sends these keys).
    options = body.get("options") or {}
    if (
        result.ok
        and workflow_id in _UNIFIED_WORKFLOWS
        and options.get("create_unified_bom")
    ):
        if _unified_newer_file(options) not in {"file1", "file2"}:
            result = type(result)(
                ok=False,
                reason_code="invalid_unified_newer_file",
                toast_text=(
                    "Unified BOM: choose which file is the newer BOM "
                    "(File 1 or File 2)."
                ),
                affected_labels=result.affected_labels,
            )
```

**(d)** In `_run_group_compare`, after `emit_progress("Running comparison", "Comparison finished.", 80)` (line ~507) and before the "Writing workbook" status, add:

```python
    unified = None
    if options.get("create_unified_bom", False):
        emit_status("running", "Building unified BOM", "Merging old and new BOMs...")
        emit_progress("Building unified BOM", "Merging...", 82)
        # UI slot convention: file1 = grouping slot, file2 = BOM slot.
        if _unified_newer_file(options) == "file1":
            new_args = (group_df, mapping.grouping_refdes_col, grouping_label or "Grouping file")
            old_args = (bom_df, mapping.bom_refdes_col, bom_label or "BOM")
            old_desc = mapping.bom_desc_col
        else:
            new_args = (bom_df, mapping.bom_refdes_col, bom_label or "BOM")
            old_args = (group_df, mapping.grouping_refdes_col, grouping_label or "Grouping file")
            old_desc = None
        unified = build_unified_bom(
            old_args[0], new_args[0],
            old_refdes_col=old_args[1],
            new_refdes_col=new_args[1],
            old_label=old_args[2],
            new_label=new_args[2],
            ignore_dnp=analyze_options.ignore_dnp,
            dnp_regex=analyze_options.dnp_regex,
            old_desc_col=old_desc,
            stop_event=bridge.stop_event,
            log_callback=log,
        )
        emit_progress("Building unified BOM", "Unified BOM built.", 84)
```

Then pass it to the writer (line ~516): `write_excel_report(results, str(tmp_output), unified=unified)`.

Finally, replace the tail of `_run_group_compare` (the `warning_count` line and return dict) with:

```python
    warning_count = len(results.description_warnings) + len(results.fmr_warnings) + len(results.part_usage_warnings)
    notes = [
        f"Group vs BOM mode: compared {grouping_label or 'grouping file'} against {bom_label or 'BOM'}.",
    ]
    if unified is not None:
        warning_count += unified.warning_count
        notes.extend(unified.notes)

    return {
        "status": "success",
        "title": "BOM comparison complete",
        "summary": f"Group vs BOM: {missing_count} missing, {extra_count} extra.",
        "output_file": str(output_path),
        "primary_metric": f"{missing_count} missing in BOM",
        "secondary_metric": f"{warning_count} warnings",
        "notes": notes,
        "row_count": missing_count + extra_count,
        "warning_count": warning_count,
        "no_match_count": missing_count,
    }
```

**(e)** In `_run_custom_compare`, after `emit_progress("Comparing entries", "Comparison finished.", 80)` (line ~735), add:

```python
    unified = None
    if options.get("create_unified_bom", False):
        emit_status("running", "Building unified BOM", "Merging old and new BOMs...")
        emit_progress("Building unified BOM", "Merging...", 82)
        # UI slot convention: file1 = File 1 (bomA), file2 = File 2 (bomB).
        # compare_columns pairs are (col_a, col_b); orient them old->new.
        if _unified_newer_file(options) == "file1":
            old_bom, old_ref, old_lbl = bom_b_df, refdes_col_b, name_b
            new_bom, new_ref, new_lbl = bom_a_df, refdes_col_a, name_a
            pairs = [(b, a) for (a, b, _rule) in compare_columns]
        else:
            old_bom, old_ref, old_lbl = bom_a_df, refdes_col_a, name_a
            new_bom, new_ref, new_lbl = bom_b_df, refdes_col_b, name_b
            pairs = [(a, b) for (a, b, _rule) in compare_columns]
        unified = build_unified_bom(
            old_bom, new_bom,
            old_refdes_col=old_ref,
            new_refdes_col=new_ref,
            old_label=old_lbl,
            new_label=new_lbl,
            column_pairs=pairs or None,
            ignore_dnp=options.get("ignore_dnp", True),
            dnp_regex=options.get("dnp_regex") or None,
            stop_event=bridge.stop_event,
            log_callback=log,
        )
        emit_progress("Building unified BOM", "Unified BOM built.", 84)
```

Then pass it to the writer (line ~741): `write_bom_compare_excel(result, str(tmp_output), bom_a_name=name_a, bom_b_name=name_b, unified=unified)`.

And extend the custom return-dict tail, mirroring (d):

```python
    warning_count = (
        len(result.part_usage_warnings)
        + len(result.scope_warnings)
        + len(result.fmr_warnings)
    )
    notes = [
        f"Custom Compare mode: compared {name_a} against {name_b}.",
    ]
    if unified is not None:
        warning_count += unified.warning_count
        notes.extend(unified.notes)
```
…and use `"notes": notes` in the return dict (leave every other key as-is).

- [ ] **Step 4: Run the runtime + logic suites, then commit**

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/test_bom_compare_runtime.py backend/tests/test_unified_bom.py backend/tests/test_bom_compare_logic.py backend/tests/test_extraction_compare.py -q
git add backend/python/bom_compare/runtime.py backend/tests/test_bom_compare_runtime.py
git commit -m "BOM Compare: Wire create_unified_bom options through runtime"
```
Expected: all green, including the pre-existing runtime tests (proves default runs are byte-identical in behavior).

---

### Task 7: Frontend — checkbox, newer-file picker, payload

**Files:**
- Modify: `frontend/src/features/bom-compare/BomCompareTool.tsx`
- Test: `frontend/src/features/bom-compare/BomCompareTool.test.tsx`

- [ ] **Step 1: Write the failing tests**

Append a new describe block to `frontend/src/features/bom-compare/BomCompareTool.test.tsx`:

```tsx
describe("Create Unified BOM option", () => {
  it("renders the checkbox and reveals the newer-file picker when checked", async () => {
    const user = userEvent.setup();
    render(<BomCompareTool />);

    const checkbox = screen.getByRole("checkbox", { name: /^Create Unified BOM/ });
    expect(checkbox).toBeEnabled();
    expect(
      screen.queryByText("Newer BOM (merge wins conflicts)"),
    ).not.toBeInTheDocument();

    await user.click(checkbox);
    expect(
      screen.getByText("Newer BOM (merge wins conflicts)"),
    ).toBeInTheDocument();
  });

  it("omits unified_newer_file when the option is off", async () => {
    const user = userEvent.setup();
    render(<BomCompareTool />);
    await user.click(screen.getByRole("button", { name: "Compare" }));

    await waitFor(() => expect(backendMocks.executeRun).toHaveBeenCalledTimes(1));
    const request = backendMocks.executeRun.mock.calls[0][0];
    expect(request.options.create_unified_bom).toBe(false);
    expect(request.options).not.toHaveProperty("unified_newer_file");
  });

  it("carries both unified keys in the run payload when enabled", async () => {
    const user = userEvent.setup();
    render(<BomCompareTool />);
    await user.click(screen.getByRole("checkbox", { name: /^Create Unified BOM/ }));
    await user.click(screen.getByRole("button", { name: "Compare" }));

    await waitFor(() => expect(backendMocks.executeRun).toHaveBeenCalledTimes(1));
    const request = backendMocks.executeRun.mock.calls[0][0];
    expect(request.options.create_unified_bom).toBe(true);
    expect(request.options.unified_newer_file).toBe("file2");
  });

  it("disables the checkbox in Extraction Compare mode", async () => {
    const user = userEvent.setup();
    render(<BomCompareTool />);

    await user.click(screen.getByRole("button", { name: /Extraction Compare/i }));
    expect(
      screen.getByRole("checkbox", { name: /Create Unified BOM/i }),
    ).toBeDisabled();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run --config frontend/vite.config.ts BomCompareTool.test`
Expected: the 4 new tests FAIL (`Unable to find an accessible element with the role "checkbox" and name /^Create Unified BOM/`); every pre-existing test PASSES.

- [ ] **Step 3: Implement the UI wiring**

All edits in `frontend/src/features/bom-compare/BomCompareTool.tsx`:

**(a)** Add the import (next to the other component imports):

```tsx
import { CustomSelect } from "../../components/CustomSelect";
```

**(b)** Add the OPTION_META entry (end of the `OPTION_META` map, line ~229):

```tsx
  create_unified_bom: {
    label: "Create Unified BOM",
    hint: "Add a merged Unified BOM tab — new file as backbone, old manual rows carried forward, changes color-coded for review.",
  },
```

**(c)** Add the option default (end of the `useState` options object, line ~283):

```tsx
    treat_prov_as_covered: true,
    create_unified_bom: false,
```

**(d)** Add the picker state next to the options state:

```tsx
  // Unified BOM (2026-08-13): which slot holds the NEWER file. Backend
  // convention: file1 = grouping/bomA slot, file2 = bom/bomB slot. Sent
  // only when create_unified_bom is on (Wiring Invariant #1).
  const [unifiedNewerFile, setUnifiedNewerFile] = useState<"file1" | "file2">("file2");
```

**(e)** Add the slot-label helper inside the component (near `buildRunRequest`):

```tsx
  const unifiedRoles: [FileRole, FileRole] =
    workflowId === "bom_compare_custom" ? ["bomA", "bomB"] : ["grouping", "bom"];

  const unifiedSlotLabel = (slot: "file1" | "file2"): string => {
    const role = slot === "file1" ? unifiedRoles[0] : unifiedRoles[1];
    const nickname = (fileNicknames[role] ?? "").trim();
    const roleLabel = inputStates.find((input) => input.role === role)?.label ?? role;
    return nickname || roleLabel;
  };
```

**(f)** In `buildRunRequest`, before the `runOptions` assignment (line ~760), add:

```tsx
    const unifiedOptions = options.create_unified_bom
      ? { unified_newer_file: unifiedNewerFile }
      : {};
```

and spread it into BOTH non-extraction branches of `runOptions`:

```tsx
    const runOptions =
      workflowId === "extraction_compare"
        ? nicknameOptions
        : workflowId === "bom_compare_custom"
          ? {
              ...options,
              ...nicknameOptions,
              ...unifiedOptions,
              compare_columns: comparePairs.filter((pair) => pair.col_a && pair.col_b),
            }
          : { ...options, ...nicknameOptions, ...unifiedOptions };
```

**(g)** Render the picker in `OptionsSection`, between the checkbox loop's closing `})}` and `<OutputFolderPicker ...>` (line ~1386):

```tsx
              {options.create_unified_bom && workflowId !== "extraction_compare" ? (
                <CustomSelect
                  label="Newer BOM (merge wins conflicts)"
                  value={unifiedNewerFile}
                  options={[
                    { value: "file1", label: unifiedSlotLabel("file1") },
                    { value: "file2", label: unifiedSlotLabel("file2") },
                  ]}
                  onChange={(value) => setUnifiedNewerFile(value as "file1" | "file2")}
                />
              ) : null}
```

(The checkbox itself needs no gating code — the existing `extractionMode` branch in the loop disables every option checkbox in extraction mode with the "BOM compare modes only" hint, satisfying Wiring Invariant #2.)

- [ ] **Step 4: Run tests + typecheck, then commit**

```powershell
npx vitest run --config frontend/vite.config.ts BomCompareTool.test
npm run typecheck
npm run typecheck:tests
git add frontend/src/features/bom-compare/BomCompareTool.tsx frontend/src/features/bom-compare/BomCompareTool.test.tsx
git commit -m "BOM Compare: Add Create Unified BOM UI (checkbox + newer-file picker)"
```
Expected: all green.

---

### Task 8: Mock scenarios, doc counts, full verification

**Files:**
- Modify: `frontend/src/mocks/scenarios.ts`
- Modify: `CLAUDE.md` (two places), `README.md`, `docs/TESTING.md` (two tables)

- [ ] **Step 1: Add the unified-BOM notes line to the demo fixtures**

In `frontend/src/mocks/scenarios.ts`, extend the group scenario's result notes (line ~821):

```ts
        notes: [
          "Group vs BOM mode: compared grouping against BOM.",
          "Unified BOM tab (optional): merged rows color-coded — added green, deletions red, carried rows yellow.",
        ],
```

and the custom scenario's result notes (line ~874):

```ts
        notes: [
          "Custom mode: compared two BOMs directly by RefDes key.",
          "Unified BOM tab (optional): merged rows color-coded — added green, deletions red, carried rows yellow.",
        ],
```

Run: `npx vitest run --config frontend/vite.config.ts scenarios.test` — expected PASS.

- [ ] **Step 2: Run BOTH full suites and capture the real totals**

```powershell
.venv\Scripts\python.exe -m pytest backend/tests -q
npx vitest run --config frontend/vite.config.ts --reporter=default
```
Expected: all green. Note the totals printed by each runner (backend was 528, frontend 406 before this feature — the new totals are whatever these runs report; do NOT guess them).

- [ ] **Step 3: Sync the doc counts (Wiring Invariant #10)**

Using the totals from Step 2, update in one pass:
1. `CLAUDE.md` Dev Commands: `npm test` comment count, and the `pytest backend/tests` comment — bump the total and append `+ N unified-BOM` to the suite parenthetical.
2. `CLAUDE.md` Testing section: bump the backend header count; add a bullet for `test_unified_bom.py` (mirror the sibling bullets' style: name the column-plan/statuses/carry-forward/uniform-rule/writer coverage); update the `test_bom_compare_runtime.py` bullet (now includes the unified option wiring + validate rejection); update the frontend header count and the `BomCompareTool.test.tsx` bullet (unified checkbox/picker/payload tests).
3. `README.md`: test-count references.
4. `docs/TESTING.md`: both tables (backend gains a `test_unified_bom.py` row; adjust totals).

- [ ] **Step 4: Final verification + commit**

```powershell
.venv\Scripts\python.exe -m pytest backend/tests -q
npx vitest run --config frontend/vite.config.ts --reporter=default
npm run typecheck
npm run typecheck:tests
.venv\Scripts\python.exe backend/python/sidecar_main.py --self-test
git add frontend/src/mocks/scenarios.ts CLAUDE.md README.md docs/TESTING.md
git commit -m "Docs: Sync test counts + demo fixtures for Unified BOM"
```
Expected: everything green (the sidecar self-test also re-runs the security audit over the new module).

---

## Self-Review (performed while writing)

- **Spec coverage:** merge semantics → Task 2; suffix/pin carry + supersession + uniform rule → Task 3; statuses/styles/Source/Change Notes → Tasks 2–4; tab-in-workbook + atomic write untouched → Task 5; option keys, validate-time rejection, warning/notes integration, DNP handling → Task 6; checkbox/picker/payload/extraction-disable → Task 7; mock fixtures + doc counts → Task 8. Every spec section has a task.
- **Known simplifications (documented in code comments/tests):** multi-token value diffs run against each distinct matched old row with token prefixes; a suffix whose base sits inside a multi-RefDes new row becomes a flagged Delete (never silent) rather than a carry.
- **Type consistency:** `UnifiedBomResult` fields (`frame/row_styles/counts/warning_count/notes`) used identically in Tasks 4–6; `unified=` param name identical in both writers; option keys spelled `create_unified_bom`/`unified_newer_file` everywhere including tests.
