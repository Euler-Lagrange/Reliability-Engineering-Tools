# -*- coding: utf-8 -*-
"""Shared BOM loading helpers for RefDes workflows."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
import json
import re
from typing import Dict, Optional, Set, Tuple

import pandas as pd

from common import get_tool_logger
from common.column_synonyms import get_synonyms
from common.refdes_utils import IEEE_315_PREFIXES, canonicalize_refdes
from common.utils import detect_column, ensure_file_available, try_read_table

_logger = get_tool_logger("refdes_bom_loader")

BASE_MODE = "base"
EXACT_MODE = "exact"

_BASE_MODE_REFDES_COLUMN_CANDIDATES = [
    "RefDes",
    "RefDeses",
    "Reference Designator",
    "Reference",
    "Designator",
    "Ref",
    "Part Reference",
]

_BOM_PAGE_COLUMN_CANDIDATES = [
    "SHEET",
    "SHEET NO",
    "SHEET NO.",
    "SHEET NUMBER",
    "PAGE",
    "PAGE NO",
    "PAGE NO.",
    "PAGE NUMBER",
]

_PAGE_COLUMN_REJECT_PHRASES = (
    "DATASHEET",
    "SHEETMETAL",
)

# Description-column candidates, precise-first. The shared ``description``
# synonym table leads with the generic ``Name`` (a net/component name), which
# would shadow a real ``Description`` column for coverage enrichment, so we
# curate the order locally rather than reorder the global table.
_DESCRIPTION_COLUMN_PRIORITY = [
    "Description",
    "Part Description",
    "Primary Part Description",
    "Item Description",
    "Component Description",
    "Part_Description",
    "Desc",
    "PartDesc",
    "Part Name",
    "Component Name",
    "Name",
]


@dataclass(frozen=True)
class BomLoadResult:
    """Normalized BOM load result shared by RefDes tools."""

    refdes: Set[str]
    page_map: Dict[str, Set[int]]
    refdes_column: Optional[str] = None
    page_column: Optional[str] = None
    # {normalized_refdes: {"part_number", "description"}} — only populated when
    # ``include_component_metadata`` is requested. Keyed identically to ``refdes``.
    meta: Dict[str, Dict[str, str]] = field(default_factory=dict)


def _load_configured_ref_prefixes() -> list[str]:
    prefixes = list(IEEE_315_PREFIXES)
    config_file = Path.home() / ".refdes_extractor_config.json"
    if not config_file.exists():
        return prefixes
    try:
        with open(config_file, "r", encoding="utf-8") as handle:
            custom = json.load(handle)
        for prefix in custom.get("ref_prefixes", []):
            normalized = str(prefix).strip().upper()
            if normalized and normalized not in prefixes:
                prefixes.append(normalized)
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as ex:
        _logger.warning("Failed to load custom RefDes prefixes: %s", ex)
    return prefixes


def _build_refdes_pattern(prefixes: list[str]) -> re.Pattern[str]:
    prefix_pattern = "|".join(sorted(prefixes, key=len, reverse=True))
    return re.compile(rf"\b(?:{prefix_pattern})\d+[A-Z]?\b", re.I)


def strip_instance_suffix(refdes: str, prefixes: Optional[list[str]] = None) -> str:
    """Normalize instance suffixes like ``R1A`` to ``R1``."""
    normalized = canonicalize_refdes(refdes)
    if not normalized or normalized.isalpha():
        return normalized
    prefix_list = prefixes or _load_configured_ref_prefixes()
    prefix_pattern = "|".join(sorted(prefix_list, key=len, reverse=True))
    instance_suffix_re = re.compile(rf"^({prefix_pattern})(\d+)([A-Z])?$", re.I)
    match = instance_suffix_re.fullmatch(normalized)
    if match:
        return f"{match.group(1)}{match.group(2)}".upper()
    return normalized


def _clean_cell(value) -> str:
    """Coerce a DataFrame cell to a trimmed string, NaN/None -> ''."""
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _find_metadata_column(df: pd.DataFrame, synonyms: list[str]) -> Optional[str]:
    """Case-insensitive exact match of a column header against synonyms."""
    cols_upper = {str(col).strip().upper(): col for col in df.columns}
    for candidate in synonyms:
        resolved = cols_upper.get(str(candidate).strip().upper())
        if resolved:
            return resolved
    return None


def _find_base_refdes_column(
    df: pd.DataFrame,
    ref_col_name: str,
    refdes_pattern: re.Pattern[str],
) -> Optional[str]:
    if ref_col_name and ref_col_name != "Auto-Detect":
        return ref_col_name if ref_col_name in df.columns else None

    cols_upper = {str(col).strip().upper(): col for col in df.columns}
    for candidate in _BASE_MODE_REFDES_COLUMN_CANDIDATES:
        resolved = cols_upper.get(candidate.upper())
        if resolved:
            return resolved

    for col in df.columns:
        sample = df[col].dropna().astype(str).head(20)
        if sample.empty:
            continue
        matching = 0
        for value in sample:
            for token in re.split(r"[,\s;]+", str(value)):
                normalized = canonicalize_refdes(token)
                if normalized and refdes_pattern.fullmatch(normalized):
                    matching += 1
                    break
        if matching > (len(sample) * 0.5):
            return col

    return None


def _find_exact_refdes_column(df: pd.DataFrame, ref_col_name: str) -> Optional[str]:
    direct = detect_column(df.columns.tolist(), [ref_col_name])
    if direct:
        return direct
    return detect_column(df.columns.tolist(), get_synonyms("ref_des"))


def _find_refdes_column(
    df: pd.DataFrame,
    ref_col_name: str,
    *,
    mode: str,
    refdes_pattern: Optional[re.Pattern[str]] = None,
) -> Optional[str]:
    if mode == EXACT_MODE:
        return _find_exact_refdes_column(df, ref_col_name=ref_col_name)
    if refdes_pattern is None:
        raise ValueError("Base-mode BOM loading requires a RefDes regex.")
    return _find_base_refdes_column(df, ref_col_name=ref_col_name, refdes_pattern=refdes_pattern)


def _find_page_column(df: pd.DataFrame) -> Optional[str]:
    cols_upper = {str(col).strip().upper(): col for col in df.columns}
    for candidate in _BOM_PAGE_COLUMN_CANDIDATES:
        resolved = cols_upper.get(candidate)
        if resolved:
            return resolved
    for upper_name, original in cols_upper.items():
        compact = re.sub(r"[^A-Z0-9]+", "", upper_name)
        if any(phrase in compact for phrase in _PAGE_COLUMN_REJECT_PHRASES):
            continue

        tokens = re.findall(r"[A-Z0-9]+", upper_name)
        if not any(token in {"SHEET", "SHEETS", "PAGE", "PAGES"} for token in tokens):
            continue

        sample = df[original].dropna().head(20)
        if sample.empty:
            continue

        parsed = 0
        for value in sample:
            if _parse_page_numbers(value):
                parsed += 1
        if parsed >= max(1, len(sample) // 2):
            return original
    return None


def _parse_page_numbers(raw_value) -> Set[int]:
    if raw_value is None:
        return set()

    text = str(raw_value).strip()
    if not text:
        return set()

    cleaned = re.sub(r"(?i)\b(sheet|sht|page|pg|number|no\.?|#)\b", " ", text)
    pages: Set[int] = set()

    for match in re.finditer(r"(\d{1,4})\s*-\s*(\d{1,4})", cleaned):
        start = int(match.group(1))
        end = int(match.group(2))
        if start > end:
            start, end = end, start
        if end - start <= 200:
            pages.update(range(start, end + 1))

    cleaned = re.sub(r"\d{1,4}\s*-\s*\d{1,4}", " ", cleaned)
    for token in re.split(r"[\s,;/|]+", cleaned):
        token = token.strip()
        if token.isdigit():
            pages.add(int(token))

    return {page for page in pages if 0 < page < 10000}


def _iter_tokens(raw_value, *, mode: str) -> list[str]:
    if pd.isna(raw_value):
        return []
    s = str(raw_value)
    if s.lower() == "nan":
        return []
    if mode == EXACT_MODE:
        return [s]
    return re.split(r"[,\s;]+", s)


def _normalize_token(
    token: str,
    *,
    mode: str,
    refdes_pattern: Optional[re.Pattern[str]] = None,
    prefixes: Optional[list[str]] = None,
) -> str:
    normalized = canonicalize_refdes(token)
    if not normalized:
        return ""
    if mode == EXACT_MODE:
        return normalized
    if refdes_pattern is None or prefixes is None:
        raise ValueError("Base-mode token normalization requires regex and prefixes.")
    if not refdes_pattern.fullmatch(normalized):
        # Pin-style BOM entry ("U7-38"): piece-part BOMs list component-pin
        # rows. In BASE (component-level) mode such a row is evidence that
        # its parent component exists — reduce it to the base instead of
        # dropping the row. Dropping it silently un-verified every extracted
        # pin of that component (U7-38 landed in "(Unverified)" even though
        # the BOM listed it).
        if "-" in normalized:
            head = normalized.split("-", 1)[0].strip()
            if head and refdes_pattern.fullmatch(head):
                return strip_instance_suffix(head, prefixes=prefixes)
        return ""
    return strip_instance_suffix(normalized, prefixes=prefixes)


def load_bom_data(
    bom_path: Path | str,
    ref_col_name: str = "Auto-Detect",
    log_func=None,
    sheet_name=None,
    *,
    include_page_metadata: bool = False,
    include_component_metadata: bool = False,
    mode: str = BASE_MODE,
) -> BomLoadResult:
    """Load normalized RefDes data from a BOM file."""

    if mode not in {BASE_MODE, EXACT_MODE}:
        raise ValueError(f"Unsupported BOM load mode: {mode}")

    _log_func = log_func or (lambda _msg: None)

    def log(message: str) -> None:
        _log_func(message)
        _logger.info(message)

    resolved_path = Path(bom_path)
    log(f"Reading BOM: {resolved_path.name}")
    resolved_path = ensure_file_available(resolved_path, log)

    refs: Set[str] = set()
    page_map: Dict[str, Set[int]] = defaultdict(set)
    prefixes = _load_configured_ref_prefixes() if mode == BASE_MODE else None
    refdes_pattern = _build_refdes_pattern(prefixes) if prefixes else None

    try:
        df = try_read_table(str(resolved_path), sheet_name=sheet_name, log_func=log)
        ref_col = _find_refdes_column(
            df,
            ref_col_name=ref_col_name,
            mode=mode,
            refdes_pattern=refdes_pattern,
        )
        if not ref_col:
            raise ValueError("BOM file is missing a recognizable RefDes column.")

        page_col = _find_page_column(df) if include_page_metadata else None
        if page_col:
            log(f"  Detected BOM page column: '{page_col}'")

        meta: Dict[str, Dict[str, str]] = {}
        pn_col = desc_col = None
        if include_component_metadata:
            pn_col = _find_metadata_column(df, get_synonyms("part_number"))
            desc_col = _find_metadata_column(df, _DESCRIPTION_COLUMN_PRIORITY)

        for _, row in df.iterrows():
            raw_ref = row.get(ref_col)
            if pd.isna(raw_ref):
                continue

            pages = _parse_page_numbers(row.get(page_col)) if page_col else set()
            row_pn = _clean_cell(row.get(pn_col)) if pn_col else ""
            row_desc = _clean_cell(row.get(desc_col)) if desc_col else ""
            for token in _iter_tokens(raw_ref, mode=mode):
                normalized = _normalize_token(
                    token,
                    mode=mode,
                    refdes_pattern=refdes_pattern,
                    prefixes=prefixes,
                )
                if not normalized:
                    continue
                refs.add(normalized)
                if pages:
                    page_map[normalized].update(pages)
                # First non-blank metadata for a RefDes wins; always seed the
                # key (even blank) so coverage lookups are predictable.
                if include_component_metadata and normalized not in meta:
                    meta[normalized] = {"part_number": row_pn, "description": row_desc}

        log(f"  Loaded {len(refs)} components from BOM.")
        if page_map:
            log(f"  Loaded BOM page metadata for {len(page_map)} component(s).")

        return BomLoadResult(
            refdes=refs,
            page_map={key: set(values) for key, values in page_map.items()},
            refdes_column=ref_col,
            page_column=page_col,
            meta=meta,
        )
    except Exception as ex:
        raise RuntimeError(f"Failed to read BOM: {ex}") from ex


def load_bom(
    bom_path: Path | str,
    ref_col_name: str = "Auto-Detect",
    log_func=None,
    sheet_name=None,
) -> Set[str]:
    """Load BOM data in extractor/test base-refdes mode."""
    return load_bom_data(
        bom_path=bom_path,
        ref_col_name=ref_col_name,
        log_func=log_func,
        sheet_name=sheet_name,
        mode=BASE_MODE,
    ).refdes


def load_bom_exact(
    bom_path: Path | str,
    ref_col_name: str = "RefDes",
    log_func=None,
    sheet_name=None,
) -> Set[str]:
    """Load BOM data in verifier exact-token mode."""
    return load_bom_data(
        bom_path=bom_path,
        ref_col_name=ref_col_name,
        log_func=log_func,
        sheet_name=sheet_name,
        mode=EXACT_MODE,
    ).refdes


def load_bom_with_metadata(
    bom_path: Path | str,
    ref_col_name: str = "Auto-Detect",
    log_func=None,
    sheet_name=None,
) -> Tuple[Set[str], Dict[str, Set[int]]]:
    """Load BOM data plus optional page metadata in base-refdes mode."""
    result = load_bom_data(
        bom_path=bom_path,
        ref_col_name=ref_col_name,
        log_func=log_func,
        sheet_name=sheet_name,
        include_page_metadata=True,
        mode=BASE_MODE,
    )
    return result.refdes, result.page_map


__all__ = [
    "BASE_MODE",
    "BomLoadResult",
    "EXACT_MODE",
    "load_bom",
    "load_bom_data",
    "load_bom_exact",
    "load_bom_with_metadata",
    "strip_instance_suffix",
]
