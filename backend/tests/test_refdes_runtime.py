"""Tests for RefDes Extractor runtime helpers (backend/python/refdes_extractor/runtime.py)."""

from __future__ import annotations

import pytest

from common.exceptions import ValidationError
from refdes_extractor.runtime import (
    _results_dataframe,
    _validate_options,
    execute_run_request,
    validate_run_request,
)


def test_adaptive_orphan_threshold_zero_is_valid() -> None:
    # Adversarial-review fix: 0 is a legitimate threshold ("trigger full geometry
    # even with zero orphans"), the frontend control allows a minimum of 0, and
    # it is the integer analogue of adaptive_orphan_ratio=0.0. Validating it as
    # >= 1 would hard-block a UI-permitted value.
    assert _validate_options({"adaptive_orphan_threshold": 0}) == []
    bad = _validate_options({"adaptive_orphan_threshold": -1})
    assert any(name == "adaptive_orphan_threshold" for name, _ in bad)


def test_every_config_field_is_validated() -> None:
    # Guard against a future RefDesConfig field being added without a matching
    # validation category (which would leave it silently unvalidated, mirroring
    # from_options' silent drop).
    from dataclasses import fields

    from refdes_extractor.runtime import (
        RefDesConfig,
        _BOOL_OPTIONS,
        _ENUM_OPTIONS,
        _NON_NEGATIVE_INT_OPTIONS,
        _POSITIVE_INT_OPTIONS,
        _POSITIVE_NUMBER_OPTIONS,
        _RATIO_OPTION,
    )

    validated = (
        set(_BOOL_OPTIONS)
        | set(_ENUM_OPTIONS)
        | set(_POSITIVE_INT_OPTIONS)
        | set(_NON_NEGATIVE_INT_OPTIONS)
        | set(_POSITIVE_NUMBER_OPTIONS)
        | {_RATIO_OPTION}
    )
    assert validated == {f.name for f in fields(RefDesConfig)}


def test_results_dataframe_drops_internal_columns_after_annotation() -> None:
    # #4: internal markers ("_is_gap" from detect_sequence_gaps, "_row_style"
    # from annotate_results) must not leak into the user-facing sheet — and
    # the display headers are Title Case with the Validation Notes column.
    from refdes_extractor.validation_notes import annotate_results

    rows = [
        {"group": "U200", "failure mode causes": "Open", "component count": 3, "pages": "1"},
        {
            "group": "U201 (GROUP NOT DETECTED)",
            "failure mode causes": "",
            "component count": 0,
            "pages": "",
            "_is_gap": True,  # internal styling marker from detect_sequence_gaps
        },
    ]
    df = _results_dataframe(annotate_results(rows, bom_provided=True))
    assert "_is_gap" not in df.columns
    assert "_row_style" not in df.columns
    assert list(df.columns) == [
        "Group",
        "Failure Mode Causes",
        "Component Count",
        "Pages",
        "Validation Notes",
    ]
    assert len(df) == 2  # rows preserved; only the internal columns dropped


def test_results_dataframe_renames_to_display_headers() -> None:
    rows = [
        {"group": "U200", "failure mode causes": "Open", "component count": 3, "pages": "1"},
    ]
    df = _results_dataframe(rows)
    assert list(df.columns) == ["Group", "Failure Mode Causes", "Component Count", "Pages"]
    assert len(df) == 1


# ---------------------------------------------------------------------------
# #5 Stage 2 — engine-option validation
# ---------------------------------------------------------------------------

# The 16 user-settable engine parameters at their shipped defaults (mirrors the
# frontend RefDesOptions defaults, which mirror RefDesConfig). Every value is
# valid, so this doubles as the "all-defaults pass clean" fixture.
_DEFAULT_OPTIONS = {
    "extraction_mode": "functional",
    "backend_mode": "auto",
    "geometry_analysis_enabled": True,
    "adaptive_geometry_enabled": True,
    "geometry_batch_size": 10,
    "max_pin_label_length": 4,
    "prov_distance": 15.0,
    "geometry_subprocess_enabled": False,
    "geometry_batch_timeout_seconds": 240.0,
    "geometry_batch_checkpoint_enabled": True,
    "pin_assignment_threshold": 50.0,
    "refdes_search_radius": 100.0,
    "adaptive_orphan_threshold": 5,
    "adaptive_orphan_ratio": 0.3,
    "adaptive_max_pages": 10,
    "pinlist_prefers_annotation_mode": True,
}


def _offenders(errors) -> list[str]:
    return sorted(name for name, _ in errors)


def test_validate_options_all_defaults_pass_clean() -> None:
    # (c) valid values + all-defaults produce no errors.
    assert _validate_options(dict(_DEFAULT_OPTIONS)) == []


def test_validate_options_empty_and_non_dict_pass_clean() -> None:
    assert _validate_options({}) == []
    assert _validate_options(None) == []
    assert _validate_options("nonsense") == []


def test_validate_options_valid_non_default_values_pass_clean() -> None:
    # (c) valid non-default values across every category are accepted.
    assert _validate_options({
        "extraction_mode": "piece_part",
        "backend_mode": "legacy",
        "geometry_subprocess_enabled": True,
        "geometry_batch_size": 25,
        "pin_assignment_threshold": 75.0,
        "adaptive_orphan_ratio": 0.0,
    }) == []


def test_validate_options_rejects_wrong_typed_number() -> None:
    # (a) a wrong-typed value (non-numeric string) is flagged.
    assert _offenders(_validate_options({"geometry_batch_size": "abc"})) == ["geometry_batch_size"]
    assert _offenders(_validate_options({"prov_distance": "wide"})) == ["prov_distance"]


def test_validate_options_rejects_out_of_range_ratio() -> None:
    # (b) an out-of-range ratio is flagged in both directions.
    assert _offenders(_validate_options({"adaptive_orphan_ratio": 5})) == ["adaptive_orphan_ratio"]
    assert _offenders(_validate_options({"adaptive_orphan_ratio": -0.1})) == ["adaptive_orphan_ratio"]


def test_validate_options_ratio_boundaries_are_valid() -> None:
    for value in (0, 0.0, 1, 1.0, 0.3):
        assert _validate_options({"adaptive_orphan_ratio": value}) == [], value


def test_validate_options_positive_int_rejects_zero_negative_fractional() -> None:
    assert _offenders(_validate_options({"geometry_batch_size": 0})) == ["geometry_batch_size"]
    assert _offenders(_validate_options({"adaptive_max_pages": -1})) == ["adaptive_max_pages"]
    assert _offenders(_validate_options({"max_pin_label_length": 2.5})) == ["max_pin_label_length"]
    assert _offenders(_validate_options({"adaptive_orphan_threshold": "x"})) == ["adaptive_orphan_threshold"]


def test_validate_options_positive_int_accepts_whole_valued_float() -> None:
    # A NumberField that emits 10.0 for an integer control must still pass.
    assert _validate_options({"geometry_batch_size": 10.0}) == []


def test_validate_options_positive_number_rejects_zero_and_negative() -> None:
    assert _offenders(_validate_options({"prov_distance": 0})) == ["prov_distance"]
    assert _offenders(_validate_options({"pin_assignment_threshold": -5})) == ["pin_assignment_threshold"]
    assert _offenders(_validate_options({"geometry_batch_timeout_seconds": 0.0})) == [
        "geometry_batch_timeout_seconds"
    ]


def test_validate_options_number_rejects_non_finite() -> None:
    # NaN / inf must not slip past a ">0" comparison.
    assert _offenders(_validate_options({"refdes_search_radius": float("inf")})) == ["refdes_search_radius"]
    assert _offenders(_validate_options({"prov_distance": float("nan")})) == ["prov_distance"]


def test_validate_options_bool_flag_rejects_non_bool() -> None:
    # bool is an int subclass — an unguarded numeric check would accept 1/0.
    assert _offenders(_validate_options({"geometry_analysis_enabled": 1})) == ["geometry_analysis_enabled"]
    assert _offenders(_validate_options({"pinlist_prefers_annotation_mode": "yes"})) == [
        "pinlist_prefers_annotation_mode"
    ]
    assert _validate_options({"geometry_subprocess_enabled": True}) == []
    assert _validate_options({"geometry_subprocess_enabled": False}) == []


def test_validate_options_number_field_rejects_bool() -> None:
    # A boolean must not masquerade as a numeric value.
    assert _offenders(_validate_options({"geometry_batch_size": True})) == ["geometry_batch_size"]


def test_validate_options_enum_rejects_unknown_value() -> None:
    assert _offenders(_validate_options({"extraction_mode": "bogus"})) == ["extraction_mode"]
    assert _offenders(_validate_options({"backend_mode": "turbo"})) == ["backend_mode"]
    assert _validate_options({"extraction_mode": "piece_part", "backend_mode": "nextgen"}) == []


def test_validate_options_ignores_unknown_keys() -> None:
    # Mirrors RefDesConfig.from_options' silent drop of unknown keys.
    assert _validate_options({"totally_unknown_key": "abc", "another": 5}) == []


def test_validate_options_reports_every_offender() -> None:
    errors = _validate_options({
        "geometry_batch_size": "abc",
        "adaptive_orphan_ratio": 5,
        "extraction_mode": "bogus",
    })
    assert _offenders(errors) == ["adaptive_orphan_ratio", "extraction_mode", "geometry_batch_size"]


# --- Integration: validate_run_request / execute_run_request wiring -----------

def _base_body(options=None) -> dict:
    return {
        "workflowId": "refdes_extract",
        "inputs": [{"role": "pdf", "path": "C:/schematic.pdf"}],
        "options": {} if options is None else options,
    }


def test_validate_run_request_accepts_default_options() -> None:
    pytest.importorskip("fitz")
    resp = validate_run_request(_base_body(dict(_DEFAULT_OPTIONS)))
    assert resp["ok"] is True
    assert resp["reason_code"] == "ok"


def test_validate_run_request_blocks_wrong_typed_option() -> None:
    # (a) wrong-typed value is a BLOCKING validation error, with a per-option entry.
    pytest.importorskip("fitz")
    resp = validate_run_request(_base_body({"geometry_batch_size": "abc"}))
    assert resp["ok"] is False
    assert resp["reason_code"] == "invalid_option"
    assert "geometry_batch_size" in resp["toast_text"]
    assert any(
        m["area"] == "Options" and "geometry_batch_size" in m["title"]
        for m in resp["validations"]
    )


def test_validate_run_request_blocks_out_of_range_ratio() -> None:
    # (b) out-of-range value is a BLOCKING validation error.
    pytest.importorskip("fitz")
    resp = validate_run_request(_base_body({"adaptive_orphan_ratio": 5}))
    assert resp["ok"] is False
    assert resp["reason_code"] == "invalid_option"
    assert "adaptive_orphan_ratio" in resp["toast_text"]


def test_validate_run_request_missing_file_precedes_option_check() -> None:
    # A missing required PDF must win over a bad option (setup blockers first).
    pytest.importorskip("fitz")
    body = {"workflowId": "refdes_extract", "inputs": [], "options": {"geometry_batch_size": "abc"}}
    resp = validate_run_request(body)
    assert resp["ok"] is False
    assert resp["reason_code"] == "missing_files"


def test_execute_run_request_raises_on_invalid_option() -> None:
    # A bad option fails visibly at execute time too, before any engine work.
    pytest.importorskip("fitz")
    with pytest.raises(ValidationError):
        execute_run_request(_base_body({"adaptive_orphan_ratio": 5}))


# ----- Batch 5 (2026-07 stability sweep) -------------------------------------


def test_group_verification_summary_requires_components() -> None:
    """The verified/unverified metrics must reflect BOM verification content,
    not the "(Verified)" row-label suffix (which every regular group emits
    even when its Verified row is empty)."""
    from refdes_extractor.runtime import _summarize_group_verification

    results = [
        # Group A: Verified row EMPTY, all components unverified.
        {"group": "A (Verified)", "component count": 0},
        {"group": "A (Unverified)", "component count": 3},
        # Group B: genuinely verified components.
        {"group": "B (Verified)", "component count": 2},
        {"group": "B (Unverified)", "component count": 0},
        # Gap placeholder rows are skipped entirely.
        {"group": "C", "component count": 0, "_is_gap": True},
        {"group": "GROUP NOT DETECTED: D", "component count": 0},
    ]
    total, verified, unverified = _summarize_group_verification(results)
    assert total == 2, (total, verified, unverified)
    assert verified == 1, (total, verified, unverified)
    assert unverified == 1, (total, verified, unverified)


def test_config_manager_carries_out_folder_for_checkpoints(tmp_path) -> None:
    """The geometry-batch checkpoint writer early-returns without an
    out_folder; the runtime must pass the resolved output directory through
    to_config_manager or the checkpoint control is inert."""
    from refdes_extractor.runtime import RefDesConfig

    cm = RefDesConfig().to_config_manager(out_folder=str(tmp_path))
    assert cm.get("out_folder", "") == str(tmp_path)

    # Default stays empty (no checkpoint writes without a destination).
    cm_default = RefDesConfig().to_config_manager()
    assert cm_default.get("out_folder", "") == ""


def test_sidecar_main_installs_multiprocessing_freeze_support() -> None:
    """The sidecar ships as a PyInstaller --onefile exe and the geometry
    subprocess option uses mp spawn: without freeze_support() at the top of
    main(), frozen children re-run the sidecar loop instead of the worker."""
    import inspect

    import sidecar_main

    source = inspect.getsource(sidecar_main.main)
    assert "freeze_support()" in source, (
        "sidecar_main.main() must call multiprocessing.freeze_support() "
        "before anything else"
    )
