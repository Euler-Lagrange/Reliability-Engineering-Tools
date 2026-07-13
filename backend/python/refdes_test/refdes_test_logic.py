"""
RefDes backend router (NextGen + legacy).

Despite the ``refdes_test`` package name, this module is on the PRODUCTION path:
the shipping RefDes Extractor (``refdes_extract``) calls
``extract_with_geometry_analysis_detailed`` here, and with the default
``backend_mode="auto"`` it runs the NextGen engine FIRST, falling back to the
legacy refdes_extractor_logic engine only on an exception. Do NOT treat NextGen
or this router as dead/experimental — deleting them breaks the default extraction
path. ``backend_mode="legacy"`` forces the old engine.
"""
from __future__ import annotations

import re
import threading
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

from .refdes_darkstar_shared import (
    REFDES_BLACKLIST,
    POWER_SOURCE_RE,
    REFDES_RE,
    _BLACKLIST_UPPER,
    strip_mode_suffix,
    strip_suffix,
)

from common import CancellationError, canonicalize_refdes, ensure_file_available, get_tool_logger, try_read_table

_logger = get_tool_logger("refdes_test_logic")

if TYPE_CHECKING:
    import fitz
    import pandas as pd

_legacy = None
_nextgen = None


def _get_legacy_module():
    global _legacy
    if _legacy is None:
        from refdes_extractor import refdes_extractor_logic as legacy_module
        _legacy = legacy_module
    return _legacy


def _get_nextgen_module():
    global _nextgen
    if _nextgen is None:
        try:
            from . import nextgen_engine as nextgen_module
        except ImportError:
            import nextgen_engine as nextgen_module
        _nextgen = nextgen_module
    return _nextgen


def detect_groups(*args, **kwargs):
    return _get_legacy_module().detect_groups(*args, **kwargs)


def detect_groups_with_fallback(*args, **kwargs):
    return _get_legacy_module().detect_groups_with_fallback(*args, **kwargs)


def load_pinlist(*args, **kwargs):
    return _get_legacy_module().load_pinlist(*args, **kwargs)

# Common page/sheet BOM column names (normalized to uppercase)
_BOM_PAGE_COLUMN_CANDIDATES = (
    "SHEET",
    "SHEET NUMBER",
    "PAGE",
    "PAGE NUMBER",
    "SCHEMATIC PAGE",
    "SCHEMATIC SHEET",
    "DRAWING PAGE",
)


def extract_annotations_from_doc(
    doc: "fitz.Document",
    stop_event=None,
    log_func=None,
    page_timeout: float = 30.0,
    max_timeouts: int = 3,
    timed_out_pages: Optional[List[int]] = None,
) -> List[dict]:
    """
    Extract PDF annotations from an already-open document with per-page timeouts.

    Handles zombie thread cleanup internally so the caller can safely continue
    using the document after this returns.

    Wave R2: ``page_timeout`` defaults to 30s (the old 10s was exceeded by
    real dense schematic sheets, silently dropping every group on the page)
    and is runtime-configurable via ``annotation_page_timeout_seconds``.
    When ``timed_out_pages`` is provided, each skipped page's 1-based number
    is appended so the caller can surface the loss in the run result instead
    of only the log.

    Returns:
        List of annotation dicts with rect, page, type keys.

    Raises:
        CancellationError: If stop_event is set.
        RuntimeError: If too many pages timeout during extraction.
    """
    log = log_func or (lambda _msg: None)
    annotations: List[dict] = []
    annot_timeout_count = 0

    _active_threads: List[threading.Thread] = []
    _thread_lock = threading.Lock()

    def _extract_page(page_ref: "fitz.Page", page_num: int, result: dict) -> None:
        try:
            page_annots = []
            recovered = 0
            words_cache = None
            annots = page_ref.annots()
            if annots:
                for ann in annots:
                    info = dict(ann.info or {})
                    rect = tuple(ann.rect.normalize())
                    if not str(info.get("content") or "").strip():
                        # Wave R3 (DIG-4xx trigger): some tools store FreeText
                        # only in the appearance stream — PyMuPDF's
                        # info["content"] reads /Contents only, so the label
                        # arrives empty and the group silently vanishes.
                        # Recover the visible text from the page textpage
                        # clipped to the annotation rect (annotation
                        # appearance text IS part of the page textpage). This
                        # runs inside the page's timeout thread, so the extra
                        # read stays bounded by page_timeout.
                        if words_cache is None:
                            words_cache = page_ref.get_text("words") or []
                        x0, y0, x1, y1 = rect
                        inside = [
                            w
                            for w in words_cache
                            if x0 <= (w[0] + w[2]) / 2 <= x1
                            and y0 <= (w[1] + w[3]) / 2 <= y1
                            and (w[4] or "").strip()
                        ]
                        recovered_text = " ".join(
                            (w[4] or "").strip()
                            for w in sorted(inside, key=lambda w: (w[1], w[0]))
                        )
                        if recovered_text:
                            info["content"] = recovered_text
                            recovered += 1
                    info["rect"] = rect
                    info["page"] = page_num
                    info["type"] = ann.type[1]
                    page_annots.append(info)
            result["result"] = page_annots
            result["recovered"] = recovered
            result["done"] = True
        except Exception as e:
            _logger.warning(f"Page {page_num + 1} annotation extraction error: {e}")
            result["done"] = True

    def _extract_with_timeout(page_ref: "fitz.Page", page_num: int) -> tuple:
        result = {"result": [], "done": False}
        thread = threading.Thread(
            target=_extract_page, args=(page_ref, page_num, result), daemon=True
        )
        with _thread_lock:
            _active_threads.append(thread)
        thread.start()
        thread.join(timeout=page_timeout)
        if result["done"]:
            with _thread_lock:
                if thread in _active_threads:
                    _active_threads.remove(thread)
            return result["result"], False, result.get("recovered", 0)
        return [], True, 0

    def _wait_for_threads(timeout_each: float = 2.0) -> int:
        with _thread_lock:
            waiting = list(_active_threads)
            _active_threads.clear()
        zombie_count = 0
        for t in waiting:
            if t.is_alive():
                zombie_count += 1
                t.join(timeout=timeout_each)
                if t.is_alive():
                    _logger.warning(
                        f"Annotation thread did not finish within {timeout_each}s cleanup window"
                    )
        return zombie_count

    abort = False
    try:
        for i, page_ref in enumerate(doc):
            if stop_event and stop_event.is_set():
                raise CancellationError("Cancelled during annotation extraction.")

            page_annots, timed_out, recovered = _extract_with_timeout(page_ref, i)
            if timed_out:
                annot_timeout_count += 1
                if timed_out_pages is not None:
                    timed_out_pages.append(i + 1)
                log(
                    f"WARNING: Page {i + 1}: annotation extraction timed out "
                    f"after {page_timeout:.0f}s - skipping annotations"
                )
                if annot_timeout_count >= max_timeouts:
                    log(
                        f"ERROR: Too many pages timed out "
                        f"({annot_timeout_count}/{max_timeouts}). Aborting extraction."
                    )
                    abort = True
                    break
            else:
                annotations.extend(page_annots)
                if recovered:
                    log(
                        f"Recovered text for {recovered} annotation(s) with "
                        f"empty content on page {i + 1}"
                    )
    finally:
        zombie_count = _wait_for_threads(timeout_each=2.0)
        if zombie_count > 0:
            log(f"Cleaned up {zombie_count} background extraction thread(s)")

    if abort:
        raise RuntimeError(
            f"Too many pages timed out during annotation extraction "
            f"({annot_timeout_count}/{max_timeouts}). "
            "PDF may be corrupted or extremely complex."
        )

    if len(annotations) > 1000:
        log(f"WARNING: Large PDF with {len(annotations)} annotations - may use significant memory")

    return annotations


def _normalize_backend_mode(config, backend_override: Optional[str] = None) -> str:
    """Resolve backend mode from config with safe default."""
    if backend_override:
        mode = str(backend_override).strip().lower()
        if mode in {"legacy", "nextgen", "auto"}:
            return mode

    if config is None:
        return "auto"

    raw = config.get("backend_mode", config.get("refdes_test_backend_mode", "auto"))
    mode = str(raw or "auto").strip().lower()
    if mode in {"legacy", "nextgen", "auto"}:
        return mode
    _logger.warning(f"Unknown backend mode '{raw}', defaulting to auto")
    return "auto"


def _run_legacy(
    pdf_path: Path,
    groups: list,
    bom_set: set,
    config,
    pinlist_set: Optional[set],
    debug_pdf_path: Path,
    log_func,
    progress_func,
    status_func,
    stop_event,
) -> list:
    legacy = _get_legacy_module()
    return legacy.extract_with_geometry_analysis(
        pdf_path,
        groups,
        bom_set,
        config=config,
        pinlist_set=pinlist_set,
        debug_pdf_path=debug_pdf_path,
        log_func=log_func,
        progress_func=progress_func,
        status_func=status_func,
        stop_event=stop_event,
    )


def _run_nextgen(
    pdf_path: Path,
    groups: list,
    bom_set: set,
    config,
    pinlist_set: Optional[set],
    debug_pdf_path: Path,
    log_func,
    progress_func,
    status_func,
    stop_event,
    bom_page_map: Optional[Dict[str, Set[int]]] = None,
    doc=None,
    diagnostics: Optional[dict] = None,
) -> list:
    nextgen = _get_nextgen_module()
    return nextgen.extract_with_geometry_analysis(
        pdf_path,
        groups,
        bom_set,
        config=config,
        pinlist_set=pinlist_set,
        debug_pdf_path=debug_pdf_path,
        log_func=log_func,
        progress_func=progress_func,
        status_func=status_func,
        stop_event=stop_event,
        bom_page_map=bom_page_map,
        doc=doc,
        diagnostics=diagnostics,
    )


def extract_with_geometry_analysis_detailed(
    pdf_path: Path,
    groups: list,
    bom_set: set,
    config=None,
    pinlist_set: Optional[set] = None,
    debug_pdf_path: Path = None,
    log_func=None,
    progress_func=None,
    status_func=None,
    stop_event=None,
    bom_page_map: Optional[Dict[str, Set[int]]] = None,
    backend_override: Optional[str] = None,
    doc=None,
) -> Tuple[list, dict]:
    """
    Route extraction to selected backend and return execution details.

    Returns:
        (results, details)
        details = {
            "backend_requested": str,
            "backend_used": str,
            "fallback_reason": str,
            "token_diagnostics": dict,  # {token: {group, pages, confidence?, source?, candidates?, parent?}}
            "orphan_pins": list,        # [{page, group, pin_text, disposition, detail}]
        }

    The diagnostics keys are populated only by the NextGen backend; legacy
    runs (including auto-mode fallback) leave them empty.
    """
    mode = _normalize_backend_mode(config, backend_override=backend_override)
    details = {
        "backend_requested": mode,
        "backend_used": mode,
        "fallback_reason": "",
        "token_diagnostics": {},
        "orphan_pins": [],
    }
    diagnostics_acc: dict = {}

    def _adopt_diagnostics() -> None:
        details["token_diagnostics"] = diagnostics_acc.get("token_diagnostics", {})
        details["orphan_pins"] = diagnostics_acc.get("orphan_pins", [])

    if mode == "legacy":
        if log_func:
            log_func("[RefDes Test] Backend mode: legacy")
        return (
            _run_legacy(
                pdf_path,
                groups,
                bom_set,
                config,
                pinlist_set,
                debug_pdf_path,
                log_func,
                progress_func,
                status_func,
                stop_event,
            ),
            details,
        )

    if mode == "nextgen":
        if log_func:
            log_func("[RefDes Test] Backend mode: nextgen")
        results = _run_nextgen(
            pdf_path,
            groups,
            bom_set,
            config,
            pinlist_set,
            debug_pdf_path,
            log_func,
            progress_func,
            status_func,
            stop_event,
            bom_page_map=bom_page_map,
            doc=doc,
            diagnostics=diagnostics_acc,
        )
        _adopt_diagnostics()
        return results, details

    if log_func:
        log_func("[RefDes Test] Backend mode: auto (nextgen with legacy fallback)")

    try:
        results = _run_nextgen(
            pdf_path,
            groups,
            bom_set,
            config,
            pinlist_set,
            debug_pdf_path,
            log_func,
            progress_func,
            status_func,
            stop_event,
            bom_page_map=bom_page_map,
            doc=doc,
            diagnostics=diagnostics_acc,
        )
        details["backend_used"] = "nextgen"
        _adopt_diagnostics()
        return results, details
    except (CancellationError, InterruptedError):
        raise
    except Exception as ex:
        details["backend_used"] = "legacy"
        details["fallback_reason"] = str(ex)
        if log_func:
            log_func(f"[RefDes Test] NextGen failed: {ex}; falling back to legacy.")
        _logger.exception("RefDes Test nextgen backend failed; falling back to legacy")
        results = _run_legacy(
            pdf_path,
            groups,
            bom_set,
            config,
            pinlist_set,
            debug_pdf_path,
            log_func,
            progress_func,
            status_func,
            stop_event,
        )
        return results, details


def extract_with_geometry_analysis(
    pdf_path: Path,
    groups: list,
    bom_set: set,
    config=None,
    pinlist_set: Optional[set] = None,
    debug_pdf_path: Path = None,
    log_func=None,
    progress_func=None,
    status_func=None,
    stop_event=None,
    bom_page_map: Optional[Dict[str, Set[int]]] = None,
    backend_override: Optional[str] = None,
    doc=None,
) -> list:
    """Compatibility wrapper returning results only."""
    results, _details = extract_with_geometry_analysis_detailed(
        pdf_path=pdf_path,
        groups=groups,
        bom_set=bom_set,
        config=config,
        pinlist_set=pinlist_set,
        debug_pdf_path=debug_pdf_path,
        log_func=log_func,
        progress_func=progress_func,
        status_func=status_func,
        stop_event=stop_event,
        bom_page_map=bom_page_map,
        backend_override=backend_override,
        doc=doc,
    )
    return results


def _find_refdes_column(df: "pd.DataFrame", ref_col_name: str = "Auto-Detect") -> Optional[str]:
    """Detect BOM RefDes column using legacy-compatible heuristics."""
    if ref_col_name and ref_col_name != "Auto-Detect":
        return ref_col_name if ref_col_name in df.columns else None

    possible = [
        "RefDes",
        "RefDeses",
        "Reference Designator",
        "Reference",
        "Designator",
        "Ref",
        "Part Reference",
    ]
    cols_upper = {str(c).strip().upper(): c for c in df.columns}
    for name in possible:
        if name.upper() in cols_upper:
            return cols_upper[name.upper()]

    for c in df.columns:
        sample = df[c].dropna().astype(str).head(20)
        if sample.empty:
            continue
        if sample.str.match(REFDES_RE).sum() > (len(sample) * 0.5):
            return c

    return None


def _find_page_column(df: pd.DataFrame) -> Optional[str]:
    """Detect optional page/sheet column in BOM."""
    cols_upper = {str(c).strip().upper(): c for c in df.columns}

    # Exact priority matches first
    for key in _BOM_PAGE_COLUMN_CANDIDATES:
        if key in cols_upper:
            return cols_upper[key]

    # Relaxed substring matching
    for u_name, original in cols_upper.items():
        if "SHEET" in u_name or "PAGE" in u_name:
            return original

    return None


def _parse_page_numbers(raw_value) -> Set[int]:
    """Parse page/sheet values like '12', '1,2,3', '4-6', 'Sheet 7'."""
    if raw_value is None:
        return set()

    text = str(raw_value).strip()
    if not text:
        return set()

    # Normalize obvious labels
    cleaned = re.sub(r"(?i)\b(sheet|sht|page|pg|number|no\.?|#)\b", " ", text)

    pages: Set[int] = set()

    # Parse ranges first
    for m in re.finditer(r"(\d{1,4})\s*-\s*(\d{1,4})", cleaned):
        start = int(m.group(1))
        end = int(m.group(2))
        if start > end:
            start, end = end, start
        if end - start <= 200:  # safety cap
            pages.update(range(start, end + 1))

    # Remove processed ranges to avoid duplicate parsing
    cleaned = re.sub(r"\d{1,4}\s*-\s*\d{1,4}", " ", cleaned)

    for tok in re.split(r"[\s,;/|]+", cleaned):
        tok = tok.strip()
        if not tok:
            continue
        if tok.isdigit():
            pages.add(int(tok))

    # Keep plausible page numbers only
    return {p for p in pages if 0 < p < 10000}


def load_bom_with_metadata(
    bom_path: Path,
    ref_col_name: str = "Auto-Detect",
    log_func=None,
    sheet_name=None,
) -> Tuple[Set[str], Dict[str, Set[int]]]:
    """
    Load BOM RefDes and optional page metadata map.

    Returns:
        (bom_refdes_set, bom_page_map)
        - bom_refdes_set: canonical base RefDes values
        - bom_page_map: {canonical_base_refdes: {page_numbers}}
    """
    from refdes_extractor.bom_loader import load_bom_with_metadata as shared_load_bom_with_metadata

    return shared_load_bom_with_metadata(
        bom_path=bom_path,
        ref_col_name=ref_col_name,
        log_func=log_func or print,
        sheet_name=sheet_name,
    )


def load_bom(bom_path: Path, ref_col_name: str = "Auto-Detect", log_func=None, sheet_name=None) -> Set[str]:
    """Compatibility wrapper returning only BOM RefDes set."""
    refs, _page_map = load_bom_with_metadata(
        bom_path=bom_path,
        ref_col_name=ref_col_name,
        log_func=log_func,
        sheet_name=sheet_name,
    )
    return refs


