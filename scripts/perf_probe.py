#!/usr/bin/env python3
"""Performance probe — synthetic large-input stress test for the backends.

Run from the repo root with the project venv:

    .venv\\Scripts\\python.exe scripts\\perf_probe.py [--rows 50000]

Generates a synthetic BOM / grouping / failure-modes trio of the requested
size (fake RefDes + part numbers only — no real design data), then drives
the FMEA, BOM Compare, and Failure Rate execute paths in-process and
reports wall time and peak memory per run, plus cancellation latency
(time from cancel() to CancellationError surfacing) for the FMEA path.

This is a PROBE, not part of the test suite — it is deliberately slow.
Baselines live in docs/reviews/PERF_BASELINES.md.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import threading
import time
import tracemalloc
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend" / "python"))

import pandas as pd  # noqa: E402

PREFIXES = ["R", "C", "U", "L", "Q", "CR", "VR", "K"]
COMMODITIES = [
    ("Resistor", "Chip"),
    ("Capacitor", "Ceramic"),
    ("Microcircuit", "Digital"),
    ("Inductor", "Power"),
    ("Transistor", "FET"),
]


def build_fixtures(root: Path, rows: int, group_size: int = 8) -> dict:
    """Write synthetic grouping/BOM/failure-mode workbooks of ``rows`` parts."""
    bom_rows = []
    group_rows = []
    fr_rows = []
    group_members: list[str] = []
    group_index = 0
    for i in range(rows):
        prefix = PREFIXES[i % len(PREFIXES)]
        ref = f"{prefix}{i + 1}"
        c1, c2 = COMMODITIES[i % len(COMMODITIES)]
        bom_rows.append(
            {
                "Reference Designator": ref,
                "Part Number": f"PN-{i % 997:04d}",
                "Description": f"Synthetic part {i + 1}",
                "BAE HDA Commodity I": c1,
                "BAE HDA Commodity II": c2,
                "Part Usage": "1",
            }
        )
        fr_rows.append({"Reference Designator": ref, "Failure Rate": 1e-6})
        group_members.append(ref)
        if len(group_members) == group_size or i == rows - 1:
            group_index += 1
            group_rows.append(
                {
                    "Component Group": f"BLK-{group_index:05d}",
                    "Reference Designator": ", ".join(group_members),
                    "Function Description": f"Synthetic block {group_index}",
                    "Schematic Page": str(group_index % 40 + 1),
                }
            )
            group_members = []

    fm_rows = []
    for c1, c2 in COMMODITIES:
        fm_rows.append(
            {
                "FMD-2016 Commodity Type 1": c1,
                "FMD-2016 Commodity Type 2": c2,
                "Failure Mode": "Open",
                "Failure Mode Ratio": 0.6,
            }
        )
        fm_rows.append(
            {
                "FMD-2016 Commodity Type 1": c1,
                "FMD-2016 Commodity Type 2": c2,
                "Failure Mode": "Short",
                "Failure Mode Ratio": 0.4,
            }
        )

    paths = {
        "bom": root / "bom.xlsx",
        "grouping": root / "grouping.xlsx",
        "fm": root / "failure_modes.xlsx",
        "prediction": root / "prediction.xlsx",
    }
    pd.DataFrame(bom_rows).to_excel(paths["bom"], index=False)
    pd.DataFrame(group_rows).to_excel(paths["grouping"], index=False)
    pd.DataFrame(fm_rows).to_excel(paths["fm"], index=False)
    pd.DataFrame(fr_rows).to_excel(paths["prediction"], index=False)
    return paths


def _state(role: str, path: Path, sheet: str = "Sheet1") -> dict:
    return {
        "role": role,
        "label": role,
        "path": str(path),
        "selectedSheet": sheet,
        "source": "desktop-bridge",
        "isResolvingSheets": False,
        "isAnalyzing": False,
        "resolutionError": None,
        "sheets": [{"id": "s1", "label": sheet}],
    }


def timed(label: str, fn) -> tuple[float, float]:
    tracemalloc.start()
    start = time.perf_counter()
    fn()
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f"  {label:<38} {elapsed:8.2f}s   peak +{peak / 1e6:7.1f} MB")
    return elapsed, peak


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=50_000)
    args = parser.parse_args()

    from bom_compare.runtime import execute_run_request as bom_execute
    from failure_rate.runtime import execute_run_request as fr_execute
    from fmea.runtime import execute_run_request as fmea_execute

    with tempfile.TemporaryDirectory(prefix="perf_probe_") as tmp:
        root = Path(tmp)
        print(f"perf_probe: generating {args.rows:,} synthetic parts ...")
        gen_start = time.perf_counter()
        paths = build_fixtures(root, args.rows)
        print(f"  fixture generation                     {time.perf_counter() - gen_start:8.2f}s")

        out_dir = root / "out"
        out_dir.mkdir()

        fmea_body = {
            "workflowId": "piece_part_generate",
            "outputStrategyId": "new_workbook_standard",
            "outputDirectory": str(out_dir),
            "options": {"failureModesStandard": "FMD-2016"},
            "inputs": [
                _state("grouping", paths["grouping"]),
                _state("bom", paths["bom"]),
                _state("failureModes", paths["fm"]),
            ],
            "mappings": [],
        }
        timed("FMEA piece_part_generate", lambda: fmea_execute(dict(fmea_body)))

        bom_body = {
            "workflowId": "bom_compare_group",
            "outputStrategyId": "new_workbook_standard",
            "outputDirectory": str(out_dir),
            "options": {
                "base_match": False,
                "exact_match": False,
                "ignore_dnp": True,
                "check_part_usage": True,
                "check_fmr": False,
            },
            "inputs": [
                _state("grouping", paths["grouping"]),
                _state("bom", paths["bom"]),
            ],
            "mappings": [
                {"canonical": "grouping_group_col", "mappedTo": "Component Group", "status": "mapped"},
                {"canonical": "grouping_refdes_col", "mappedTo": "Reference Designator", "status": "mapped"},
                {"canonical": "bom_refdes_col", "mappedTo": "Reference Designator", "status": "mapped"},
                {"canonical": "bom_desc_col", "mappedTo": "Description", "status": "mapped"},
            ],
        }
        timed("BOM Compare group", lambda: bom_execute(dict(bom_body)))

        fr_body = {
            "workflowId": "failure_rate_link",
            "outputStrategyId": "new_workbook_standard",
            "outputDirectory": str(out_dir),
            "options": {"unit_mode": "per_hour", "validate_fmr": False},
            "inputs": [
                _state("prediction", paths["prediction"]),
                _state("fmea", paths["grouping"]),
            ],
            "mappings": [
                {"canonical": "pred_ref", "mappedTo": "Reference Designator", "status": "mapped"},
                {"canonical": "pred_fr", "mappedTo": "Failure Rate", "status": "mapped"},
                {"canonical": "fmea_cause", "mappedTo": "Reference Designator", "status": "mapped"},
                {"canonical": "fmea_ratio", "mappedTo": "Schematic Page", "status": "mapped"},
                {"canonical": "fmea_usage", "mappedTo": "Schematic Page", "status": "mapped"},
            ],
        }
        timed("Failure Rate link", lambda: fr_execute(dict(fr_body)))

        # --- Cancellation latency: cancel the FMEA run 1s in, measure how
        # long the worker takes to actually stop. ---
        from common.cancellation import CancellationError

        captured: dict = {}
        result: dict = {}

        def _run() -> None:
            try:
                fmea_execute(
                    dict(fmea_body),
                    processor_ready_callback=lambda proc: captured.__setitem__("proc", proc),
                )
                result["outcome"] = "completed-before-cancel"
            except CancellationError:
                result["outcome"] = "cancelled"
                result["at"] = time.perf_counter()
            except InterruptedError:
                result["outcome"] = "cancelled"
                result["at"] = time.perf_counter()

        worker = threading.Thread(target=_run)
        worker.start()
        deadline = time.perf_counter() + 60
        while "proc" not in captured and worker.is_alive() and time.perf_counter() < deadline:
            time.sleep(0.01)
        time.sleep(1.0)
        cancel_sent = time.perf_counter()
        if "proc" in captured:
            captured["proc"].cancel.cancel()
        else:
            print("  cancellation: processor_ready_callback never fired within 60s")
        worker.join(timeout=180)
        if result.get("outcome") == "cancelled":
            print(f"  cancellation latency                   {result['at'] - cancel_sent:8.2f}s")
        else:
            print(f"  cancellation: {result.get('outcome', 'worker did not finish')}")

    print("perf_probe: done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
