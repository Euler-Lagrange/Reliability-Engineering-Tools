"""
RefDes NextGen extraction engine.

This is the DEFAULT production backend for the shipping RefDes Extractor tool
(the ``refdes_extract`` workflow). refdes_extractor/runtime.py defaults
``backend_mode="auto"``, and refdes_test_logic.extract_with_geometry_analysis_detailed
runs NextGen FIRST under "auto", falling back to the legacy
refdes_extractor_logic engine only on an exception. Despite the ``refdes_test``
package name, this is NOT experimental / test-only code — deleting it breaks the
default extraction path. It routes around the legacy extractor without modifying it.

Key difference vs the legacy harvest_hybrid path:
- Pin label mappings are resolved from candidate lists only.
- No page-level (page,label) exact-map overwrite path that can leak J1-1
  into unrelated groups when labels like "1" are duplicated.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import re
import threading
import time
from datetime import datetime
from collections import defaultdict
from contextlib import nullcontext
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

import fitz

from common import (
    CancellationError,
    ConfigManager,
    ProcessingError,
    canonicalize_refdes,
    check_cancelled,
    ensure_file_available,
    get_prefix,
    get_tool_logger,
    should_analyze_pins,
)

from refdes_extractor import extraction_engine as legacy_engine
from refdes_extractor import geometry_analyzer as ga
from refdes_extractor.group_detection import area_of, center, point_in_rect
from refdes_extractor.pinlist_parenting import (
    DEFAULT_PIN_PARENT_PREFIX_ALLOWLIST,
    qualify_pins_via_pinlist,
)
from refdes_extractor import refdes_extractor_logic as legacy_logic

_logger = get_tool_logger("refdes_test_nextgen")

# Default cell size for spatial grid (px). Typical annotation widths are 50-200px.
_GRID_CELL_SIZE = 100
_DEFAULT_BATCH_SIZE = 10
_DEFAULT_ADAPTIVE_MAX_PAGES = 10
_DEFAULT_ADAPTIVE_ORPHAN_THRESHOLD = 5
_DEFAULT_ADAPTIVE_ORPHAN_RATIO = 0.30
_DEFAULT_BATCH_TIMEOUT_SECONDS = 240.0


def _build_group_grid(groups: list, cell_size: int = _GRID_CELL_SIZE) -> dict:
    """Build a spatial hash grid for fast point-in-group lookups."""
    grid = defaultdict(list)
    for g in groups:
        r = g["rect"]
        x0, y0, x1, y1 = r[0], r[1], r[2], r[3]
        cx0 = int(x0 // cell_size)
        cy0 = int(y0 // cell_size)
        cx1 = int(x1 // cell_size)
        cy1 = int(y1 // cell_size)
        for gx in range(cx0, cx1 + 1):
            for gy in range(cy0, cy1 + 1):
                grid[(gx, gy)].append(g)
    return grid


def _lookup_group(grid: dict, cx: float, cy: float, cell_size: int = _GRID_CELL_SIZE):
    """Find the smallest group containing point (cx, cy) using the grid index."""
    cell = (int(cx // cell_size), int(cy // cell_size))
    for g in grid.get(cell, ()):
        if point_in_rect(cx, cy, g["rect"]):
            return g
    return None


def _extract_base_refdes(component: str) -> Optional[str]:
    """Extract base RefDes from token for BOM verification."""
    if component is None:
        return None

    token = str(component).strip().upper()
    if not token:
        return None

    if token.endswith("[?]"):
        token = token[:-3].strip()

    if token.startswith("PIN-"):
        return None

    if "-" in token:
        token = token.split("-", 1)[0]

    if legacy_logic.REFDES_RE.fullmatch(token):
        return canonicalize_refdes(legacy_logic.strip_suffix(token))
    return None


def _normalize_bom_set(bom_set: Optional[set]) -> set:
    """Canonical BOM normalization for matching."""
    if not bom_set:
        return set()
    normalized = set()
    for item in bom_set:
        if item is None:
            continue
        canon = canonicalize_refdes(legacy_logic.strip_suffix(str(item).strip().upper()))
        if canon:
            normalized.add(canon)
    return normalized


def _normalize_bom_page_map(bom_page_map: Optional[dict]) -> dict:
    """Canonicalize BOM page metadata map: {base_refdes: {page_numbers}}."""
    if not bom_page_map:
        return {}
    normalized = {}
    for raw_ref, raw_pages in bom_page_map.items():
        if raw_ref is None:
            continue
        canon_ref = canonicalize_refdes(legacy_logic.strip_suffix(str(raw_ref).strip().upper()))
        if not canon_ref:
            continue

        pages = set()
        if raw_pages:
            for raw_page in raw_pages:
                try:
                    page_num = int(raw_page)
                except (TypeError, ValueError):
                    continue
                if 0 < page_num < 10000:
                    pages.add(page_num)
        if pages:
            normalized.setdefault(canon_ref, set()).update(pages)
    return normalized


def _chunk_pages(pages: Iterable[int], batch_size: int) -> List[List[int]]:
    """Return sorted page batches with a fixed maximum size."""
    ordered = sorted({int(p) for p in pages if isinstance(p, int) or str(p).isdigit()})
    if not ordered:
        return []
    size = max(1, int(batch_size))
    return [ordered[i : i + size] for i in range(0, len(ordered), size)]


def _parse_tokens(value: str) -> Set[str]:
    if not value:
        return set()
    tokens: Set[str] = set()
    for raw in str(value).split(","):
        token = raw.strip()
        if token:
            tokens.add(token)
    return tokens


def _parse_pages(value: str) -> Set[int]:
    if not value:
        return set()
    pages: Set[int] = set()
    for raw in str(value).split(","):
        token = raw.strip()
        if not token:
            continue
        try:
            pages.add(int(token))
        except ValueError:
            continue
    return pages


def _format_pages(pages: Set[int]) -> str:
    if not pages:
        return ""
    return ", ".join(str(p) for p in sorted(pages))


def _merge_hybrid_results_nextgen(base_results: list, override_results: list) -> list:
    """
    Merge result rows from disjoint page sets.

    - Existing group rows are unioned by tokens and pages.
    - Gap rows from partial passes are ignored.
    """
    merged = [dict(row) for row in (base_results or [])]
    index = {row.get("group"): i for i, row in enumerate(merged) if row.get("group")}

    for row in (override_results or []):
        if row.get("_is_gap"):
            continue
        group = row.get("group")
        if not group:
            continue

        tokens = _parse_tokens(row.get("failure mode causes", ""))
        pages = _parse_pages(row.get("pages", ""))

        if group in index:
            base_row = merged[index[group]]
            merged_tokens = _parse_tokens(base_row.get("failure mode causes", "")) | tokens
            merged_pages = _parse_pages(base_row.get("pages", "")) | pages
            base_row["failure mode causes"] = (
                ", ".join(sorted(merged_tokens, key=legacy_engine.natural_key)) if merged_tokens else ""
            )
            base_row["component count"] = len(merged_tokens)
            base_row["pages"] = _format_pages(merged_pages)
            continue

        new_row = dict(row)
        new_row["failure mode causes"] = (
            ", ".join(sorted(tokens, key=legacy_engine.natural_key)) if tokens else ""
        )
        new_row["component count"] = len(tokens)
        new_row["pages"] = _format_pages(pages)
        merged.append(new_row)
        index[group] = len(merged) - 1

    def _group_base_name(group: str) -> str:
        name = str(group or "").strip()
        upper = name.upper()
        if upper.endswith(" (GROUP NOT DETECTED)"):
            name = name[: -len(" (GROUP NOT DETECTED)")].rstrip()
            upper = name.upper()
        if upper.endswith(" (VERIFIED)"):
            name = name[: -len(" (VERIFIED)")].rstrip()
        elif upper.endswith(" (UNVERIFIED)"):
            name = name[: -len(" (UNVERIFIED)")].rstrip()
        elif upper.endswith(" (PARTIAL)"):
            name = name[: -len(" (PARTIAL)")].rstrip()
        return name

    def _group_status(group: str) -> Optional[str]:
        upper = str(group or "").strip().upper()
        if upper.endswith(" (VERIFIED)"):
            return "verified"
        if upper.endswith(" (UNVERIFIED)"):
            return "unverified"
        if upper.endswith(" (PARTIAL)"):
            return "partial"
        return None

    # Reconcile Verified/Unverified pairs for each base group so tokens don't
    # appear in both rows after partial-pass merges.
    buckets: Dict[str, dict] = {}
    for i, row in enumerate(merged):
        if row.get("_is_gap"):
            continue
        group = str(row.get("group", ""))
        status = _group_status(group)
        if status not in ("verified", "unverified"):
            continue
        base = _group_base_name(group)
        if not base:
            continue
        bucket = buckets.setdefault(
            base,
            {
                "verified_idx": None,
                "unverified_idx": None,
                "verified_tokens": set(),
                "unverified_tokens": set(),
                "pages": set(),
            },
        )
        bucket[f"{status}_idx"] = i
        bucket[f"{status}_tokens"].update(_parse_tokens(row.get("failure mode causes", "")))
        bucket["pages"].update(_parse_pages(row.get("pages", "")))

    for base, bucket in buckets.items():
        verified_tokens = set(bucket["verified_tokens"])
        unverified_tokens = set(bucket["unverified_tokens"]) - verified_tokens
        pages = _format_pages(set(bucket["pages"]))

        verified_idx = bucket["verified_idx"]
        if verified_idx is None:
            merged.append(
                {
                    "group": f"{base} (Verified)",
                    "failure mode causes": "",
                    "component count": 0,
                    "pages": pages,
                }
            )
            verified_idx = len(merged) - 1
        merged[verified_idx]["failure mode causes"] = (
            ", ".join(sorted(verified_tokens, key=legacy_engine.natural_key)) if verified_tokens else ""
        )
        merged[verified_idx]["component count"] = len(verified_tokens)
        merged[verified_idx]["pages"] = pages

        unverified_idx = bucket["unverified_idx"]
        if unverified_idx is None:
            merged.append(
                {
                    "group": f"{base} (Unverified)",
                    "failure mode causes": "",
                    "component count": 0,
                    "pages": pages,
                }
            )
            unverified_idx = len(merged) - 1
        merged[unverified_idx]["failure mode causes"] = (
            ", ".join(sorted(unverified_tokens, key=legacy_engine.natural_key)) if unverified_tokens else ""
        )
        merged[unverified_idx]["component count"] = len(unverified_tokens)
        merged[unverified_idx]["pages"] = pages

    # Drop stale gap rows once a real row for the same base group exists.
    present_bases = {
        _group_base_name(row.get("group", ""))
        for row in merged
        if not row.get("_is_gap")
    }
    merged = [
        row
        for row in merged
        if not (row.get("_is_gap") and _group_base_name(row.get("group", "")) in present_bases)
    ]

    def _sort_key(row: dict):
        g = str(row.get("group", ""))
        if row.get("_is_gap"):
            return (3, "", g)
        if "UNGROUPED" in g:
            return (2, "", g)
        if "PROVISIONAL" in g:
            return (1, "", g)
        return (0, legacy_engine.natural_key(g), "")

    merged.sort(key=_sort_key)
    return merged


def _build_geometry_config(config: ConfigManager, max_pin_length: int) -> Dict[str, float]:
    """Build geometry analyzer configuration from runtime settings."""
    return {
        "pin_assignment_threshold": config.get("pin_assignment_threshold", 50.0),
        "refdes_search_radius": config.get("refdes_search_radius", 100.0),
        "y_overlap_weight": config.get("y_overlap_weight", 0.7),
        "dx_weight": config.get("dx_weight", 0.3),
        "refdes_font_size_min": config.get("refdes_font_size_min", 8.0),
        "max_pin_label_length": max_pin_length,
    }


def _serialize_pin_map(pin_map: Dict[str, ga.PinMapping]) -> List[dict]:
    payload = []
    for mapping in pin_map.values():
        payload.append(
            {
                "pin_identifier": mapping.pin_identifier,
                "refdes": mapping.refdes,
                "pin_label": mapping.pin_label,
                "full_identifier": mapping.full_identifier,
                "confidence": float(mapping.confidence),
                "page_num": int(mapping.page_num),
            }
        )
    return payload


def _serialize_body_rects(body_rects: Dict[Tuple[int, str], ga.Rect]) -> List[dict]:
    payload = []
    for (page_num, refdes), rect in body_rects.items():
        payload.append(
            {
                "page_num": int(page_num),
                "refdes": str(refdes),
                "rect": [float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)],
            }
        )
    return payload


def _deserialize_pin_map(payload: List[dict]) -> Dict[str, ga.PinMapping]:
    pin_map: Dict[str, ga.PinMapping] = {}
    for item in payload or []:
        mapping = ga.PinMapping(
            pin_identifier=str(item.get("pin_identifier", "")),
            refdes=str(item.get("refdes", "")),
            pin_label=str(item.get("pin_label", "")),
            full_identifier=str(item.get("full_identifier", "")),
            confidence=float(item.get("confidence", 0.0)),
            page_num=int(item.get("page_num", 0)),
        )
        if mapping.pin_identifier:
            pin_map[mapping.pin_identifier] = mapping
    return pin_map


def _deserialize_body_rects(payload: List[dict]) -> Dict[Tuple[int, str], ga.Rect]:
    body_rects: Dict[Tuple[int, str], ga.Rect] = {}
    for item in payload or []:
        rect_data = item.get("rect") or []
        if len(rect_data) != 4:
            continue
        page_num = int(item.get("page_num", 0))
        refdes = str(item.get("refdes", ""))
        if not refdes:
            continue
        body_rects[(page_num, refdes)] = ga.Rect(
            float(rect_data[0]),
            float(rect_data[1]),
            float(rect_data[2]),
            float(rect_data[3]),
        )
    return body_rects


def _geometry_batch_worker(
    result_queue: "mp.Queue",
    pdf_path: str,
    geo_config: dict,
    batch_pages: List[int],
) -> None:
    """
    Child-process worker for isolated geometry execution.

    Running geometry in a separate process allows hard termination on cancel.
    """
    try:
        pin_map, body_rects = ga.analyze_document(
            pdf_path,
            geo_config,
            stop_event=None,
            page_filter=set(batch_pages),
        )
        result_queue.put(
            {
                "ok": True,
                "pin_map": _serialize_pin_map(pin_map),
                "body_rects": _serialize_body_rects(body_rects),
            }
        )
    except Exception as ex:  # pragma: no cover - exercised via parent error path
        result_queue.put({"ok": False, "error": str(ex)})


def _run_geometry_batch_subprocess(
    pdf_path: Path,
    geo_config: dict,
    batch_pages: List[int],
    stop_event=None,
    timeout_seconds: float = _DEFAULT_BATCH_TIMEOUT_SECONDS,
) -> Tuple[Dict[str, ga.PinMapping], Dict[Tuple[int, str], ga.Rect]]:
    """Execute a geometry batch in a child process with cancellation polling."""
    ctx = mp.get_context("spawn")
    result_queue = ctx.Queue()
    proc = ctx.Process(
        target=_geometry_batch_worker,
        args=(result_queue, str(pdf_path), geo_config, list(batch_pages)),
        daemon=True,
    )
    proc.start()
    start = time.monotonic()
    cancelled = False
    timed_out = False

    try:
        while proc.is_alive():
            if stop_event and stop_event.is_set():
                cancelled = True
                proc.terminate()
                break

            elapsed = time.monotonic() - start
            if elapsed > timeout_seconds:
                timed_out = True
                proc.terminate()
                break

            time.sleep(0.1)

        proc.join(timeout=5.0)

        if cancelled:
            raise CancellationError("Cancelled during subprocess geometry batch.")
        if timed_out:
            raise ProcessingError(
                f"Geometry subprocess timed out after {timeout_seconds:.0f}s "
                f"for pages {', '.join(str(p + 1) for p in batch_pages)}."
            )

        payload = None
        try:
            payload = result_queue.get(timeout=2.0)
        except Exception:
            payload = None

        if not payload:
            raise ProcessingError("Geometry subprocess exited without returning results.")
        if not payload.get("ok"):
            raise ProcessingError(payload.get("error") or "Geometry subprocess failed.")

        return (
            _deserialize_pin_map(payload.get("pin_map") or []),
            _deserialize_body_rects(payload.get("body_rects") or []),
        )
    finally:
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=2.0)
            if proc.is_alive():
                proc.kill()
                proc.join(timeout=1.0)
        try:
            result_queue.close()
            result_queue.join_thread()
        except Exception:
            pass


def _detect_sparse_geometry_pages(
    batch_pages: List[int],
    batch_pin_map: Dict[str, ga.PinMapping],
    batch_body_rects: Dict[Tuple[int, str], ga.Rect],
    page_metrics: Optional[Dict[int, legacy_engine.PageMetrics]],
    config: ConfigManager,
) -> Set[int]:
    """
    Identify suspicious geometry outputs that should degrade to annotation-only mode.

    This guards against pathological pages where geometry extraction appears to run
    but returns implausibly low structural data.
    """
    if not page_metrics:
        return set()

    min_pin_candidates = int(config.get("geometry_sparse_gate_min_pin_candidates", 40))
    max_body_count = int(config.get("geometry_sparse_gate_max_bodies", 15))
    max_body_to_pin_ratio = float(config.get("geometry_sparse_gate_max_body_to_pin_ratio", 0.20))
    min_mapped_ratio = float(config.get("geometry_sparse_gate_min_mapped_ratio", 0.10))

    sparse_pages: Set[int] = set()
    for page_idx in batch_pages:
        metrics = page_metrics.get(page_idx)
        if not metrics:
            continue

        total_candidates = int(metrics.total_pin_candidates)
        if total_candidates < min_pin_candidates:
            continue

        body_count = sum(1 for (p, _ref) in batch_body_rects.keys() if p == page_idx)
        mapped_count = sum(1 for m in batch_pin_map.values() if m.page_num == page_idx)
        body_ratio = body_count / max(total_candidates, 1)
        mapped_ratio = mapped_count / max(total_candidates, 1)

        if body_count <= max_body_count and body_ratio <= max_body_to_pin_ratio and mapped_ratio <= min_mapped_ratio:
            sparse_pages.add(page_idx)

    return sparse_pages


def _save_geometry_batch_checkpoint(
    config: ConfigManager,
    pdf_path: Path,
    batch_index: int,
    batch_pages: List[int],
    pin_count: int,
    body_count: int,
    degraded_pages: Set[int],
) -> None:
    """Persist a lightweight batch checkpoint for post-run triage."""
    if not bool(config.get("geometry_batch_checkpoint_enabled", True)):
        return

    out_folder = str(config.get("out_folder", "")).strip()
    if not out_folder:
        return

    checkpoint_dir = Path(out_folder) / "_refdes_test_checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"{Path(pdf_path).stem}_geo_batch_{batch_index + 1:03d}_{ts}.json"
    payload = {
        "timestamp": ts,
        "pdf": str(pdf_path),
        "batch_index": batch_index + 1,
        "pages_1_indexed": [p + 1 for p in batch_pages],
        "pin_map_count": pin_count,
        "body_rect_count": body_count,
        "degraded_pages_1_indexed": [p + 1 for p in sorted(degraded_pages)],
    }
    (checkpoint_dir / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _run_geometry_with_batches(
    pdf_path: Path,
    pages: Set[int],
    geo_config: dict,
    config: ConfigManager,
    log: Callable[[str], None],
    status: Callable[[str], None],
    stop_event=None,
    progress_func: Optional[Callable[[float], None]] = None,
    doc: Optional[fitz.Document] = None,
    page_metrics: Optional[Dict[int, legacy_engine.PageMetrics]] = None,
) -> Tuple[Dict[str, ga.PinMapping], Dict[Tuple[int, str], ga.Rect], Set[int]]:
    """
    Run geometry in bounded page batches and return merged results.

    Returns:
        (pin_map, body_rects, degraded_pages)
    """
    pages_to_process = sorted(pages)
    if not pages_to_process:
        return {}, {}, set()

    batch_size = max(1, int(config.get("geometry_batch_size", _DEFAULT_BATCH_SIZE)))
    use_subprocess = bool(config.get("geometry_subprocess_enabled", False))
    batch_timeout = float(config.get("geometry_batch_timeout_seconds", _DEFAULT_BATCH_TIMEOUT_SECONDS))
    batches = _chunk_pages(pages_to_process, batch_size)

    merged_pin_map: Dict[str, ga.PinMapping] = {}
    merged_body_rects: Dict[Tuple[int, str], ga.Rect] = {}
    degraded_pages: Set[int] = set()

    for batch_index, batch_pages in enumerate(batches):
        check_cancelled(stop_event, "Cancelled before geometry batch")
        status(
            "Geometry batch "
            f"{batch_index + 1}/{len(batches)} "
            f"(pages {batch_pages[0] + 1}-{batch_pages[-1] + 1})"
        )

        try:
            if use_subprocess:
                batch_pin_map, batch_body_rects = _run_geometry_batch_subprocess(
                    pdf_path=pdf_path,
                    geo_config=geo_config,
                    batch_pages=batch_pages,
                    stop_event=stop_event,
                    timeout_seconds=batch_timeout,
                )
            else:
                batch_pin_map, batch_body_rects = ga.analyze_document(
                    str(pdf_path),
                    geo_config,
                    stop_event=stop_event,
                    log_func=log,
                    status_func=status,
                    page_filter=set(batch_pages),
                    doc=doc,
                )
        except (CancellationError, InterruptedError):
            raise
        except Exception as ex:
            log(
                "[RefDes Test] WARNING: Geometry batch "
                f"{batch_index + 1}/{len(batches)} failed ({ex}). "
                "Continuing with annotation-only mode for this batch."
            )
            _logger.exception("Geometry batch failed")
            degraded_pages.update(batch_pages)
            continue

        sparse_pages = _detect_sparse_geometry_pages(
            batch_pages=batch_pages,
            batch_pin_map=batch_pin_map,
            batch_body_rects=batch_body_rects,
            page_metrics=page_metrics,
            config=config,
        )
        if sparse_pages:
            degraded_pages.update(sparse_pages)
            log(
                "[RefDes Test] WARNING: Geometry output deemed sparse on page(s) "
                f"{', '.join(str(p + 1) for p in sorted(sparse_pages))}; "
                "falling back to annotation-only extraction for those pages."
            )
            batch_pin_map = {
                key: mapping for key, mapping in batch_pin_map.items() if mapping.page_num not in sparse_pages
            }
            batch_body_rects = {
                key: rect for key, rect in batch_body_rects.items() if key[0] not in sparse_pages
            }

        merged_pin_map.update(batch_pin_map)
        merged_body_rects.update(batch_body_rects)
        _save_geometry_batch_checkpoint(
            config=config,
            pdf_path=pdf_path,
            batch_index=batch_index,
            batch_pages=batch_pages,
            pin_count=len(batch_pin_map),
            body_count=len(batch_body_rects),
            degraded_pages=sparse_pages,
        )

        if progress_func and len(batches) > 0:
            progress_func((batch_index + 1) / len(batches))

    return merged_pin_map, merged_body_rects, degraded_pages


def _is_token_bom_member(token: str, normalized_bom: set) -> bool:
    """Return True when the token's base RefDes exists in the BOM."""
    base = _extract_base_refdes(token)
    return bool(base and base in normalized_bom)


def _get_token_page_mismatch(
    token: str,
    pages: set,
    normalized_bom_pages: dict,
) -> Optional[dict]:
    """
    Return advisory page mismatch details for a BOM member token.

    Page metadata is diagnostic only. A mismatch is logged for review, but it
    must not move a BOM member into the Unverified bucket.
    """
    base = _extract_base_refdes(token)
    if not base:
        return None

    expected_pages = normalized_bom_pages.get(base)
    if not expected_pages or not pages:
        return None

    actual_pages = {int(p) for p in pages if isinstance(p, int) or str(p).isdigit()}
    if not actual_pages or not actual_pages.isdisjoint(expected_pages):
        return None

    return {
        "token": token,
        "base": base,
        "expected_pages": set(expected_pages),
        "actual_pages": actual_pages,
    }


def _format_hybrid_results_nextgen(
    grouped_data: dict,
    bom_set: set,
    bom_page_map: Optional[dict],
    log_func: Optional[Callable] = None,
    normalized_bom: Optional[set] = None,
    normalized_bom_pages: Optional[dict] = None,
) -> list:
    """
    Format rows with consistent Verified/Unverified split.

    Unlike legacy formatting for piece-part mode, NextGen validates by base RefDes.
    BOM page metadata is checked only for advisory mismatch reporting.
    """
    from refdes_extractor.refdes_extractor_logic import _strip_mode_suffix, detect_sequence_gaps

    rows = []
    if normalized_bom is None:
        normalized_bom = _normalize_bom_set(bom_set)
    if normalized_bom_pages is None:
        normalized_bom_pages = _normalize_bom_page_map(bom_page_map)

    page_mismatches = []

    for group_name, data in grouped_data.items():
        mode = data.get("mode", "functional")
        display_name = _strip_mode_suffix(group_name)
        page_set = {int(p) for p in data.get("pages", set()) if isinstance(p, int) or str(p).isdigit()}
        token_pages_by_token = data.get("token_pages", {})
        pages = ", ".join(str(p) for p in sorted(page_set))

        if "UNGROUPED" in group_name or "PROVISIONAL" in group_name:
            if mode == "functional":
                all_tokens = sorted(
                    set(data.get("verified", set())) | set(data.get("unverified", set())),
                    key=legacy_engine.natural_key,
                )
            else:
                all_tokens = sorted(set(data.get("tokens", set())), key=legacy_engine.natural_key)

            if all_tokens:
                rows.append(
                    {
                        "group": group_name,
                        "failure mode causes": ", ".join(all_tokens),
                        "component count": len(all_tokens),
                        "pages": pages,
                    }
                )
            continue

        if mode == "functional":
            candidates = set(data.get("verified", set())) | set(data.get("unverified", set()))
        else:
            candidates = set(data.get("tokens", set()))

        verified = []
        unverified = []
        for token in sorted(candidates, key=legacy_engine.natural_key):
            token_page_set = {
                int(p)
                for p in token_pages_by_token.get(token, set())
                if isinstance(p, int) or str(p).isdigit()
            }
            effective_pages = token_page_set or page_set
            if _is_token_bom_member(token, normalized_bom):
                verified.append(token)
                mismatch = _get_token_page_mismatch(token, effective_pages, normalized_bom_pages)
                if mismatch:
                    mismatch["group"] = display_name
                    page_mismatches.append(mismatch)
            else:
                unverified.append(token)

        rows.append(
            {
                "group": f"{display_name} (Verified)",
                "failure mode causes": ", ".join(verified),
                "component count": len(verified),
                "pages": pages,
            }
        )
        rows.append(
            {
                "group": f"{display_name} (Unverified)",
                "failure mode causes": ", ".join(unverified),
                "component count": len(unverified),
                "pages": pages,
            }
        )

    regular_groups = [
        _strip_mode_suffix(name)
        for name in grouped_data.keys()
        if "UNGROUPED" not in name and "PROVISIONAL" not in name
    ]
    rows.extend(detect_sequence_gaps(regular_groups, log_func))

    if page_mismatches:
        mismatch_groups = sorted({item["group"] for item in page_mismatches}, key=legacy_engine.natural_key)
        if log_func:
            log_func(
                "[RefDes Test] NOTE: "
                f"{len(page_mismatches)} verified component(s) had BOM page mismatches "
                f"across {len(mismatch_groups)} group(s); verification remained BOM-membership-based."
            )
        for mismatch in page_mismatches:
            _logger.debug(
                "[RefDes Test] BOM page mismatch kept verified: group=%s token=%s base=%s expected=%s actual=%s",
                mismatch["group"],
                mismatch["token"],
                mismatch["base"],
                sorted(mismatch["expected_pages"]),
                sorted(mismatch["actual_pages"]),
            )

    def _sort_key(row: dict):
        g = str(row.get("group", ""))
        if "UNGROUPED" in g:
            return (2, "", g)
        if "PROVISIONAL" in g:
            return (1, "", g)
        if row.get("_is_gap") or "GROUP NOT DETECTED" in g:
            base_name = g.replace(" (GROUP NOT DETECTED)", "")
            return (0, legacy_engine.natural_key(base_name), 2)
        base_name = g.replace(" (Verified)", "").replace(" (Unverified)", "")
        is_unverified = "(Unverified)" in g
        return (0, legacy_engine.natural_key(base_name), 1 if is_unverified else 0)

    return sorted(rows, key=_sort_key)


def extract_with_geometry_analysis(
    pdf_path: Path,
    groups: list,
    bom_set: set,
    config: Optional[ConfigManager] = None,
    pinlist_set: Optional[set] = None,
    debug_pdf_path: Path = None,
    log_func=None,
    progress_func=None,
    status_func=None,
    stop_event=None,
    bom_page_map: Optional[dict] = None,
    doc: Optional[fitz.Document] = None,
) -> list:
    """NextGen extraction entry point with adaptive + batched geometry support."""
    legacy_logic._ensure_engine_initialized()

    if config is None:
        config = ConfigManager("refdes_test")

    log = log_func or (lambda _msg: None)
    progress = progress_func or (lambda _pct: None)
    status = status_func or (lambda _msg: None)

    if not groups:
        log("No annotation groups detected in PDF.")
        return []

    global_mode = config.get("extraction_mode", "functional")
    group_modes = {}
    pn_pages: Set[int] = set()
    for page_idx, name, _rect in groups:
        mode = legacy_logic._determine_group_mode(name, global_mode)
        group_modes[(page_idx, name)] = mode
        if mode == "piece_part":
            pn_pages.add(page_idx)

    max_pin_length = int(config.get("max_pin_label_length", 4))
    geometry_enabled = bool(config.get("geometry_analysis_enabled", True))
    adaptive_enabled = bool(config.get("adaptive_geometry_enabled", True))
    pinlist_prefers_annotation = bool(config.get("pinlist_prefers_annotation_mode", True))

    prov_distance = float(config.get("prov_distance", legacy_logic.DEFAULT_PROV_DISTANCE))
    if prov_distance <= 0:
        prov_distance = legacy_logic.DEFAULT_PROV_DISTANCE

    normalized_bom = _normalize_bom_set(bom_set)
    normalized_bom_pages = _normalize_bom_page_map(bom_page_map)
    geo_config = _build_geometry_config(config, max_pin_length)
    pdf_path = Path(pdf_path)

    if doc is None:
        pdf_path = ensure_file_available(pdf_path, log)

    doc_ctx = nullcontext(doc) if doc is not None else fitz.open(str(pdf_path))
    with doc_ctx as active_doc:
        # Fast paths with no geometry.
        if not pn_pages:
            log("[RefDes Test] No piece-part pages detected; skipping geometry.")
            results = harvest_hybrid_nextgen(
                pdf_path=pdf_path,
                groups=groups,
                bom_set=bom_set,
                bom_page_map=bom_page_map,
                config=config,
                group_modes=group_modes,
                pin_map={},
                body_rects={},
                pinlist_set=pinlist_set,
                debug_pdf_path=debug_pdf_path,
                log_func=log,
                progress_func=progress,
                prov_distance=prov_distance,
                stop_event=stop_event,
                max_pin_length=max_pin_length,
                doc=active_doc,
                normalized_bom=normalized_bom,
                normalized_bom_pages=normalized_bom_pages,
            )
            progress(1.0)
            status("Extraction complete")
            return results

        if not geometry_enabled:
            log("[RefDes Test] Geometry disabled; using annotation-only extraction.")
            results = harvest_hybrid_nextgen(
                pdf_path=pdf_path,
                groups=groups,
                bom_set=bom_set,
                bom_page_map=bom_page_map,
                config=config,
                group_modes=group_modes,
                pin_map={},
                body_rects={},
                pinlist_set=pinlist_set,
                debug_pdf_path=debug_pdf_path,
                log_func=log,
                progress_func=progress,
                prov_distance=prov_distance,
                stop_event=stop_event,
                max_pin_length=max_pin_length,
                doc=active_doc,
                normalized_bom=normalized_bom,
                normalized_bom_pages=normalized_bom_pages,
            )
            progress(1.0)
            status("Extraction complete")
            return results

        if pinlist_set and pinlist_prefers_annotation:
            log("[RefDes Test] Pinlist present; using lightweight annotation-first pin qualification.")
            results = harvest_hybrid_nextgen(
                pdf_path=pdf_path,
                groups=groups,
                bom_set=bom_set,
                bom_page_map=bom_page_map,
                config=config,
                group_modes=group_modes,
                pin_map={},
                body_rects={},
                pinlist_set=pinlist_set,
                debug_pdf_path=debug_pdf_path,
                log_func=log,
                progress_func=progress,
                prov_distance=prov_distance,
                stop_event=stop_event,
                max_pin_length=max_pin_length,
                doc=active_doc,
                normalized_bom=normalized_bom,
                normalized_bom_pages=normalized_bom_pages,
            )
            progress(1.0)
            status("Extraction complete")
            return results

        if adaptive_enabled:
            # -----------------------------------------------------------------
            # Phase 1: Fast extraction for metrics (no geometry)
            # -----------------------------------------------------------------
            log("[RefDes Test] Adaptive geometry enabled.")
            status("Phase 1/4: Fast extraction...")
            progress(0.05)
            phase1_results, page_metrics = harvest_hybrid_nextgen(
                pdf_path=pdf_path,
                groups=groups,
                bom_set=bom_set,
                bom_page_map=bom_page_map,
                config=config,
                group_modes=group_modes,
                pin_map={},
                body_rects={},
                pinlist_set=pinlist_set,
                debug_pdf_path=None,
                log_func=log,
                progress_func=lambda p: progress(0.05 + p * 0.15),
                prov_distance=prov_distance,
                stop_event=stop_event,
                max_pin_length=max_pin_length,
                doc=active_doc,
                normalized_bom=normalized_bom,
                normalized_bom_pages=normalized_bom_pages,
                collect_metrics=True,
            )
            progress(0.20)

            # -----------------------------------------------------------------
            # Phase 2: Gate problematic pages
            # -----------------------------------------------------------------
            status("Phase 2/4: Selecting geometry pages...")
            pn_page_metrics = {p: m for p, m in page_metrics.items() if p in pn_pages}
            gating_config = legacy_engine.GatingConfig(
                orphan_threshold=int(
                    config.get("adaptive_orphan_threshold", _DEFAULT_ADAPTIVE_ORPHAN_THRESHOLD)
                ),
                orphan_ratio_threshold=float(
                    config.get("adaptive_orphan_ratio", _DEFAULT_ADAPTIVE_ORPHAN_RATIO)
                ),
                max_geometry_pages=int(
                    config.get("adaptive_max_pages", _DEFAULT_ADAPTIVE_MAX_PAGES)
                ),
            )
            flagged_pages, suppressed_pages = legacy_engine.select_pages_for_geometry(
                pn_page_metrics, gating_config
            )

            total_candidates = sum(m.total_pin_candidates for m in pn_page_metrics.values())
            total_orphans = sum(m.orphan_count for m in pn_page_metrics.values())
            log(
                "[RefDes Test] Adaptive metrics: "
                f"{total_candidates} pin candidates, {total_orphans} orphans."
            )
            if flagged_pages:
                log(
                    "[RefDes Test] Flagged geometry pages: "
                    f"{', '.join(str(p + 1) for p in sorted(flagged_pages))}"
                )
            if suppressed_pages:
                log(
                    "[RefDes Test] Suppressed pages: "
                    f"{', '.join(str(p + 1) for p in sorted(suppressed_pages.keys()))}"
                )
            progress(0.25)

            # -----------------------------------------------------------------
            # Phase 3: Batched geometry on flagged pages
            # -----------------------------------------------------------------
            pin_map: Dict[str, ga.PinMapping] = {}
            body_rects: Dict[Tuple[int, str], ga.Rect] = {}
            degraded_pages: Set[int] = set()
            if flagged_pages:
                status("Phase 3/4: Running batched geometry...")
                pin_map, body_rects, degraded_pages = _run_geometry_with_batches(
                    pdf_path=pdf_path,
                    pages=flagged_pages,
                    geo_config=geo_config,
                    config=config,
                    log=log,
                    status=status,
                    stop_event=stop_event,
                    progress_func=lambda p: progress(0.25 + p * 0.35),
                    doc=active_doc,
                    page_metrics=page_metrics,
                )
                if degraded_pages:
                    log(
                        "[RefDes Test] Geometry degraded to annotation-only on page(s): "
                        f"{', '.join(str(p + 1) for p in sorted(degraded_pages))}"
                    )
            progress(0.60)

            # -----------------------------------------------------------------
            # Phase 4: Final harvest with selective geometry results applied
            # -----------------------------------------------------------------
            status("Phase 4/4: Finalizing results...")
            if not flagged_pages or (not pin_map and not body_rects):
                results = phase1_results
                if debug_pdf_path:
                    _ = harvest_hybrid_nextgen(
                        pdf_path=pdf_path,
                        groups=groups,
                        bom_set=bom_set,
                        bom_page_map=bom_page_map,
                        config=config,
                        group_modes=group_modes,
                        pin_map={},
                        body_rects={},
                        pinlist_set=pinlist_set,
                        debug_pdf_path=debug_pdf_path,
                        log_func=log,
                        progress_func=lambda p: progress(0.60 + p * 0.35),
                        prov_distance=prov_distance,
                        stop_event=stop_event,
                        max_pin_length=max_pin_length,
                        doc=active_doc,
                        normalized_bom=normalized_bom,
                        normalized_bom_pages=normalized_bom_pages,
                    )
            else:
                results = harvest_hybrid_nextgen(
                    pdf_path=pdf_path,
                    groups=groups,
                    bom_set=bom_set,
                    bom_page_map=bom_page_map,
                    config=config,
                    group_modes=group_modes,
                    pin_map=pin_map,
                    body_rects=body_rects,
                    pinlist_set=pinlist_set,
                    debug_pdf_path=debug_pdf_path,
                    log_func=log,
                    progress_func=lambda p: progress(0.60 + p * 0.35),
                    prov_distance=prov_distance,
                    stop_event=stop_event,
                    max_pin_length=max_pin_length,
                    doc=active_doc,
                    normalized_bom=normalized_bom,
                    normalized_bom_pages=normalized_bom_pages,
                )

            progress(1.0)
            status("Extraction complete")
            return results

        # Adaptive disabled: run full set of piece-part pages, but batched.
        status("Running batched geometry...")
        progress(0.10)
        pin_map, body_rects, degraded_pages = _run_geometry_with_batches(
            pdf_path=pdf_path,
            pages=pn_pages,
            geo_config=geo_config,
            config=config,
            log=log,
            status=status,
            stop_event=stop_event,
            progress_func=lambda p: progress(0.10 + p * 0.35),
            doc=active_doc,
            page_metrics=None,
        )
        if degraded_pages:
            log(
                "[RefDes Test] Geometry degraded to annotation-only on page(s): "
                f"{', '.join(str(p + 1) for p in sorted(degraded_pages))}"
            )

        status("Harvesting components...")
        results = harvest_hybrid_nextgen(
            pdf_path=pdf_path,
            groups=groups,
            bom_set=bom_set,
            bom_page_map=bom_page_map,
            config=config,
            group_modes=group_modes,
            pin_map=pin_map,
            body_rects=body_rects,
            pinlist_set=pinlist_set,
            debug_pdf_path=debug_pdf_path,
            log_func=log,
            progress_func=lambda p: progress(0.45 + p * 0.55),
            prov_distance=prov_distance,
            stop_event=stop_event,
            max_pin_length=max_pin_length,
            doc=active_doc,
            normalized_bom=normalized_bom,
            normalized_bom_pages=normalized_bom_pages,
        )

    progress(1.0)
    status("Extraction complete")
    return results


def harvest_hybrid_nextgen(
    pdf_path: Path,
    groups: list,
    bom_set: set,
    bom_page_map: Optional[dict],
    config: ConfigManager,
    group_modes: dict,
    pin_map: dict,
    body_rects: dict,
    pinlist_set: Optional[set] = None,
    debug_pdf_path: Path = None,
    log_func: Callable = None,
    progress_func: Callable = None,
    prov_distance: float = None,
    stop_event: threading.Event = None,
    max_pin_length: int = 4,
    doc: Optional[fitz.Document] = None,
    normalized_bom: Optional[set] = None,
    normalized_bom_pages: Optional[dict] = None,
    collect_metrics: bool = False,
) -> list | tuple[list, dict]:
    """
    NextGen hybrid harvester.

    Uses candidate-list pin disambiguation for every pin label to avoid
    single-entry overwrite collisions on duplicated labels (e.g. many "1" pins).
    """
    log = log_func or (lambda _msg: None)
    progress = progress_func or (lambda _pct: None)

    if prov_distance is None:
        prov_distance = legacy_logic.DEFAULT_PROV_DISTANCE

    if not groups:
        log("No groups to process")
        if collect_metrics:
            return [], {}
        return []

    if normalized_bom is None:
        normalized_bom = _normalize_bom_set(bom_set)
    if normalized_bom_pages is None:
        normalized_bom_pages = _normalize_bom_page_map(bom_page_map)
    if not normalized_bom:
        log("NOTE: No BOM loaded - all components will be marked as Unverified")

    def _expected_pages_for_refdes(refdes: str) -> set:
        base = canonicalize_refdes(legacy_logic.strip_suffix(refdes))
        if not base:
            return set()
        return normalized_bom_pages.get(base, set())

    def _page_penalty_for_refdes(refdes: str, page_number: int) -> int:
        expected = _expected_pages_for_refdes(refdes)
        if not expected:
            return 0
        return 0 if page_number in expected else 1

    def _is_strong_page_match(refdes: str, page_number: int) -> bool:
        expected = _expected_pages_for_refdes(refdes)
        return bool(expected) and page_number in expected

    def _canonicalize_pin_id(token: str) -> str:
        if token is None:
            return ""
        t = str(token).strip().upper()
        if not t:
            return ""
        if t.endswith("[?]"):
            t = t[:-3].strip()
        t = re.sub(r"\s*[-.:]\s*", "-", t)
        t = re.sub(r"-{2,}", "-", t)
        if "-" not in t:
            return ""
        ref, pin = t.rsplit("-", 1)
        ref = canonicalize_refdes(legacy_logic.strip_suffix(ref))
        pin = re.sub(r"\s+", "", pin).upper()
        if not ref or not pin:
            return ""
        return f"{ref}-{pin}"

    normalized_pinlist = set()
    if pinlist_set:
        normalized_pinlist = {p for p in (_canonicalize_pin_id(x) for x in pinlist_set) if p}
        if normalized_pinlist:
            log(f"Pinlist filtering enabled: {len(normalized_pinlist)} pin(s)")

    page_group_map = defaultdict(list)
    for page_idx, name, rect in groups:
        mode = group_modes.get((page_idx, name), "functional")
        page_group_map[page_idx].append(
            {
                "name": name,
                "rect": rect,
                "mode": mode,
                "area": area_of(rect),
            }
        )
    for page_idx in page_group_map:
        page_group_map[page_idx].sort(key=lambda g: g["area"])

    grouped_data = {}
    for _page_idx, name, _rect in groups:
        mode = group_modes.get((_page_idx, name), "functional")
        if name in grouped_data:
            continue
        if mode == "functional":
            grouped_data[name] = {
                "verified": set(),
                "unverified": set(),
                "pages": set(),
                "mode": mode,
                "token_pages": {},
            }
        else:
            grouped_data[name] = {"tokens": set(), "pages": set(), "mode": mode, "token_pages": {}}

    def _track_token_page(group_bucket: dict, token: str, page_number: int) -> None:
        """Track the specific page(s) each extracted token came from."""
        if not token:
            return
        token_pages = group_bucket.setdefault("token_pages", {})
        pages = token_pages.setdefault(token, set())
        pages.add(page_number)

    # NextGen fix: never build a single exact-map for (page,label) because labels are not unique.
    pin_lookup_by_label = defaultdict(list)
    for mapping in pin_map.values():
        pin_lookup_by_label[(mapping.page_num, mapping.pin_label)].append(mapping)

    debug_shapes = [] if (debug_pdf_path or collect_metrics) else None
    _dbg = debug_shapes.append if debug_shapes is not None else lambda _t: None

    if doc is None:
        pdf_path = ensure_file_available(pdf_path, log)

    observed_page_count = 0
    doc_ctx = nullcontext(doc) if doc is not None else fitz.open(str(pdf_path))
    with doc_ctx as doc:
        try:
            total_pages = len(doc)
            observed_page_count = total_pages
            for page_idx, page in enumerate(doc):
                check_cancelled(stop_event, "Hybrid harvesting cancelled by user.")
                if total_pages > 0:
                    progress(page_idx / total_pages)

                current_groups = page_group_map.get(page_idx, [])
                if not current_groups:
                    continue

                group_grid = _build_group_grid(current_groups)
                words = legacy_engine._get_words_with_timeout(page, page_num=page_idx, log_func=log)

                for g in current_groups:
                    _dbg((page_idx, g["rect"], (1, 0, 0), g["name"]))

                prov_markers = []
                for w in words:
                    if (w[4] or "").strip().upper() == "PROV":
                        prov_markers.append((w[0], w[1], w[2], w[3]))

                page_refdes_candidates = []
                for w in words:
                    t = (w[4] or "").strip()
                    if not t:
                        continue
                    if legacy_logic.REFDES_RE.fullmatch(t) and not legacy_logic.POWER_SOURCE_RE.match(t):
                        r = (w[0], w[1], w[2], w[3])
                        rcx, rcy = center(r)
                        page_refdes_candidates.append((canonicalize_refdes(legacy_logic.strip_suffix(t)), rcx, rcy))

                group_entries = defaultdict(list)
                for w_idx, w in enumerate(words):
                    if w_idx % 200 == 0:
                        check_cancelled(stop_event, "Word processing cancelled by user.")

                    text = (w[4] or "").strip()
                    if not text:
                        continue

                    rect = (w[0], w[1], w[2], w[3])
                    cx, cy = center(rect)

                    my_group = _lookup_group(group_grid, cx, cy)
                    if not my_group:
                        continue

                    is_prov = False
                    for p_rect in prov_markers:
                        pcx, pcy = center(p_rect)
                        if ((cx - pcx) ** 2 + (cy - pcy) ** 2) ** 0.5 < prov_distance:
                            is_prov = True
                            break

                    group_entries[my_group["name"]].append(
                        {"text": text, "rect": rect, "center": (cx, cy), "is_prov": is_prov}
                    )

                pinlist_qualified_pins = {}
                has_piece_part_groups = any(g["mode"] == "piece_part" for g in current_groups)
                if normalized_pinlist and has_piece_part_groups:
                    piece_part_entries = {
                        g["name"]: group_entries.get(g["name"], [])
                        for g in current_groups
                        if g["mode"] == "piece_part"
                    }
                    if piece_part_entries:
                        def _is_refdes_check(text: str) -> bool:
                            return bool(legacy_logic.REFDES_RE.fullmatch(text) and not legacy_logic.POWER_SOURCE_RE.match(text))

                        def _is_pin_candidate_check(text: str) -> bool:
                            return ga.is_pin_candidate(text, max_length=max_pin_length)

                        clustering_parent_radius = float(config.get("parent_refdes_max_radius", 300.0))
                        if clustering_parent_radius < 250:
                            clustering_parent_radius = 500.0

                        pinlist_config = {
                            "pin_parent_prefix_allowlist": config.get(
                                "pin_parent_prefix_allowlist",
                                DEFAULT_PIN_PARENT_PREFIX_ALLOWLIST,
                            ),
                            "passive_terminal_labels": config.get("passive_terminal_labels", ["1", "2"]),
                            "passive_context_radius_px": config.get("passive_context_radius_px", 120.0),
                            "pin_cluster_cell_size_px": config.get("pin_cluster_cell_size_px", 120.0),
                            "pin_cluster_max_dist_px": config.get("pin_cluster_max_dist_px", 150.0),
                            "cluster_min_distinct_labels": config.get("cluster_min_distinct_labels", 2),
                            "strict_numeric_pin_parenting": config.get("strict_numeric_pin_parenting", True),
                            "parent_refdes_max_radius": clustering_parent_radius,
                        }
                        try:
                            pinlist_qualified_pins = qualify_pins_via_pinlist(
                                group_entries=piece_part_entries,
                                normalized_pinlist=normalized_pinlist,
                                page_words=words,
                                config=pinlist_config,
                                is_refdes_fn=_is_refdes_check,
                                is_pin_candidate_fn=_is_pin_candidate_check,
                                stop_event=stop_event,
                            )
                        except CancellationError:
                            raise
                        except Exception as ex:
                            _logger.error(f"Pinlist clustering failed on page {page_idx}: {ex}")
                            pinlist_qualified_pins = {}

                page_body_candidates = []
                if body_rects:
                    for (p, ref), b_rect in body_rects.items():
                        if p == page_idx:
                            page_body_candidates.append((canonicalize_refdes(legacy_logic.strip_suffix(ref)), b_rect))

                parent_refdes_radius = float(config.get("parent_refdes_max_radius", config.get("refdes_search_radius", 100.0)))
                if normalized_pinlist and parent_refdes_radius < 250:
                    parent_refdes_radius = 500.0
                parent_refdes_radius_sq = parent_refdes_radius ** 2

                def find_parent_refdes(group_rect: tuple, pin_texts: list[str]) -> Optional[str]:
                    gcx, gcy = center(group_rect)
                    candidates = {}

                    for ref, b_rect in page_body_candidates:
                        if legacy_engine._rects_overlap(group_rect, b_rect):
                            bcx = (b_rect.x0 + b_rect.x1) / 2
                            bcy = (b_rect.y0 + b_rect.y1) / 2
                            dist_sq = (gcx - bcx) ** 2 + (gcy - bcy) ** 2
                            candidates[ref] = {"source": "body", "dist_sq": dist_sq}

                    for ref, rcx, rcy in page_refdes_candidates:
                        dx = gcx - rcx
                        dy = gcy - rcy
                        dist_sq = dx * dx + dy * dy
                        if dist_sq > parent_refdes_radius_sq:
                            continue
                        bias = 1.0
                        if rcx < gcx and rcy < gcy:
                            bias = 0.8
                        elif rcx > gcx and rcy > gcy:
                            bias = 1.4
                        eff_dist = dist_sq * bias

                        existing = candidates.get(ref)
                        if not existing or (existing["source"] != "body" and eff_dist < existing["dist_sq"]):
                            candidates[ref] = {"source": "text", "dist_sq": eff_dist}

                    if not candidates:
                        return None

                    if normalized_pinlist and pin_texts:
                        best_ref = None
                        best_hits = -1
                        best_rank = None
                        for ref, info in candidates.items():
                            hits = 0
                            for ptxt in pin_texts:
                                full = _canonicalize_pin_id(f"{ref}-{ptxt}")
                                if full and full in normalized_pinlist:
                                    hits += 1
                            page_penalty = _page_penalty_for_refdes(ref, page_idx + 1)
                            source_pri = 0 if info["source"] == "body" else 1
                            rank = (-hits, page_penalty, source_pri, info["dist_sq"])
                            if hits > best_hits or (hits == best_hits and (best_rank is None or rank < best_rank)):
                                best_ref = ref
                                best_hits = hits
                                best_rank = rank
                        if best_ref and best_hits > 0:
                            return best_ref

                    best_ref = None
                    best_rank = None
                    for ref, info in candidates.items():
                        page_penalty = _page_penalty_for_refdes(ref, page_idx + 1)
                        source_pri = 0 if info["source"] == "body" else 1
                        rank = (page_penalty, source_pri, info["dist_sq"])
                        if best_rank is None or rank < best_rank:
                            best_rank = rank
                            best_ref = ref
                    return best_ref

                parent_refdes_by_group = {}
                for g in current_groups:
                    if g["mode"] != "piece_part":
                        continue
                    entries = group_entries.get(g["name"], [])
                    if not entries:
                        continue
                    pin_texts = []
                    for e in entries:
                        t = e["text"]
                        is_ref = legacy_logic.REFDES_RE.fullmatch(t) and not legacy_logic.POWER_SOURCE_RE.match(t)
                        if not is_ref and ga.is_pin_candidate(t, max_length=max_pin_length):
                            pin_texts.append(t)
                    parent = find_parent_refdes(g["rect"], pin_texts)
                    if parent:
                        parent_refdes_by_group[g["name"]] = parent

                qt_lookup_cache = {}

                for g in current_groups:
                    group_name = g["name"]
                    group_mode = g["mode"]
                    entries = group_entries.get(group_name, [])
                    if not entries:
                        continue

                    for e_idx, entry in enumerate(entries):
                        if e_idx % 200 == 0:
                            check_cancelled(stop_event, "Token processing cancelled by user.")

                        text = entry["text"]
                        rect = entry["rect"]
                        cx, cy = entry["center"]
                        is_prov = entry["is_prov"]

                        if group_mode == "functional":
                            if legacy_logic._is_blacklisted(text, config):
                                continue

                            is_refdes = legacy_logic.REFDES_RE.fullmatch(text) and not legacy_logic.POWER_SOURCE_RE.match(text)
                            if not is_refdes:
                                continue

                            base = legacy_logic.strip_suffix(text)
                            if is_prov:
                                if "PROVISIONAL" not in grouped_data:
                                    grouped_data["PROVISIONAL"] = {
                                        "verified": set(),
                                        "unverified": set(),
                                        "tokens": set(),
                                        "pages": set(),
                                        "mode": "functional",
                                        "token_pages": {},
                                    }
                                grouped_data["PROVISIONAL"]["unverified"].add(base)
                                grouped_data["PROVISIONAL"]["pages"].add(page_idx + 1)
                                _track_token_page(grouped_data["PROVISIONAL"], base, page_idx + 1)
                                _dbg((page_idx, rect, (1, 0.5, 0), "PROV"))
                            else:
                                norm_base = canonicalize_refdes(base)
                                if norm_base in normalized_bom:
                                    grouped_data[group_name]["verified"].add(base)
                                    _dbg((page_idx, rect, (0, 0.8, 0), "VERIFIED"))
                                else:
                                    grouped_data[group_name]["unverified"].add(base)
                                    _dbg((page_idx, rect, (0.8, 0.4, 0), "UNVERIFIED"))
                                grouped_data[group_name]["pages"].add(page_idx + 1)
                                _track_token_page(grouped_data[group_name], base, page_idx + 1)
                            continue

                        # piece_part mode
                        if legacy_logic._is_blacklisted(text, config):
                            continue

                        is_refdes = legacy_logic.REFDES_RE.fullmatch(text) and not legacy_logic.POWER_SOURCE_RE.match(text)
                        is_pin = ga.is_pin_candidate(text, max_length=max_pin_length)

                        if is_refdes:
                            base = legacy_logic.strip_suffix(text)
                            if is_prov:
                                if "PROVISIONAL" not in grouped_data:
                                    grouped_data["PROVISIONAL"] = {
                                        "verified": set(),
                                        "unverified": set(),
                                        "tokens": set(),
                                        "pages": set(),
                                        "mode": "piece_part",
                                        "token_pages": {},
                                    }
                                grouped_data["PROVISIONAL"]["tokens"].add(base)
                                grouped_data["PROVISIONAL"]["pages"].add(page_idx + 1)
                                _track_token_page(grouped_data["PROVISIONAL"], base, page_idx + 1)
                                _dbg((page_idx, rect, (1, 0.5, 0), "PROV"))
                            else:
                                grouped_data[group_name]["tokens"].add(base)
                                grouped_data[group_name]["pages"].add(page_idx + 1)
                                _track_token_page(grouped_data[group_name], base, page_idx + 1)
                                _dbg((page_idx, rect, (0, 1, 0), "COMP"))
                            continue

                        if not is_pin:
                            continue

                        if pinlist_qualified_pins and group_name in pinlist_qualified_pins:
                            qualified_tokens = pinlist_qualified_pins[group_name]
                            cache_key = (page_idx, group_name)
                            if cache_key not in qt_lookup_cache:
                                qt_lookup_cache[cache_key] = {
                                    (qt.text, round(qt.center[0] / 5) * 5, round(qt.center[1] / 5) * 5): qt
                                    for qt in qualified_tokens
                                }
                            match_key = (text.upper(), round(cx / 5) * 5, round(cy / 5) * 5)
                            matching_token = qt_lookup_cache[cache_key].get(match_key)

                            if matching_token:
                                if matching_token.suppressed:
                                    _dbg((page_idx, rect, (0.5, 0.5, 0.5), "PIN_SUPPRESS_PASSIVE"))
                                    continue
                                if matching_token.drop_reason:
                                    _dbg((page_idx, rect, (0.7, 0.3, 0.3), f"PIN_DROP:{matching_token.drop_reason}"))
                                    continue
                                if matching_token.parent_refdes:
                                    val = f"{matching_token.parent_refdes}-{matching_token.text}"
                                    canon = _canonicalize_pin_id(val)
                                    if not canon or canon not in normalized_pinlist:
                                        _dbg((page_idx, rect, (0.6, 0.6, 0.6), "PIN_FILTERED"))
                                        continue
                                    grouped_data[group_name]["tokens"].add(val)
                                    grouped_data[group_name]["pages"].add(page_idx + 1)
                                    _track_token_page(grouped_data[group_name], val, page_idx + 1)
                                    _dbg((page_idx, rect, (0, 0.8, 0.4), f"PIN_CLUSTER:{matching_token.parent_refdes}"))
                                continue

                            _dbg((page_idx, rect, (0.6, 0.6, 0.6), "PIN_EXCLUDED"))
                            continue

                        mapping = None
                        candidates = pin_lookup_by_label.get((page_idx, text), [])
                        if len(candidates) > 1 and normalized_bom_pages:
                            matched = [c for c in candidates if _is_strong_page_match(c.refdes, page_idx + 1)]
                            if matched:
                                candidates = matched
                        if len(candidates) == 1:
                            mapping = candidates[0]
                        elif len(candidates) > 1:
                            mapping = legacy_engine._disambiguate_pin_mapping(
                                candidates,
                                g["rect"],
                                body_rects,
                                page_idx,
                                (cx, cy),
                            )

                        parent_refdes = parent_refdes_by_group.get(group_name)

                        parent_prefix = None
                        if mapping and mapping.refdes:
                            parent_prefix = get_prefix(mapping.refdes)
                        elif parent_refdes:
                            parent_prefix = get_prefix(parent_refdes)

                        if parent_prefix and not should_analyze_pins(parent_prefix):
                            continue

                        if mapping:
                            body_key = (page_idx, mapping.refdes)
                            if not normalized_pinlist and body_key in body_rects:
                                if legacy_logic.annotation_box_contains_body(g["rect"], body_rects[body_key]):
                                    continue
                            val = mapping.full_identifier
                            _dbg((page_idx, rect, (0, 0.5, 1), "PIN_QUAL"))
                        elif parent_refdes:
                            body_key = (page_idx, parent_refdes)
                            if not normalized_pinlist and body_key in body_rects:
                                if legacy_logic.annotation_box_contains_body(g["rect"], body_rects[body_key]):
                                    continue
                            val = f"{parent_refdes}-{text}"
                            _dbg((page_idx, rect, (0.2, 0.6, 1), "PIN_PARENT"))
                        else:
                            box_refdes = legacy_logic._find_refdes_in_box(words, g["rect"], (cx, cy))
                            if box_refdes:
                                val = f"{box_refdes}-{text}"
                                _dbg((page_idx, rect, (0.5, 0.5, 1), "PIN_BOX"))
                            else:
                                val = f"PIN-{text}"
                                _dbg((page_idx, rect, (0.5, 0.5, 0.5), "PIN_UNQUAL"))

                        if normalized_pinlist:
                            canon = _canonicalize_pin_id(val)
                            if not canon or canon not in normalized_pinlist:
                                _dbg((page_idx, rect, (0.6, 0.6, 0.6), "PIN_FILTERED"))
                                continue

                        grouped_data[group_name]["tokens"].add(val)
                        grouped_data[group_name]["pages"].add(page_idx + 1)
                        _track_token_page(grouped_data[group_name], val, page_idx + 1)

            if debug_pdf_path:
                log("Generating debug PDF...")
                try:
                    for p_idx, r, col, label in debug_shapes:
                        if stop_event and stop_event.is_set():
                            break
                        pg = doc[p_idx]
                        pg.draw_rect(r, color=col, width=1.5 if label in ("GROUP", "VERIFIED") else 0.75)
                        if col == (1, 0, 0):
                            pg.insert_text((r[0], r[1] - 2), label, color=col, fontsize=6)
                    doc.save(str(debug_pdf_path))
                    log(f"  Debug PDF saved: {debug_pdf_path}")
                except Exception as ex:
                    log(f"WARNING: Failed to save debug PDF: {ex}")
                    _logger.exception("Debug PDF save failed")
        finally:
            zombie_count = legacy_engine.cleanup_words_extraction_threads(timeout_per_thread=2.0)
            if zombie_count > 0:
                log(f"Cleaned up {zombie_count} background word extraction thread(s)")

    results = _format_hybrid_results_nextgen(
        grouped_data, bom_set, bom_page_map, log,
        normalized_bom=normalized_bom,
        normalized_bom_pages=normalized_bom_pages,
    )
    if collect_metrics:
        page_count = observed_page_count
        if page_count <= 0:
            try:
                with fitz.open(str(pdf_path)) as _tmp_doc:
                    page_count = len(_tmp_doc)
            except Exception:
                page_count = max((g[0] for g in groups), default=-1) + 1
        metrics = legacy_engine.collect_page_metrics_from_debug_shapes(
            debug_shapes or [],
            page_count,
        )
        return results, metrics
    return results
