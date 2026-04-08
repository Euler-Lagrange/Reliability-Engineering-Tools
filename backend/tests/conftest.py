"""Test infrastructure: ensure backend/python is on sys.path so direct imports
of FMEA / common / runtime modules work for in-process unit tests.

The existing test_sidecar_main.py spawns the sidecar as a subprocess and
therefore doesn't need this — but Phase D's test_fmea_phase_d.py imports
FMEAProcessor directly for focused unit tests of the new inheritance,
BOM Additions, and functional_to_piecepart logic.
"""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND_PYTHON = Path(__file__).resolve().parents[1] / "python"
if str(_BACKEND_PYTHON) not in sys.path:
    sys.path.insert(0, str(_BACKEND_PYTHON))
