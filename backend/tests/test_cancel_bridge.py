"""
Direct unit tests for the BOM Compare and RefDes ``_CancelBridge`` classes.

These bridges expose a ``CancellationToken`` (``bridge.cancel``) AND a
``threading.Event`` (``bridge.stop_event``). The sidecar's ``ActiveRun``
calls ``processor.cancel.cancel()`` to request cancellation, but the inner
BOM compare and RefDes helpers consult ``stop_event.is_set()``. Before this
fix, the two events were independent, so cancelling never reached the
helpers. The bridges now share the underlying ``threading.Event`` between
the token and the public ``stop_event`` property — this test asserts that
invariant directly so a future regression is caught immediately.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make ``bom_compare`` and ``refdes_extractor`` importable when this test
# runs from the repo root via ``pytest backend/tests``. Mirrors the
# sidecar's import policy: everything resolves from ``backend/python``.
ROOT = Path(__file__).resolve().parents[2]
BACKEND_PYTHON = ROOT / "backend" / "python"
if str(BACKEND_PYTHON) not in sys.path:
    sys.path.insert(0, str(BACKEND_PYTHON))

from bom_compare.runtime import _CancelBridge as BomCompareCancelBridge  # noqa: E402
from refdes_extractor.runtime import _CancelBridge as RefDesCancelBridge  # noqa: E402


# ---------------------------------------------------------------------------
# BOM Compare bridge
# ---------------------------------------------------------------------------


def test_bom_compare_bridge_token_and_stop_event_share_underlying_event() -> None:
    bridge = BomCompareCancelBridge()
    # The CancellationToken's underlying event must be the SAME object as the
    # bridge's stop_event property — that's the whole point of the fix.
    assert bridge.cancel.event is bridge.stop_event


def test_bom_compare_bridge_token_cancel_sets_stop_event() -> None:
    bridge = BomCompareCancelBridge()
    assert not bridge.stop_event.is_set()
    bridge.cancel.cancel()
    assert bridge.stop_event.is_set()
    assert bridge.cancel.is_cancelled()


def test_bom_compare_bridge_request_cancel_still_works() -> None:
    """Backward-compat: the legacy ``request_cancel()`` method still cancels."""
    bridge = BomCompareCancelBridge()
    bridge.request_cancel()
    assert bridge.stop_event.is_set()
    assert bridge.cancel.is_cancelled()


def test_bom_compare_bridge_setting_stop_event_directly_also_cancels_token() -> None:
    """Some inner helpers may set the stop_event by hand; the token should agree."""
    bridge = BomCompareCancelBridge()
    bridge.stop_event.set()
    assert bridge.cancel.is_cancelled()


# ---------------------------------------------------------------------------
# RefDes bridge — same invariants
# ---------------------------------------------------------------------------


def test_refdes_bridge_token_and_stop_event_share_underlying_event() -> None:
    bridge = RefDesCancelBridge()
    assert bridge.cancel.event is bridge.stop_event


def test_refdes_bridge_token_cancel_sets_stop_event() -> None:
    bridge = RefDesCancelBridge()
    assert not bridge.stop_event.is_set()
    bridge.cancel.cancel()
    assert bridge.stop_event.is_set()
    assert bridge.cancel.is_cancelled()


def test_refdes_bridge_request_cancel_still_works() -> None:
    bridge = RefDesCancelBridge()
    bridge.request_cancel()
    assert bridge.stop_event.is_set()
    assert bridge.cancel.is_cancelled()


def test_refdes_bridge_setting_stop_event_directly_also_cancels_token() -> None:
    bridge = RefDesCancelBridge()
    bridge.stop_event.set()
    assert bridge.cancel.is_cancelled()
