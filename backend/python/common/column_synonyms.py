#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Centralized Column Name Synonyms

This module provides standardized column name synonyms used across all
reliability engineering tools. Centralizing these definitions ensures
consistent column detection behavior and easier maintenance.

Usage:
    from common.column_synonyms import COLUMN_SYNONYMS, get_synonyms

    # Get synonyms for a specific column type
    ref_des_names = get_synonyms('ref_des')

    # Use with detect_column
    col = detect_column(df.columns, get_synonyms('ref_des'))
"""
from typing import Dict, List

# =============================================================================
# COLUMN SYNONYMS - Single Source of Truth
# =============================================================================

COLUMN_SYNONYMS: Dict[str, List[str]] = {
    # -------------------------------------------------------------------------
    # Reference Designator
    # -------------------------------------------------------------------------
    'ref_des': [
        'RefDes', 'Reference Designator', 'Reference Designators',
        'ReferenceDesignator', 'ReferenceDesignators',
        'Part Reference Designator', 'Ref Des', 'Ref_Des', 'Designator',
        'Refs', 'Components', 'Parts', 'RefDes List', 'Ref',
        'Failure Mode Causes',  # Used in some FMEA contexts
        'Failure Mode Cause',
        'FMCs',
    ],

    # -------------------------------------------------------------------------
    # Part Number
    # -------------------------------------------------------------------------
    'part_number': [
        'Part Number', 'PartNumber', 'P/N', 'Part_Number', 'PN',
        'BAE Part Number', 'BAE PN',
    ],

    # -------------------------------------------------------------------------
    # Description
    # -------------------------------------------------------------------------
    'description': [
        'Name', 'Part Description', 'Primary Part Description',
        'Description', 'Part_Description', 'Item Description',
        'Desc', 'PartDesc', 'Part Name', 'Component Name',
    ],

    # -------------------------------------------------------------------------
    # Component Group / Function Block
    # -------------------------------------------------------------------------
    'component_group': [
        'Component Group', 'Component Grouping', 'Group', 'Function Block',
        'Circuit Block', 'Partition', 'Block', 'Area', 'Function Group',
        'Group ID', 'Function_Group',
    ],

    # -------------------------------------------------------------------------
    # Function ID (for Functional FMEA)
    # -------------------------------------------------------------------------
    'function_id': [
        'Function ID', 'Function', 'Function/Group', 'Component Group',
        'Group', 'Block', 'Func ID', 'Identification Number', 'ID Number',
        'Ident Number', 'ID',
    ],

    # -------------------------------------------------------------------------
    # FMEA ID / Identification Number
    # -------------------------------------------------------------------------
    'fmea_id': [
        'FMEA ID', 'FMEA-ID', 'FMEA_ID', 'FMEAID',
        'Identification Number', 'ID Number', 'Ident Number',
    ],

    # -------------------------------------------------------------------------
    # Function Description
    # -------------------------------------------------------------------------
    'function_description': [
        'Function Description', 'Function_Description', 'Description',
    ],

    # -------------------------------------------------------------------------
    # Schematic Page
    # -------------------------------------------------------------------------
    'schematic_page': [
        'Schematic Page', 'Page', 'Schematic',
    ],

    # -------------------------------------------------------------------------
    # Commodity Levels (HDA)
    # -------------------------------------------------------------------------
    'commodity_level1': [
        'Commodity Level 1', 'Commodity Level I',
        'HDA Commodity Level 1', 'HDA Commodity Level I',
        'BAE HDA Commodity I',
        # BAE variants with "Level"
        'BAE HDA Commodity Level', 'BAE HDA Commodity Level I', 'BAE HDA Commodity Level 1',
        # Short forms (without "Level")
        'HDA Commodity', 'HDA Commodity I', 'Commodity', 'Commodity I',
    ],

    'commodity_level2': [
        'Commodity Level 2', 'Commodity Level II',
        'HDA Commodity Level 2', 'HDA Commodity Level II',
        'BAE HDA Commodity II',
        # BAE variants with "Level"
        'BAE HDA Commodity Level II', 'BAE HDA Commodity Level 2',
        # Short forms (without "Level")
        'HDA Commodity II', 'Commodity II',
    ],

    # -------------------------------------------------------------------------
    # FMD Component Types
    # -------------------------------------------------------------------------
    'fmd_type1': [
        'FMD-91 Component Type 1', 'FMD-2016 Component Type 1',
        'FMD Component Type 1', 'FMD Type 1',
        'Component Type 1', 'Type 1', 'FMD-2016 Commodity Type 1',
        # Roman numeral variations (common in user data)
        'FMD-2016 Commodity I', 'FMD-91 Commodity I',
        'FMD-2016 I', 'FMD-91 I',
        # "Level" variants (common in BAE/industry data)
        'FMD-2016 Commodity Level I', 'FMD-91 Commodity Level I',
        'FMD Commodity Level I', 'FMD Commodity Level 1',
        # "Type" with Roman numerals
        'FMD-2016 Commodity Type I', 'FMD-91 Commodity Type I',
        'FMD Commodity Type I', 'Component Type I', 'Type I',
    ],

    'fmd_type2': [
        'FMD-91 Component Type 2', 'FMD-2016 Component Type 2',
        'FMD Component Type 2', 'FMD Type 2',
        'Component Type 2', 'Type 2', 'FMD-2016 Commodity Type 2',
        # Roman numeral variations (common in user data)
        'FMD-2016 Commodity II', 'FMD-91 Commodity II',
        'FMD-2016 II', 'FMD-91 II',
        # "Level" variants (common in BAE/industry data)
        'FMD-2016 Commodity Level II', 'FMD-91 Commodity Level II',
        'FMD Commodity Level II', 'FMD Commodity Level 2',
        # "Type" with Roman numerals
        'FMD-2016 Commodity Type II', 'FMD-91 Commodity Type II',
        'FMD Commodity Type II', 'Component Type II', 'Type II',
    ],

    # -------------------------------------------------------------------------
    # Failure Mode
    # -------------------------------------------------------------------------
    'failure_mode': [
        'Failure Mode', 'Failure Modes', 'Main Failure Modes', 'Mode',
        'FM', 'Main Failure Mode', 'Functional Failure Mode',
    ],

    # -------------------------------------------------------------------------
    # Failure Mode Ratio
    # -------------------------------------------------------------------------
    'ratio': [
        'Ratio', 'FMR', 'Failure Mode Ratio', 'Percentage', 'Percent',
        'Probability', 'FM Ratio',
    ],

    # Strict FMR-only synonyms — excludes generic terms like "Percentage",
    # "Percent", "Probability" that can false-match on non-FMEA data.
    # Use this key for FMR detection in contexts where the input file
    # may or may not be an FMEA (e.g., BOM Compare part usage checks).
    'fmr_strict': [
        'FMR', 'Failure Mode Ratio', 'FM Ratio', 'Ratio',
    ],

    # -------------------------------------------------------------------------
    # Part Usage / Quantity
    # -------------------------------------------------------------------------
    'part_usage': [
        'Part Usage', 'Usage', 'Quantity', 'Qty',
    ],

    # -------------------------------------------------------------------------
    # Effects (Functional FMEA)
    # -------------------------------------------------------------------------
    'local_effect': [
        'Local Effect', 'Local Effects', 'Local',
        'Local Effect (Board)', 'Board Effect', 'Board',
    ],

    'next_higher_effect': [
        'Next Higher Effect', 'Next-Higher Effect', 'Next Effect',
        'Channel Effect', 'Channel', 'Next Higher Effect (Channel)',
    ],

    'end_effect': [
        'End Effect', 'FADEC Effect', 'System Effect',
        'Top Effect', 'FADEC', 'End Effect (FADEC)',
    ],

    # -------------------------------------------------------------------------
    # FMEA RefDes (for piece-part coverage validation)
    # -------------------------------------------------------------------------
    'fmea_refdes': [
        'Failure Mode Causes', 'Failure Mode Cause', 'FMCs',
        'RefDes', 'Reference Designator', 'Ref Des', 'Ref_Des',
        'Parts', 'Components', 'Affected Parts',
    ],

    # -------------------------------------------------------------------------
    # Circuit Block / FMEA Level Column (O2: centralized from bom_compare_logic)
    # Used to detect FMEA row types for duplicate detection filtering
    # -------------------------------------------------------------------------
    'circuit_block': [
        'circuit block', 'function block', 'component group', 'function group',
        'circuit_block', 'function_block', 'fmea level', 'fmea_level', 'row type',
    ],
}


# =============================================================================
# FILE-SPECIFIC CONFIGURATIONS
# =============================================================================
# These map standard column keys to their synonyms for specific file contexts.
# This allows tools to define which columns they need without repeating synonyms.

HEADER_CONFIG = {
    'BOM': {
        'ref_des': COLUMN_SYNONYMS['ref_des'],
        'part_number': COLUMN_SYNONYMS['part_number'],
        'description': COLUMN_SYNONYMS['description'],
        'hda_level1': COLUMN_SYNONYMS['commodity_level1'],
        'hda_level2': COLUMN_SYNONYMS['commodity_level2'],
        'part_usage': COLUMN_SYNONYMS['part_usage'],
    },
    # BOM_ENRICHED: Used when BOM contains inline HDA/FMD columns (no separate HDA file)
    'BOM_ENRICHED': {
        'ref_des': COLUMN_SYNONYMS['ref_des'],
        'part_number': COLUMN_SYNONYMS['part_number'],
        'description': COLUMN_SYNONYMS['description'],
        'hda_level1': COLUMN_SYNONYMS['commodity_level1'],
        'hda_level2': COLUMN_SYNONYMS['commodity_level2'],
        'fmd_type1': COLUMN_SYNONYMS['fmd_type1'],
        'fmd_type2': COLUMN_SYNONYMS['fmd_type2'],
        'part_usage': COLUMN_SYNONYMS['part_usage'],
    },
    'HDA': {
        'part_number': COLUMN_SYNONYMS['part_number'],
        'commodity_level1': COLUMN_SYNONYMS['commodity_level1'],
        'commodity_level2': COLUMN_SYNONYMS['commodity_level2'],
        'description': COLUMN_SYNONYMS['description'],
        'fmd_type1': COLUMN_SYNONYMS['fmd_type1'],
        'fmd_type2': COLUMN_SYNONYMS['fmd_type2'],
    },
    'FAILURE_MODES': {
        # Accept BOTH FMD types AND Commodity levels (different naming conventions)
        'commodity_level1': COLUMN_SYNONYMS['fmd_type1'] + COLUMN_SYNONYMS['commodity_level1'],
        'commodity_level2': COLUMN_SYNONYMS['fmd_type2'] + COLUMN_SYNONYMS['commodity_level2'],
        'failure_mode': COLUMN_SYNONYMS['failure_mode'],
        'ratio': COLUMN_SYNONYMS['ratio'],
    },
    'COMPONENT_GROUPING': {
        'component_group': COLUMN_SYNONYMS['component_group'],
        'description': COLUMN_SYNONYMS['function_description'],
        'ref_des': COLUMN_SYNONYMS['ref_des'],
        'schematic_page': COLUMN_SYNONYMS['schematic_page'],
    },
    'FUNCTIONAL': {
        'function_id': COLUMN_SYNONYMS['function_id'],
        'failure_mode': COLUMN_SYNONYMS['failure_mode'],
        'local_effect': COLUMN_SYNONYMS['local_effect'],
        'next_higher_effect': COLUMN_SYNONYMS['next_higher_effect'],
        'end_effect': COLUMN_SYNONYMS['end_effect'],
    },
    'FUNCTIONAL_MERGE_SOURCE': {
        'function_id': COLUMN_SYNONYMS['function_id'],
        'failure_mode': COLUMN_SYNONYMS['failure_mode'],
        'local_effect': COLUMN_SYNONYMS['local_effect'],
        'next_higher_effect': COLUMN_SYNONYMS['next_higher_effect'],
        'end_effect': COLUMN_SYNONYMS['end_effect'],
    },
    'PIECEPART_MERGE_SOURCE': {
        'ref_des': COLUMN_SYNONYMS['ref_des'],
        'failure_mode': COLUMN_SYNONYMS['failure_mode'],
        'fmea_id': COLUMN_SYNONYMS['fmea_id'],
        'part_number': COLUMN_SYNONYMS['part_number'],
        'part_usage': COLUMN_SYNONYMS['part_usage'],
        'local_effect': COLUMN_SYNONYMS['local_effect'],
        'next_higher_effect': COLUMN_SYNONYMS['next_higher_effect'],
        'end_effect': COLUMN_SYNONYMS['end_effect'],
    },
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_synonyms(column_key: str) -> List[str]:
    """
    Get the list of synonyms for a standard column key.

    Args:
        column_key: Standard column identifier (e.g., 'ref_des', 'part_number')

    Returns:
        List of possible column names for that column type

    Raises:
        KeyError: If column_key is not recognized

    Example:
        >>> get_synonyms('ref_des')
        ['RefDes', 'Reference Designator', 'Reference Designators', ...]
    """
    if column_key not in COLUMN_SYNONYMS:
        raise KeyError(f"Unknown column key: '{column_key}'. "
                       f"Valid keys: {list(COLUMN_SYNONYMS.keys())}")
    return COLUMN_SYNONYMS[column_key]


def get_file_config(file_type: str) -> Dict[str, List[str]]:
    """
    Get the column configuration for a specific file type.

    Args:
        file_type: File type identifier (e.g., 'BOM', 'HDA', 'FAILURE_MODES')

    Returns:
        Dictionary mapping standard column keys to their synonyms

    Raises:
        KeyError: If file_type is not recognized
    """
    if file_type not in HEADER_CONFIG:
        raise KeyError(f"Unknown file type: '{file_type}'. "
                       f"Valid types: {list(HEADER_CONFIG.keys())}")
    return HEADER_CONFIG[file_type]


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    'COLUMN_SYNONYMS',
    'HEADER_CONFIG',
    'get_synonyms',
    'get_file_config',
]
