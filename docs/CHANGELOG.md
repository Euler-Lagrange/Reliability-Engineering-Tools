# Tauri Build Changelog

## 0.1.0

- Adopted the existing Dark Star prototype into `tauri_build/`
- Normalized the desktop-track folder structure
- Added suite shell navigation with tool icons and placeholder tabs
- Added theme state with light, dark, and signal-slate variants
- Replaced the hand-rolled select with a Radix-based control
- Added initial sidecar NDJSON contract scaffolding
- Added Python sidecar scaffold with `health_check` and `list_sheets`
- Added backend protocol tests and desktop-track docs
- Added a real Rust desktop bridge for `health_check` and `list_sheets`
- Added workbook browsing and sheet hydration in the FMEA input cards
- Added packaged backend self-test coverage to the release flow
- Added Python sidecar support for `inspect_input` and `analyze_template`
- Added Rust bridge commands for inspection and template analysis
- Added live workbook-analysis context to the FMEA mapping and preview UI
- Replaced per-command Python spawn with a managed Rust-held sidecar session
- Added normal-shutdown sidecar teardown in the Tauri shell
- Copied the frozen FMEA generator logic into the Tauri backend tree for the first execution slice
- Added `validate_run` to the Python sidecar and desktop bridge
- Added a first real `execute_run` path for standard and BOM-only new-workbook generation
- Added execution-log display and real result rendering in the Dark Star run panel
- Added backend tests covering validation and real workbook generation through the sidecar
