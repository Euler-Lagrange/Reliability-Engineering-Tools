"""Shared helper for building ``validate_run`` output_preview payloads.

The preview is a lightweight sample of source/input rows mapped into
review-friendly columns, so the frontend's Review drawer can confirm what
the tool is about to process without actually running it (see
`contracts/sidecar-protocol.md` for the contract).

Design constraints:

- Preview generation must never fail validation. Every entry point in this
  module catches ``Exception`` and returns ``None`` on any error.
- Reads are bounded by :data:`PREVIEW_ROW_CAP`. Callers hand in pre-loaded
  DataFrames whenever possible so the preview path does not duplicate
  IO already done by the validation step.
- Cancellation is honored by callers; this helper does no blocking IO of
  its own — it only slices already-loaded DataFrames.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Sequence

_logger = logging.getLogger(__name__)

# Hard cap on the number of preview rows the sidecar emits. Chosen to
# match the handoff spec (20 rows) — enough to show shape, small enough
# that serialization is trivial on even a huge output.
PREVIEW_ROW_CAP = 20

# Skip preview when the source file is larger than this — it's cheaper to
# emit nothing than to block the validation thread on a 50 MB Excel read.
# Callers may override with their own heuristics if needed.
PREVIEW_FILE_SIZE_LIMIT_BYTES = 10 * 1024 * 1024  # 10 MB


def _cell_to_string(value: Any) -> str:
    """Render a DataFrame cell as a preview-safe string.

    NaN / None / pandas NA collapse to empty string so the UI can line
    columns up without defensive null checks.
    """
    try:
        import pandas as pd  # local import so this module stays optional

        if value is None or pd.isna(value):
            return ""
    except Exception:
        if value is None:
            return ""
    text = str(value).strip()
    return text


def _resolve_columns(
    df_columns: Sequence[str],
    spec: Sequence[tuple[str, Sequence[str]]],
) -> list[tuple[str, str]]:
    """Map each (display, candidates) pair to the first candidate column that
    actually exists in ``df_columns``. Display names appear at most once in
    the result, preserving caller-supplied order.
    """
    resolved: list[tuple[str, str]] = []
    seen_displays: set[str] = set()
    lowered = {str(col).strip().lower(): col for col in df_columns}
    for display, candidates in spec:
        if display in seen_displays:
            continue
        for candidate in candidates:
            key = str(candidate).strip().lower()
            actual = lowered.get(key)
            if actual is not None:
                resolved.append((display, actual))
                seen_displays.add(display)
                break
    return resolved


def build_preview_from_dataframe(
    df: Any,
    column_spec: Sequence[tuple[str, Sequence[str]]],
    *,
    row_cap: int = PREVIEW_ROW_CAP,
    total_estimate: int | None = None,
) -> dict[str, Any] | None:
    """Slice a DataFrame down to an ``output_preview`` dict.

    Args:
        df: A pandas DataFrame (may be None or empty — both return None).
        column_spec: Ordered pairs of ``(display_header, candidates)`` where
            candidates is a list of DataFrame column names to try in order.
            The first candidate that exists wins; if none match, the display
            name is skipped.
        row_cap: Maximum number of rows to emit; the remainder is signaled
            via ``truncated``.
        total_estimate: Total rows the full output would contain. When
            ``None``, defaults to ``len(df)``.

    Returns:
        ``{"columns", "rows", "truncated", "total_estimated"}`` or
        ``None`` if a preview cannot be rendered (empty df, no columns
        resolved, or an unexpected exception during iteration).
    """
    if df is None:
        return None
    try:
        if getattr(df, "empty", True):
            return None
        resolved = _resolve_columns(list(df.columns), column_spec)
        if not resolved:
            return None
        total = int(total_estimate) if total_estimate is not None else int(len(df))
        head = df.head(row_cap)
        rows: list[list[str]] = []
        for _, row in head.iterrows():
            rows.append([_cell_to_string(row.get(actual)) for _, actual in resolved])
        return {
            "columns": [display for display, _ in resolved],
            "rows": rows,
            "truncated": total > row_cap,
            "total_estimated": total,
        }
    except Exception as exc:  # pragma: no cover - defensive
        _logger.debug("output_preview: DataFrame rendering failed (%s)", exc)
        return None


def build_preview_from_file(
    path: str | None,
    sheet: str | None,
    column_spec: Sequence[tuple[str, Sequence[str]]],
    *,
    row_cap: int = PREVIEW_ROW_CAP,
    log_callback: Callable[[str], None] | None = None,
) -> dict[str, Any] | None:
    """Read ``path`` with the sidecar's standard IO helpers and return a preview.

    Silently returns ``None`` on any failure — including missing files,
    locked files, oversized files, empty sheets, or unmappable columns.
    Preview generation is a best-effort garnish on validation; validation
    itself must not regress just because a preview could not be built.
    """
    if not path:
        return None
    try:
        p = Path(path)
        try:
            if p.exists() and p.stat().st_size > PREVIEW_FILE_SIZE_LIMIT_BYTES:
                return None
        except OSError:
            return None

        # Local imports so this helper does not drag pandas into module load
        # order when callers never actually invoke it (e.g., test stubs).
        from common import try_read_table, normalize_df_columns

        df = try_read_table(
            str(p),
            sheet_name=sheet or None,
            log_func=log_callback,
        )
        if df is None or getattr(df, "empty", True):
            return None
        df = normalize_df_columns(df)

        return build_preview_from_dataframe(
            df,
            column_spec,
            row_cap=row_cap,
            total_estimate=int(len(df)),
        )
    except Exception as exc:  # pragma: no cover - defensive
        _logger.debug(
            "output_preview: failed to build preview for path=%s sheet=%s (%s)",
            path,
            sheet,
            exc,
        )
        return None
