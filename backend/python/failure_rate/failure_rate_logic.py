#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Failure Rate Integration Tool - Core Logic
"""
import math
import re
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Union

import pandas as pd


def normalize_refdes_for_lookup(value) -> str:
    """
    Normalize RefDes for lookup, stripping leading zeros from numeric part.

    This ensures "U01" matches "U1" and "R001" matches "R1" across different
    data sources that may use inconsistent zero-padding.

    Args:
        value: Raw RefDes string (or NaN/None which returns empty string)

    Returns:
        Normalized RefDes with leading zeros stripped (e.g., "U01" -> "U1")
    """
    # Guard against NaN/None values to prevent "NAN" pollution in lookups
    # pd.isna() handles None, float NaN, pd.NA, and numpy NaN types
    if pd.isna(value):
        return ""
    s = str(value).strip().upper()
    # Match prefix (letters) + leading zeros + number + optional suffix (multi-letter)
    match = re.match(r'^([A-Z]+)0*(\d+)([A-Z]*)$', s)
    if match:
        prefix, num, suffix = match.groups()
        return f"{prefix}{int(num)}{suffix}"
    return s

# Tauri backend copy — source: src/apps/failure_rate/failure_rate_logic.py
from common import (
    try_read_table,
    ensure_columns_exist,
    sha256_of_path,
    write_snapshot,
    get_tool_logger,
    style_worksheet,
    write_df_to_sheet,
    CancellationToken,
    FMR_TOLERANCE,
    FileAccessError,
    ProcessingError,
    to_user_facing_text,
)
from common.refdes_utils import (
    extract_base_refdes,
    extract_instance_refdes,
)

# Initialize module logger
_logger = get_tool_logger("failure_rate")


# ==================== LOGIC CLASS ====================

class FMEALinkerLogic:
    """Core logic for linking FMEA data with failure rate predictions."""

    def __init__(
        self,
        log_func: Optional[Callable[[str], None]] = None,
        progress_func: Optional[Callable[[float], None]] = None,  # L7: Progress callback (0.0-1.0)
    ) -> None:
        self._log_func: Callable[[str], None] = log_func or print
        self._progress_func: Optional[Callable[[float], None]] = progress_func  # L7
        self.prediction_df: Optional[pd.DataFrame] = None
        self.fmea_df: Optional[pd.DataFrame] = None
        self.merged_df: Optional[pd.DataFrame] = None
        # Cancellation token for user-initiated stop requests
        self.cancel: CancellationToken = CancellationToken()

    def log(self, msg: str) -> None:
        """Log a message to both the GUI callback and the module logger."""
        self._log_func(msg)
        _logger.info(msg)

    def _report_progress(self, fraction: float) -> None:
        """L7: Report progress to GUI callback (0.0 to 1.0)."""
        if self._progress_func:
            self._progress_func(min(1.0, max(0.0, fraction)))

    def load_prediction(self, path: Union[str, Path], sheet_name=None) -> None:
        """Load prediction file containing failure rate data.

        Args:
            path: Path to the prediction file.
            sheet_name: Excel sheet name or index (None = first sheet).
        """
        self.log(f"Loading Prediction: {Path(path).name}")
        # Pass cancel_check so Cancel interrupts slow OneDrive reads /
        # retry loops instead of blocking until the read completes.
        self.prediction_df = try_read_table(
            path,
            sheet_name=sheet_name,
            log_func=self.log,
            cancel_check=self.cancel.is_cancelled,
        )
        if self.prediction_df is None or self.prediction_df.empty:
            raise FileAccessError(
                f"Failed to load prediction data from '{path}' or file is empty",
                file_path=str(path),
                operation="read",
            )
        self.log(f"  Loaded {len(self.prediction_df)} rows.")

    def load_fmea(self, path: Union[str, Path], sheet_name=None) -> None:
        """Load FMEA file containing failure mode data.

        Args:
            path: Path to the FMEA file.
            sheet_name: Excel sheet name or index (None = first sheet).
        """
        self.log(f"Loading FMEA: {Path(path).name}")
        self.fmea_df = try_read_table(
            path,
            sheet_name=sheet_name,
            log_func=self.log,
            cancel_check=self.cancel.is_cancelled,
        )
        if self.fmea_df is None or self.fmea_df.empty:
            raise FileAccessError(
                f"Failed to load FMEA data from '{path}' or file is empty",
                file_path=str(path),
                operation="read",
            )
        self.log(f"  Loaded {len(self.fmea_df)} rows.")

    def process(
        self,
        col_map: Dict[str, str],
        check_fmr: bool = False,
    ) -> pd.DataFrame:
        """Process FMEA and prediction data. Call self.cancel.cancel() to stop."""
        # Precondition check - ensure data is loaded
        if self.prediction_df is None or self.fmea_df is None:
            raise ProcessingError(
                "Data not loaded. Call load_prediction() and load_fmea() before process()."
            )

        self.log("Starting Processing...")
        pred = self.prediction_df.copy()
        fmea = self.fmea_df.copy()

        pred_ref_col = col_map['pred_ref']
        pred_fr_col = col_map['pred_fr']
        ensure_columns_exist(pred, [pred_ref_col, pred_fr_col], "Prediction file")
        
        # Normalize RefDes with zero-stripping (U01 -> U1, R001 -> R1)
        pred['RefDes_Norm'] = pred[pred_ref_col].apply(normalize_refdes_for_lookup)
        pred['FR_Clean'] = pd.to_numeric(pred[pred_fr_col], errors='coerce').fillna(0.0)

        # Validate and apply unit conversion
        valid_unit_modes = {'per_hour', 'per_million_hours', 'per_billion_hours'}
        unit_mode = col_map.get('unit_mode', 'per_hour')
        if unit_mode not in valid_unit_modes:
            self.log(f"  WARNING: Invalid unit_mode '{unit_mode}', defaulting to 'per_hour'")
            unit_mode = 'per_hour'

        if unit_mode == "per_million_hours":
            pred['FR_Clean'] = pred['FR_Clean'] / 1_000_000
        elif unit_mode == "per_billion_hours":
            pred['FR_Clean'] = pred['FR_Clean'] / 1_000_000_000
        # per_hour: no conversion needed
        
        # Check for duplicate RefDes in Prediction file - keep first occurrence
        pred_dupes = pred[pred.duplicated(subset=['RefDes_Norm'], keep=False)]
        if not pred_dupes.empty:
            dupe_refs = pred_dupes['RefDes_Norm'].unique()
            # L5: Show clear total count and sample of duplicates
            sample = ', '.join(dupe_refs[:5])
            remaining = len(dupe_refs) - 5
            suffix = f" (and {remaining} more)" if remaining > 0 else ""
            self.log(f"  WARNING: Found {len(dupe_refs)} duplicate RefDes entries in Prediction: {sample}{suffix}")

        # Drop duplicates keeping first occurrence, then create lookup
        pred_deduped = pred.drop_duplicates(subset=['RefDes_Norm'], keep='first')
        if len(pred_deduped) < len(pred):
            dropped_count = len(pred) - len(pred_deduped)
            self.log(f"  Note: Dropped {dropped_count} duplicate rows (keeping first occurrence)")
        fr_lookup = pred_deduped.set_index('RefDes_Norm')['FR_Clean'].to_dict()
        self.log(f"  Mapped {len(fr_lookup)} failure rates from Prediction.")

        fmea_cause_col = col_map['fmea_cause']
        fmea_ratio_col = col_map['fmea_ratio']
        fmea_usage_col = col_map['fmea_usage']
        fmea_func_col = col_map['fmea_func']
        # M3: Normalize fmea_func_col early - GUI may send "" or "None" for unselected
        if not fmea_func_col or fmea_func_col == "None":
            fmea_func_col = ""
        fmea_required = [fmea_cause_col, fmea_ratio_col, fmea_usage_col]
        if fmea_func_col:
            fmea_required.append(fmea_func_col)
        ensure_columns_exist(fmea, fmea_required, "FMEA file")

        # Check for duplicate RefDes in FMEA file (for user awareness)
        fmea_dupes = fmea[fmea.duplicated(subset=[fmea_cause_col], keep=False)]
        if not fmea_dupes.empty:
            self.log(f"  Note: Found {len(fmea_dupes)} rows with duplicate Failure Cause values (expected for multiple failure modes per component).")

        linked_count = 0
        missing_refs = set()

        # Initialize accumulators for vectorized column assignment
        # Using list accumulation pattern for 5-10x performance improvement over iterrows()
        extracted_refdes_list = []
        validation_refdes_list = []
        part_fr_list = []
        mode_fr_list = []
        corrected_ratio_list = []
        validation_notes_list = []

        # Build column index map for position-based access
        # This handles column names with spaces/special characters that break namedtuple attributes
        col_list = list(fmea.columns)
        cause_idx = col_list.index(fmea_cause_col)
        ratio_idx = col_list.index(fmea_ratio_col)
        usage_idx = col_list.index(fmea_usage_col)

        # Use itertuples(name=None, index=False) for 5-10x performance over iterrows()
        # M6 fix: index=False removes DataFrame index from tuple, simplifying access
        total_rows = len(fmea)
        for row_idx, row in enumerate(fmea.itertuples(name=None, index=False)):
            self.cancel.check("Processing cancelled by user.")
            # L7: Report progress every 100 rows to avoid callback overhead
            if row_idx % 100 == 0:
                self._report_progress(row_idx / total_rows * 0.8)  # 0-80% for main loop
            # Direct column access without index offset
            cause_text = str(row[cause_idx]) if pd.notna(row[cause_idx]) else ""
            notes = []

            # 1. Extract Base RefDes for Linking (e.g. U200 from U200-1)
            # Using centralized refdes_utils for consistent behavior across tools
            refdes_raw = extract_base_refdes(cause_text)
            # Normalize to match prediction lookup (strip leading zeros: U01 -> U1)
            refdes = normalize_refdes_for_lookup(refdes_raw) if refdes_raw else None
            extracted_refdes_list.append(refdes or "")

            # Lookup failure rate
            if refdes and refdes in fr_lookup:
                part_fr = fr_lookup[refdes]
                linked_count += 1
            elif refdes:
                part_fr = 0.0
                missing_refs.add(refdes)
                notes.append("RefDes not in Prediction")
            else:
                part_fr = 0.0
            part_fr_list.append(part_fr)

            # 2. Extract Instance RefDes for Validation (e.g. U200-1).
            # FMR (Failure Mode Ratio) validation deliberately groups by the
            # INSTANCE / pin designator, NOT the base component: each instance
            # (U200-1, U200-2) carries its own failure modes (open/short/...)
            # whose ratios must sum to 1.0. Component-level failure-rate roll-up
            # is handled separately by the Part Usage column, which fractionally
            # allocates (e.g. 1/2 each) so Mode_FR sums back to the base part's
            # rate. Collapsing instances to a base RefDes HERE would wrongly sum
            # multiple instances' ratios to > 1.0 and emit false FMR warnings.
            # Do NOT "fix" this to group by base RefDes.
            if check_fmr:
                inst_ref = extract_instance_refdes(cause_text)
                validation_refdes_list.append(inst_ref if inst_ref else (refdes or ""))
            else:
                validation_refdes_list.append("")

            # Validate and convert usage value (C10 fix: check for inf/huge values)
            usage_val = pd.to_numeric(row[usage_idx], errors='coerce')
            if pd.isna(usage_val):
                usage = 1.0
                notes.append("Invalid Usage (NaN, defaulted 1.0)")
            else:
                usage = float(usage_val)
                # C10: Validate finite and reasonable range
                if not math.isfinite(usage) or usage <= 0 or usage > 1e6:
                    notes.append(f"Invalid Usage ({usage}, defaulted 1.0)")
                    usage = 1.0

            # Validate and convert ratio value (C10 fix: check for inf/huge values)
            ratio_val = pd.to_numeric(row[ratio_idx], errors='coerce')
            if pd.isna(ratio_val):
                ratio = 1.0
                notes.append("Invalid Ratio (NaN, defaulted 1.0)")
            else:
                ratio = float(ratio_val)
                # C10: Validate finite and reasonable range (0-1 expected for FMR)
                if not math.isfinite(ratio) or ratio < 0 or ratio > 10:
                    notes.append(f"Invalid Ratio ({ratio}, defaulted 1.0)")
                    ratio = 1.0

            corrected_ratio_list.append(ratio)

            # Calculate mode failure rate
            mode_fr = part_fr * usage * ratio
            mode_fr_list.append(mode_fr)

            # Format validation notes with trailing semicolon/space for consistency
            validation_notes_list.append("; ".join(notes) + ("; " if notes else ""))

        # Assign all columns at once (vectorized assignment)
        fmea['Extracted_RefDes'] = extracted_refdes_list
        fmea['Validation_RefDes'] = validation_refdes_list
        fmea['Part_FR'] = part_fr_list
        fmea['Mode_FR'] = mode_fr_list
        fmea['Corrected_Ratio'] = corrected_ratio_list
        fmea['Validation_Notes'] = validation_notes_list

        self.log(f"  Linked {linked_count} rows to Prediction data.")
        if missing_refs: self.log(f"  Warning: {len(missing_refs)} RefDes found in FMEA but missing in Prediction.")
        self._report_progress(0.85)  # L7: 85% after main linking

        if check_fmr:
            self.log("  Validating Failure Mode Ratios (Sum to 1.0)...")
            # Group by Validation_RefDes
            # Filter out empty validation refdes
            valid_rows = fmea[fmea['Validation_RefDes'] != ""]
            # Use Corrected_Ratio column for consistent validation with Mode_FR calculations
            ratio_sums = valid_rows.groupby('Validation_RefDes')['Corrected_Ratio'].sum()
            
            for ref, total in ratio_sums.items():
                self.cancel.check("Processing cancelled by user.")
                # Check if sum is 1.0 - use epsilon comparison for float reliability
                # M4 fix: Remove redundant round() - compare directly against tolerance
                if abs(total - 1.0) > FMR_TOLERANCE:
                    mask = fmea['Validation_RefDes'] == ref
                    fmea.loc[mask, 'Validation_Notes'] += f"FMR Sum {total:.2f} != 1.0; "
            self._report_progress(0.95)  # L7: 95% after FMR validation

        if fmea_func_col and fmea_func_col != "None":
            self.log("  Calculating Function Failure Rates...")
            func_fr = fmea.groupby(fmea_func_col)['Mode_FR'].transform('sum')
            fmea['Function_FR'] = func_fr

        self.merged_df = fmea
        self._report_progress(1.0)  # L7: 100% complete
        return fmea

    def save_results(self, output_path: Union[str, Path]) -> None:
        """Save merged results to an Excel file."""
        if self.merged_df is None: return
        self.log(f"Saving report to: {output_path}")
        try:
            from openpyxl import Workbook

            export_df = self.merged_df.copy()
            for col in export_df.columns:
                export_df[col] = export_df[col].apply(to_user_facing_text)

            wb = Workbook()
            ws_main = wb.active
            ws_main.title = "Main"

            # Row styling based on validation status
            # M7 fix: Check column exists before accessing
            has_validation_col = 'Validation_Notes' in export_df.columns

            def main_row_style(row, idx):
                if not has_validation_col:
                    return 'default'
                notes = str(row.get('Validation_Notes', ''))
                has_ratio_sum_error = (
                    ('FMR Sum' in notes and '!= 1.0' in notes)
                    or ('Failure Mode Ratio Sum' in notes and '!= 1.0' in notes)
                )
                if has_ratio_sum_error:
                    return 'error'
                elif notes.strip():
                    return 'warning'
                return 'default'

            # Write and style Main sheet (with zebra striping for readability)
            write_df_to_sheet(ws_main, export_df)
            style_worksheet(ws_main, export_df, row_style_func=main_row_style, max_width=40, alternate_rows=True)

            # Apply scientific notation to failure rate columns
            from common.excel_styles import NUMBER_FORMATS
            from openpyxl.utils import get_column_letter
            fr_columns = ['Mode_FR', 'Function_FR', 'Failure_Rate', 'FR']
            for col_idx, col_name in enumerate(export_df.columns, start=1):
                if isinstance(col_name, str) and (col_name in fr_columns or col_name.endswith('_FR')):
                    col_letter = get_column_letter(col_idx)
                    for row_idx in range(2, ws_main.max_row + 1):
                        cell = ws_main[f"{col_letter}{row_idx}"]
                        if cell.value is not None and cell.value != '':
                            cell.number_format = NUMBER_FORMATS["scientific"]

            # Create Validation Warnings sheet if there are warnings
            # M7 fix: Only create sheet if column exists
            if has_validation_col and 'Extracted_RefDes' in export_df.columns:
                val_df = export_df[export_df['Validation_Notes'] != ""][['Extracted_RefDes', 'Validation_Notes']]
            else:
                val_df = pd.DataFrame()  # Empty DataFrame
            if not val_df.empty:
                ws_val = wb.create_sheet("Validation Warnings")
                write_df_to_sheet(ws_val, val_df)
                # All validation rows get warning styling
                style_worksheet(ws_val, val_df, row_style_func=lambda r, i: 'warning', max_width=60)

            wb.save(output_path)
            self.log("  Save complete.")
        except (IOError, OSError, PermissionError) as e:
            self.log(f"  Failed to save: {e}")
            raise
