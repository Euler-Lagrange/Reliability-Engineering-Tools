#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================
# Freeze lifted 2026-04-08: this file is now actively maintained as part of
# the Tauri desktop suite. The original "FROZEN -- Do not modify" directive
# has been removed by user request. See plan: mighty-wishing-meadow.md
# ============================================================================
"""
BOM Verifier - Verification and Conflict Detection Layer

This module handles BOM (Bill of Materials) verification by comparing extracted
RefDes identifiers against a reference BOM, enabling users to validate extraction
accuracy and identify discrepancies.

Key responsibilities:
- Load BOM files (Excel/CSV) and extract RefDes
- Normalize RefDes for consistent matching
- Verify extracted RefDes against BOM (exact 1:1 matching)
- Generate conflict reports (extracted-only, BOM-only)
- Split groups into verified/unverified buckets

Author: Claude Code (Anthropic)
Date: 2025-12-02
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Set, List, Tuple, Optional

import pandas as pd
import sys

# Import from geometry_analyzer
from . import geometry_analyzer as ga

# Import shared utilities
from common import (
    get_tool_logger,
    ensure_file_available,
    try_read_table,
    detect_column,
)
from common.column_synonyms import get_synonyms
from common.refdes_utils import canonicalize_refdes
from common.exceptions import ValidationError, FileAccessError

_logger = get_tool_logger("bom_verifier")

# ==================== DATA STRUCTURES ====================

@dataclass
class VerificationResult:
    """BOM verification outcome."""
    verified_refdes: Set[str]      # In BOM
    unverified_refdes: Set[str]    # Not in BOM or exceed BOM count
    bom_only_refdes: Set[str]      # In BOM but not extracted
    confidence_threshold: float     # Threshold used for filtering
    bom_set: Set[str] = None       # Original BOM set (for qualified pin matching)


# ==================== BOM LOADING ====================

def load_bom(
    bom_path: str,
    refdes_column: str = "RefDes",
    log_func=None
) -> Set[str]:
    """
    Load BOM and extract normalized RefDes set.

    Handles both Excel and CSV files, normalizes RefDes identifiers,
    and returns a deduplicated set.

    Args:
        bom_path: Excel/CSV file path
        refdes_column: Column name (uses synonyms for fuzzy matching)
        log_func: Optional logging callback

    Returns:
        Set of canonicalized RefDes strings

    Raises:
        FileAccessError: If file cannot be accessed
        ValidationError: If RefDes column not found

    Example:
        >>> bom_set = load_bom("my_bom.xlsx")
        >>> print(f"Loaded {len(bom_set)} components from BOM")
        Loaded 245 components from BOM
    """
    from .bom_loader import load_bom_exact

    try:
        return load_bom_exact(
            bom_path=bom_path,
            ref_col_name=refdes_column,
            log_func=log_func,
        )
    except RuntimeError as ex:
        message = str(ex)
        if "recognizable RefDes column" in message:
            available_hint = ""
            try:
                df = try_read_table(str(ensure_file_available(bom_path, log_func)))
                available = ", ".join(map(str, df.columns[:10]))
                tried_synonyms = ", ".join(get_synonyms('ref_des')[:5])
                available_hint = (
                    f" Tried: '{refdes_column}' and synonyms ({tried_synonyms}). "
                    f"Available columns: {available}..."
                )
            except Exception:
                pass
            raise ValidationError(f"RefDes column not found in BOM.{available_hint}") from ex
        if "Failed to read BOM" in message or "Cannot access" in message:
            raise FileAccessError(message) from ex
        raise


# ==================== VERIFICATION ====================

def verify_mappings(
    pin_map: Dict[str, ga.PinMapping],
    bom_refdes: Set[str],
    confidence_threshold: float = 0.5,
    log_func=None
) -> VerificationResult:
    """
    Compare extracted RefDes against BOM.

    Performs exact 1:1 matching (no fuzzy matching) to ensure reliability.
    Splits extracted RefDes into verified (in BOM) and unverified (not in BOM).

    Args:
        pin_map: Output from geometry_analyzer.analyze_document
        bom_refdes: Normalized RefDes set from load_bom
        confidence_threshold: Minimum confidence to include (0.0-1.0)
        log_func: Optional logging callback

    Returns:
        VerificationResult with split sets

    Example:
        >>> result = verify_mappings(pin_map, bom_set)
        >>> print(f"Verified: {len(result.verified_refdes)}")
        >>> print(f"Unverified: {len(result.unverified_refdes)}")
        Verified: 180
        Unverified: 12
    """
    def log(msg):
        if log_func:
            log_func(msg)
        _logger.info(msg)

    log("Verifying extracted RefDes against BOM...")

    # Extract unique RefDes from pin_map
    extracted_refdes = set()

    for mapping in pin_map.values():
        if mapping.confidence >= confidence_threshold:
            normalized = canonicalize_refdes(mapping.refdes)
            if normalized:
                extracted_refdes.add(normalized)

    # Split into verified/unverified
    verified = extracted_refdes & bom_refdes
    unverified = extracted_refdes - bom_refdes
    bom_only = bom_refdes - extracted_refdes

    log(f"  Verified: {len(verified)} RefDes")
    log(f"  Unverified: {len(unverified)} RefDes (not in BOM)")
    log(f"  BOM-only: {len(bom_only)} RefDes (not extracted)")

    return VerificationResult(
        verified_refdes=verified,
        unverified_refdes=unverified,
        bom_only_refdes=bom_only,
        confidence_threshold=confidence_threshold,
        bom_set=bom_refdes  # Include original BOM for qualified pin matching
    )


# ==================== CONFLICT REPORTING ====================

def generate_conflict_report(
    verification: VerificationResult,
    output_path: str,
    log_func=None
) -> None:
    """
    Export BOM conflicts to CSV.

    Creates a CSV file with three sections:
    - Verified: RefDes found in both extraction and BOM
    - Extracted Only: RefDes extracted but not in BOM
    - BOM Only: RefDes in BOM but not extracted

    Args:
        verification: VerificationResult from verify_mappings
        output_path: Output CSV file path
        log_func: Optional logging callback

    Raises:
        IOError: If file cannot be written

    Example:
        >>> generate_conflict_report(result, "conflicts.csv")
        Conflict report saved: conflicts.csv
    """
    def log(msg):
        if log_func:
            log_func(msg)
        _logger.info(msg)

    log(f"Generating conflict report: {output_path}")

    rows = []

    # Verified section
    for refdes in sorted(verification.verified_refdes):
        rows.append({
            "RefDes": refdes,
            "Status": "Verified",
            "Description": "Found in both extraction and BOM"
        })

    # Extracted only section
    for refdes in sorted(verification.unverified_refdes):
        rows.append({
            "RefDes": refdes,
            "Status": "Extracted Only",
            "Description": "Not found in BOM"
        })

    # BOM only section
    for refdes in sorted(verification.bom_only_refdes):
        rows.append({
            "RefDes": refdes,
            "Status": "BOM Only",
            "Description": "Not extracted from PDF"
        })

    # Create DataFrame and save
    df = pd.DataFrame(rows)

    try:
        df.to_csv(output_path, index=False)
        log(f"  Conflict report saved: {output_path}")
        log(f"  Total entries: {len(rows)}")
    except Exception as e:
        raise IOError(f"Failed to save conflict report: {e}")


# ==================== GROUP VERIFICATION ====================

def apply_verification_to_groups(
    groups_df: pd.DataFrame,
    verification: VerificationResult,
    refdes_column: str = "failure mode causes"
) -> pd.DataFrame:
    """
    Add verification status to groups DataFrame.

    Annotates each group with verification status based on its components:
    - All components verified → "VERIFIED"
    - All components unverified → "UNVERIFIED"
    - Mixed → "PARTIAL"

    Args:
        groups_df: DataFrame with extraction results
        verification: VerificationResult from verify_mappings
        refdes_column: Column containing comma-separated RefDes

    Returns:
        Modified DataFrame with "verification_status" column and updated group names

    Example:
        >>> df = apply_verification_to_groups(results_df, verification_result)
        >>> print(df[["group", "verification_status"]])
          group                       verification_status
          CPU-001 (VERIFIED)          verified
          CPU-002 (UNVERIFIED)        unverified
    """
    def classify_group(row):
        """Determine verification status for a group."""
        components_str = str(row.get(refdes_column, ""))
        if not components_str or components_str == "No components found":
            return "empty"

        # Parse components (format: U1B-P20, U1C-P15, R400, etc.)
        components = [c.strip() for c in components_str.split(",")]

        # Check each component against BOM
        # Priority: Full identifier first (e.g., "U201-AA27"), then base RefDes (e.g., "U201")
        bom_set = verification.bom_set or set()
        verified_count = 0
        total = 0

        for comp in components:
            if not comp:
                continue
            total += 1
            full_id = canonicalize_refdes(comp)

            # Check 1: Is the FULL identifier in the BOM? (e.g., "U201-AA27")
            if full_id in bom_set:
                verified_count += 1
                continue

            # Check 2: Is the FULL identifier in verified_refdes? (base RefDes matches)
            if full_id in verification.verified_refdes:
                verified_count += 1
                continue

            # Check 3: For qualified pins (with hyphen), extract base RefDes and check
            if "-" in comp:
                base_refdes = canonicalize_refdes(comp.split("-")[0])
                if base_refdes in verification.verified_refdes or base_refdes in bom_set:
                    verified_count += 1
                    continue

        if total == 0:
            return "empty"
        elif verified_count == total:
            return "verified"
        elif verified_count == 0:
            return "unverified"
        else:
            return "partial"

    # Add verification status column
    groups_df = groups_df.copy()
    groups_df["verification_status"] = groups_df.apply(classify_group, axis=1)

    # Update group names with status annotation
    def annotate_group_name(row):
        group_name = row["group"]
        status = row["verification_status"]

        if status == "empty":
            return group_name  # Don't annotate empty groups
        elif status == "verified":
            return f"{group_name} (VERIFIED)"
        elif status == "unverified":
            return f"{group_name} (UNVERIFIED)"
        else:  # partial
            return f"{group_name} (PARTIAL)"

    groups_df["group"] = groups_df.apply(annotate_group_name, axis=1)

    return groups_df


# ==================== STANDALONE UTILITY ====================

def verify_extraction_against_bom(
    pdf_path: str,
    bom_path: str,
    output_dir: str = ".",
    config: Optional[Dict] = None,
    log_func=None
) -> Tuple[Dict[str, ga.PinMapping], VerificationResult]:
    """
    Convenience function to run analysis, verification, and reporting in one step.

    Args:
        pdf_path: Input PDF schematic
        bom_path: BOM file (Excel/CSV)
        output_dir: Directory for output files
        config: Optional geometry analysis config
        log_func: Optional logging callback

    Returns:
        Tuple of (pin_map, verification_result)

    Example:
        >>> pin_map, result = verify_extraction_against_bom("sch.pdf", "bom.xlsx")
        >>> print(f"Verified: {len(result.verified_refdes)}")
    """
    def log(msg):
        if log_func:
            log_func(msg)
        _logger.info(msg)

    # Ensure output directory exists
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Run geometry analysis
    log("Step 1: Running geometry analysis...")
    pin_map, _body_rects = ga.analyze_document(pdf_path, config, log_func=log)

    # Load BOM
    log("Step 2: Loading BOM...")
    bom_refdes = load_bom(bom_path, log_func=log)

    # Verify
    log("Step 3: Verifying against BOM...")
    verification = verify_mappings(pin_map, bom_refdes, log_func=log)

    # Generate conflict report
    pdf_stem = Path(pdf_path).stem
    conflict_path = output_path / f"{pdf_stem}_conflicts.csv"
    generate_conflict_report(verification, str(conflict_path), log_func=log)

    return pin_map, verification


# ==================== COMMAND-LINE INTERFACE ====================

if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(
        description="Verify RefDes extraction against BOM"
    )
    parser.add_argument("pdf", help="Input PDF schematic")
    parser.add_argument("bom", help="BOM file (Excel or CSV)")
    parser.add_argument(
        "-o", "--output",
        help="Output directory (default: current directory)",
        default="."
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="Confidence threshold (default: 0.5)"
    )

    args = parser.parse_args()

    config = {
        "pin_assignment_threshold": 50.0,
        "refdes_search_radius": 100.0,
    }

    try:
        pin_map, result = verify_extraction_against_bom(
            args.pdf,
            args.bom,
            args.output,
            config
        )

        print("\n✓ Verification complete:")
        print(f"  Verified:   {len(result.verified_refdes)} RefDes")
        print(f"  Unverified: {len(result.unverified_refdes)} RefDes")
        print(f"  BOM-only:   {len(result.bom_only_refdes)} RefDes")
        print(f"\nConflict report saved to: {args.output}")

        sys.exit(0)

    except Exception as e:
        print(f"✗ Error: {e}", file=sys.stderr)
        sys.exit(1)
