#!/usr/bin/env python3
"""Build the Python sidecar as a standalone executable using PyInstaller."""
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend" / "python"
ENTRY = BACKEND / "sidecar_main.py"
DEFAULT_OUTPUT = ROOT / "local_build"
BUILD_ROOT = ROOT / "build"
PACKAGE_NAMES = (
    "common",
    "shared",
    "fmea",
    "bom_compare",
    "failure_rate",
    "refdes_extractor",
    "refdes_test",
)


def _purge_source_bytecode() -> None:
    """Remove ignored interpreter caches before collecting package data."""
    backend_root = BACKEND.resolve()
    cache_dirs = sorted(
        BACKEND.rglob("__pycache__"),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for cache_dir in cache_dirs:
        resolved = cache_dir.resolve()
        if backend_root not in resolved.parents:
            raise RuntimeError(f"Refusing to remove cache outside backend tree: {resolved}")
        shutil.rmtree(resolved)
    for bytecode in BACKEND.rglob("*.py[co]"):
        resolved = bytecode.resolve()
        if backend_root not in resolved.parents:
            raise RuntimeError(f"Refusing to remove bytecode outside backend tree: {resolved}")
        resolved.unlink()


def _prepare_source_data(source_data_stage: Path) -> None:
    """Copy auditable Python sources without ignored cache artifacts."""
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
    for package_name in PACKAGE_NAMES:
        shutil.copytree(
            BACKEND / package_name,
            source_data_stage / package_name,
            ignore=ignore,
        )

    offenders = [
        path
        for path in source_data_stage.rglob("*")
        if path.name == "__pycache__" or path.suffix.lower() in {".pyc", ".pyo"}
    ]
    if offenders:
        sample = "\n  ".join(str(path) for path in offenders[:20])
        raise RuntimeError(f"Source-data staging contains bytecode:\n  {sample}")


def _assert_archive_is_auditable(exe: Path) -> None:
    """Reject bytecode data and prove packaged sources remain auditable."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller.utils.cliutils.archive_viewer",
            "--recursive",
            "--brief",
            str(exe),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Could not inspect packaged sidecar archive: {result.stderr.strip()}")

    archive_listing = result.stdout.replace("\\", "/").lower()
    offenders = [
        line.strip()
        for line in result.stdout.splitlines()
        if "__pycache__" in line.lower()
        or ".pyc" in line.lower()
        or ".pyo" in line.lower()
    ]
    if offenders:
        sample = "\n  ".join(offenders[:20])
        raise RuntimeError(f"Packaged sidecar contains bytecode data:\n  {sample}")

    missing_sources = [
        f"{package_name}/__init__.py"
        for package_name in PACKAGE_NAMES
        if f"{package_name}/__init__.py" not in archive_listing
    ]
    if missing_sources:
        missing = "\n  ".join(missing_sources)
        raise RuntimeError(
            "Packaged sidecar is missing auditable source payloads:\n"
            f"  {missing}"
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Directory that receives reliability-tools-sidecar.exe",
    )
    return parser.parse_args()

def main():
    args = _parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    _purge_source_bytecode()
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix="sidecar_source_data_",
        dir=BUILD_ROOT,
    ) as source_data_temp:
        source_data_stage = Path(source_data_temp)
        _prepare_source_data(source_data_stage)

        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--onefile",
            "--name", "reliability-tools-sidecar",
            "--distpath", str(output),
            "--workpath", str(BUILD_ROOT / "sidecar_build"),
            "--specpath", str(BUILD_ROOT),
            # Add clean source copies so the frozen self-test can AST-audit them.
            *[
                item
                for package_name in PACKAGE_NAMES
                for item in (
                    "--add-data",
                    f"{source_data_stage / package_name};{package_name}",
                )
            ],
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
            # Ensure supported spreadsheet/PDF engines are bundled.
            "--hidden-import", "openpyxl",
            "--hidden-import", "fitz",
            "--hidden-import", "pymupdf",
            "--hidden-import", "xlrd",
            # Clean build
            "--clean",
            "--noconfirm",
            # Entry point
            str(ENTRY),
        ]

        print(f"Building sidecar from: {ENTRY}")
        print(f"Output: {output / 'reliability-tools-sidecar.exe'}")
        result = subprocess.run(cmd, cwd=str(BACKEND))
        if result.returncode != 0:
            print("ERROR: PyInstaller build failed")
            sys.exit(1)

        # Verify the output and archive contents before executing it.
        exe = output / "reliability-tools-sidecar.exe"
        if not exe.exists():
            print(f"ERROR: Expected output not found: {exe}")
            sys.exit(1)
        _assert_archive_is_auditable(exe)

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
