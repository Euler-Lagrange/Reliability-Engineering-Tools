#!/usr/bin/env python3
"""Build the Python sidecar as a standalone executable using PyInstaller."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend" / "python"
ENTRY = BACKEND / "sidecar_main.py"
OUTPUT = ROOT / "local_build"

def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "reliability-tools-sidecar",
        "--distpath", str(OUTPUT),
        "--workpath", str(ROOT / "build" / "sidecar_build"),
        "--specpath", str(ROOT / "build"),
        # Add all backend packages as data
        "--add-data", f"{BACKEND / 'common'};common",
        "--add-data", f"{BACKEND / 'shared'};shared",
        "--add-data", f"{BACKEND / 'fmea'};fmea",
        "--add-data", f"{BACKEND / 'bom_compare'};bom_compare",
        "--add-data", f"{BACKEND / 'failure_rate'};failure_rate",
        "--add-data", f"{BACKEND / 'refdes_extractor'};refdes_extractor",
        "--add-data", f"{BACKEND / 'refdes_test'};refdes_test",
        # Hidden imports that PyInstaller might miss
        "--hidden-import", "common",
        "--hidden-import", "common.cancellation",
        "--hidden-import", "common.column_synonyms",
        "--hidden-import", "common.excel_styles",
        "--hidden-import", "common.exceptions",
        "--hidden-import", "common.fmea_utils",
        "--hidden-import", "common.logger",
        "--hidden-import", "common.partition_id",
        "--hidden-import", "common.refdes_utils",
        "--hidden-import", "common.user_facing_labels",
        "--hidden-import", "common.utils",
        "--hidden-import", "common.validation_utils",
        "--hidden-import", "shared.pre_run_validation",
        "--hidden-import", "fmea.runtime",
        "--hidden-import", "fmea.fmea_generator_logic",
        "--hidden-import", "fmea.fmea_template_analyzer",
        "--hidden-import", "fmea.fmea_template_writer",
        "--hidden-import", "bom_compare.runtime",
        "--hidden-import", "bom_compare.bom_compare_logic",
        "--hidden-import", "bom_compare.custom_compare",
        "--hidden-import", "bom_compare.group_analysis",
        "--hidden-import", "bom_compare.fmea_coverage",
        "--hidden-import", "bom_compare.excel_export",
        "--hidden-import", "bom_compare.extraction_compare",
        "--hidden-import", "failure_rate.runtime",
        "--hidden-import", "failure_rate.failure_rate_logic",
        "--hidden-import", "refdes_extractor.runtime",
        "--hidden-import", "refdes_extractor.refdes_extractor_logic",
        "--hidden-import", "refdes_extractor.extraction_engine",
        "--hidden-import", "refdes_extractor.geometry_analyzer",
        "--hidden-import", "refdes_extractor.bom_loader",
        "--hidden-import", "refdes_extractor.coverage_report",
        "--hidden-import", "refdes_extractor.validation_notes",
        "--hidden-import", "refdes_extractor.pinlist_parenting",
        "--hidden-import", "refdes_extractor.group_detection",
        "--hidden-import", "refdes_test.refdes_test_logic",
        "--hidden-import", "refdes_test.nextgen_engine",
        "--hidden-import", "refdes_test.refdes_darkstar_shared",
        # Ensure openpyxl and fitz are bundled
        "--hidden-import", "openpyxl",
        "--hidden-import", "fitz",
        "--hidden-import", "pymupdf",
        # Clean build
        "--clean",
        "--noconfirm",
        # Entry point
        str(ENTRY),
    ]

    print(f"Building sidecar from: {ENTRY}")
    print(f"Output: {OUTPUT / 'reliability-tools-sidecar.exe'}")
    result = subprocess.run(cmd, cwd=str(BACKEND))
    if result.returncode != 0:
        print("ERROR: PyInstaller build failed")
        sys.exit(1)

    # Verify the output
    exe = OUTPUT / "reliability-tools-sidecar.exe"
    if not exe.exists():
        print(f"ERROR: Expected output not found: {exe}")
        sys.exit(1)

    # Run self-test
    print("Running sidecar self-test...")
    test = subprocess.run([str(exe), "--self-test"], capture_output=True, text=True)
    if test.returncode != 0:
        print(f"ERROR: Sidecar self-test failed: {test.stderr}")
        sys.exit(1)
    print(f"OK: {test.stdout.strip()}")
    print(f"Sidecar built: {exe} ({exe.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
