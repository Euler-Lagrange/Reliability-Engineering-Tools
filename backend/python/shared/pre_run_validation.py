#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared helpers for precise pre-run validation messages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence


# Sentinel used by the frontend mapping table for "do not map this column".
# Mirrors frontend/src/app/types.ts DO_NOT_MAP_VALUE. Defined here — the
# shared pre-run validation module that every runtime adapter already imports
# — so the literal lives in exactly one place across the backend. The sentinel
# is a non-empty string, so ``_has_value`` would otherwise treat it as a valid
# mapping; runtime adapters must funnel sentinel-pinned required mappings
# through ``invalid_mappings`` so ``invalid_do_not_map_result`` fires.
DO_NOT_MAP_SENTINEL = "__do_not_map__"


@dataclass(frozen=True)
class ValidationResult:
    """Structured result for GUI pre-run validation."""

    ok: bool
    reason_code: str = "ok"
    toast_text: str = ""
    affected_labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class LabeledValue:
    """Human label plus current UI/control value."""

    label: str
    value: Any


@dataclass(frozen=True)
class LabeledState:
    """Human label plus a boolean readiness flag."""

    label: str
    ready: bool


def output_directory_validation(explicit_directory) -> dict[str, Any] | None:
    """Return a WARNING validation message when an explicit output directory is
    set but is not a usable (writable) directory, else ``None``.

    Tier-2 #19: an invalid ``outputDirectory`` used to pass validate green and
    then silently relocate the output at execute time (the resolver falls back
    to the first input file's folder). Surfacing it at validate time lets the
    user fix the path — or knowingly accept the fallback — before running.
    """
    # Local import: ``common`` is self-contained and this is a validate-time
    # (cold) path, so we avoid pulling it into module import.
    from common.utils import validate_explicit_output_directory

    candidate = str(explicit_directory).strip() if explicit_directory else ""
    if not candidate:
        return None  # No explicit directory — the default heuristic applies.
    if validate_explicit_output_directory(candidate, log_func=None) is not None:
        return None  # A real, writable directory.
    return {
        "id": "output_directory_unwritable",
        "severity": "warning",
        "area": "Output",
        "title": "Output folder not usable",
        "detail": (
            f"The chosen output folder '{candidate}' is not a writable "
            f"directory. The run will save next to the first input file "
            f"instead — update the folder if that isn't what you want."
        ),
    }


def append_output_directory_warning(response: dict, explicit_directory) -> None:
    """Append the Tier-2 #19 output-directory warning to a validate response's
    ``validations`` list, in place, when the explicit directory is unusable."""
    warning = output_directory_validation(explicit_directory)
    if warning is not None:
        response.setdefault("validations", []).append(warning)


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _labels_text(labels: Sequence[str]) -> str:
    return ", ".join(labels)


def summarize_labels(labels: Sequence[str], limit: int = 3) -> str:
    """Return a compact human-readable label list."""

    visible = list(labels[:limit])
    text = _labels_text(visible)
    remaining = len(labels) - len(visible)
    if remaining > 0:
        text += f" (+{remaining} more)"
    return text


def missing_required_files_result(missing_labels: Sequence[str]) -> ValidationResult:
    return ValidationResult(
        ok=False,
        reason_code="missing_files",
        toast_text=f"Select required files: {_labels_text(missing_labels)}.",
        affected_labels=tuple(missing_labels),
    )


def load_in_progress_result(message: str = "Columns/files are still loading. Please wait and try again.") -> ValidationResult:
    return ValidationResult(
        ok=False,
        reason_code="load_in_progress",
        toast_text=message,
    )


def not_loaded_result(unloaded_labels: Sequence[str], noun: str = "Load") -> ValidationResult:
    return ValidationResult(
        ok=False,
        reason_code="not_loaded",
        toast_text=f"{noun} current files/columns for: {_labels_text(unloaded_labels)}.",
        affected_labels=tuple(unloaded_labels),
    )


def missing_mappings_result(missing_labels: Sequence[str]) -> ValidationResult:
    return ValidationResult(
        ok=False,
        reason_code="missing_mappings",
        toast_text=f"Missing required mappings: {_labels_text(missing_labels)}.",
        affected_labels=tuple(missing_labels),
    )


def invalid_do_not_map_result(invalid_labels: Sequence[str]) -> ValidationResult:
    return ValidationResult(
        ok=False,
        reason_code="invalid_do_not_map",
        toast_text=f"Required mappings cannot use 'Do Not Map': {_labels_text(invalid_labels)}.",
        affected_labels=tuple(invalid_labels),
    )


def manual_mapping_fallback_message(missing_labels: Sequence[str], limit: int = 3) -> str:
    """Build a precise non-blocking warning for manual mapping fallback."""

    return (
        "Manual mapping incomplete. Auto-detect will be used for: "
        f"{summarize_labels(missing_labels, limit=limit)}"
    )


def validate_pre_run_state(
    *,
    required_files: Iterable[LabeledValue] = (),
    load_in_progress: bool = False,
    load_in_progress_message: str = "Columns/files are still loading. Please wait and try again.",
    loaded_states: Iterable[LabeledState] = (),
    not_loaded_message: str | None = None,
    required_mappings: Iterable[LabeledValue] = (),
    invalid_mappings: Iterable[LabeledValue] = (),
) -> ValidationResult:
    """Validate current GUI state and return the narrowest blocking message."""

    missing_files = [item.label for item in required_files if not _has_value(item.value)]
    if missing_files:
        return missing_required_files_result(missing_files)

    if load_in_progress:
        return load_in_progress_result(load_in_progress_message)

    unloaded = [item.label for item in loaded_states if not item.ready]
    if unloaded:
        if not_loaded_message:
            return ValidationResult(
                ok=False,
                reason_code="not_loaded",
                toast_text=not_loaded_message.format(labels=_labels_text(unloaded)),
                affected_labels=tuple(unloaded),
            )
        return not_loaded_result(unloaded)

    missing_mappings = [item.label for item in required_mappings if not _has_value(item.value)]
    if missing_mappings:
        return missing_mappings_result(missing_mappings)

    invalid = [item.label for item in invalid_mappings if _has_value(item.value)]
    if invalid:
        return invalid_do_not_map_result(invalid)

    return ValidationResult(ok=True)
