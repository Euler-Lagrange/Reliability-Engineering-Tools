# Reliability Tools Desktop

A Windows desktop application for hardware reliability engineering analysis. Built with Tauri (Rust + React) with a Python sidecar for data processing.

## Tools

| Tool | Description |
|------|-------------|
| **FMEA Generator** | Generate piece-part FMEA workbooks from grouping, BOM, and failure mode sources. Supports four workflows: standard (`piece_part_generate`), BOM-only (`bom_only`), functional-to-piece-part (`functional_to_piecepart`), and fill-gaps (`fill_gaps`), with optional template preservation. |
| **BOM Compare** | Compare grouping files against BOMs (coverage check) or two arbitrary BOMs (delta analysis). Detects missing/extra RefDes and per-column value differences (Custom Compare's column-pair picker), with FMEA-aware scope warnings. |
| **Failure Rate** | Link prediction failure rates to FMEA failure modes. Calculates mode failure rates with configurable unit conversion and FMR validation. |
| **RefDes Extractor** | Extract reference designators and pins from annotated schematic PDFs. Adaptive 4-phase geometry analysis with NextGen and Legacy backend routing. With a BOM loaded, cross-checks coverage both ways — emitting Coverage Summary, BOM Not Grouped, and Extracted Not In BOM sheets. |
| **Settings** | Theme selection, backend diagnostics, and application info. |

## Architecture

```
frontend/           React 19 + TypeScript UI (Vite)
src-tauri/          Rust desktop bridge (Tauri 2.x)
backend/python/     Python sidecar (NDJSON over stdio)
backend/tests/      Integration tests (subprocess-based)
contracts/          Protocol documentation
```

The frontend communicates with the Rust bridge via Tauri IPC. The Rust bridge manages a Python sidecar process, routing commands over NDJSON stdio. The Python backend contains all data processing logic — no network access, fully offline.

## Quick Start

### Prerequisites

- Node.js 18+
- Rust toolchain (via rustup) with MSVC build tools
- Python 3.10+ with venv

### Setup

```powershell
npm install
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
```

### Development

```powershell
npm run dev                    # Browser preview (mock backend)
npm run tauri:dev              # Desktop with hot reload
```

### Testing

```powershell
npm run typecheck              # TypeScript type checking
npm run typecheck:tests        # TypeScript type checking for Vitest files
npm test                       # Frontend tests (371 tests across 48 test suites)
.venv\Scripts\python.exe -m pytest backend\tests -v   # Backend tests (528 tests across sidecar, audit, cancel bridge, output-directory helpers, FMEA phase D, FMEA template analyzer, failure-rate logic, RefDes extraction-engine, BOM-compare logic, extraction compare, read-layer, RefDes BOM-coverage, BOM-loader, OneDrive detection, file-size guard, crash-dump, NextGen engine, RefDes runtime, validation notes)
```

### Build

```powershell
npm run tauri:build:portable   # Portable .exe (no installer)
npm run release                # Full 12-step release pipeline (typechecks + audit + tests + build + self-tests)
```

Release artifact: `local_build\ReliabilityToolsDesktop.exe`

### Version management

```powershell
npm run version:check          # Verify manifests and lockfile package versions agree
npm run version:bump -- 0.4.3  # Update all three manifests in lockstep
```

## Sidecar Protocol

NDJSON over stdio between Rust and Python. Commands: `health_check`, `list_sheets`, `inspect_input`, `analyze_template`, `validate_run`, `execute_run`, `cancel_run`, `read_flet_config`.

- `execute_run` streams progress/log events with a terminal result
- `health_check` now reports the sidecar log directory so Settings › Logs can reveal it
- `validate_run` / `execute_run` accept an optional `outputDirectory` honored by every tool
- `validate_run` may return an optional `output_preview` sample surfaced in the shell's Review drawer (⌘R / Ctrl+R)
- Heartbeat supervision: Python emits every 5s, Rust times out at 15s
- Automatic frontend reconnection with exponential backoff on disconnect
- Full spec in `contracts/sidecar-protocol.md`

## Key Technical Details

- **Offline/air-gapped** — no network access in the Python backend
- **Single active run** — one `execute_run` at a time per sidecar session
- **Atomic stdin writes** — payload + newline + flush under a single mutex lock
- **PyMuPDF** required for RefDes Extractor (PDF processing)
- **CancellationError** propagates through `InterruptedError → OSError → Exception` chain
- **Crash dumps** — unhandled Python exceptions (main + worker threads) and Rust panics write timestamped files to `~/.reliability_tools/logs/crashes/`; each dump carries a review-before-sharing banner and truncates embedded values (may contain source data)
- **Content Security Policy** — production builds ship a conservative CSP (`default-src 'self' ipc:`, `script-src 'self'`, `object-src 'none'`, etc.); dev mode is unaffected

## Project Status

All four analysis tools have backend runtime adapters, React frontends, and integration tests. Settings is an active platform tab for theme selection, backend diagnostics, logs, and app info. See `docs/MIGRATION_HISTORY.md` for the completed phase log and `docs/CHANGELOG.md` for release notes.
