# Reliability Tools Desktop

This folder is the separate `tauri_build` migration track for the desktop shell that will eventually replace the current Flet UI. It adopts the original Dark Star prototype, keeps the existing Python/Flet product untouched, and now includes the first suite-shell foundation plus an initial Python sidecar scaffold.

## Scope

- Suite shell foundation in `Vite + React + TypeScript`
- Desktop packaging through `Tauri`
- Separate Python sidecar scaffold under `backend/python/`
- Flet app remains untouched during migration

## Current State

- Dark Star FMEA is the only active migrated tool tab
- Other tools are shell placeholders with icons and theme-safe navigation states
- Theme system includes `system`, `Light Precision`, and `Dark Precision`
- Frontend shell tests and backend sidecar tests are wired into the new build flow
- The desktop shell now has a real Rust-to-Python bridge for `health_check` and `list_sheets`
- The bridge now also supports `inspect_input` and `analyze_template`
- The first real Phase 4 execution slice is now wired for `validate_run` and `execute_run`
- Input cards in the FMEA workspace can browse a workbook and hydrate sheet names when run in the Tauri shell
- The mapping review can now use inspected workbook columns, and the preview panel shows live analysis context
- The Rust bridge now keeps a managed Python sidecar session alive across commands instead of spawning Python per request
- The sidecar contract is documented in `contracts/sidecar-protocol.md`
- `health_check`, `list_sheets`, `inspect_input`, `analyze_template`, `validate_run`, and a first `execute_run` path are implemented in the Python scaffold

## Run

```powershell
cd tauri_build
npm run dev
```

## Test

```powershell
cd tauri_build
npm test
C:\Reliability_Eng_Tools_Dev\.venv\Scripts\python.exe -m pytest backend\tests -q
```

## Build

```powershell
cd tauri_build
npm run build
```

## Desktop Build

This migration shell builds as a Windows desktop app through Tauri.

```powershell
cd tauri_build
npm run tauri:readiness
```

Desktop commands:

```powershell
npm run tauri:dev
npm run tauri:build
npm run tauri:build:portable
```

`tauri:dev` launches the desktop shell against the React frontend.

`tauri:build` builds the desktop executable and bundles an installer.

`tauri:build:portable` builds the desktop executable without the installer step. This is the primary migration verification path and the command used by the release script.

## Release

Use the release script when you want a one-click portable artifact similar to the current Python app flow.

```powershell
cd tauri_build
npm run release
```

That release script:

- runs backend `pytest` in `backend/tests`
- runs `npm test`
- runs `npm run tauri:build:portable`
- copies the portable exe into `local_build\ReliabilityToolsDesktop.exe`
- runs a packaged `--self-test` against the copied exe
- runs a packaged `--self-test-backend` to verify the Rust bridge can still reach the Python sidecar

Primary release artifact:

- `local_build\ReliabilityToolsDesktop.exe`

Current build output:

- `src-tauri\target\x86_64-pc-windows-msvc\release\reliability-tools-desktop.exe`
- `src-tauri\target\x86_64-pc-windows-msvc\release\bundle\nsis\Reliability Tools Desktop_0.1.0_x64-setup.exe`

ARM64 Windows note:

- This machine has an ARM64 host OS but only an x64 MSVC linker installed.
- The Tauri runner automatically falls back to the `stable-x86_64-pc-windows-msvc` Rust toolchain and builds an `x64` desktop app, which Windows 11 ARM can run.

## Notes

- The shell is tab-based, not route-based.
- UI state still relies on typed mock fixtures for the FMEA workspace while the sidecar foundation is being wired.
- The first executable Dark Star path is intentionally narrow:
  - standard piece-part generation
  - BOM-only generation
  - new workbook output only
- `src-tauri/` contains the desktop bootstrap and packaging config.
- `backend/python/sidecar_main.py` is an initial NDJSON sidecar scaffold, not the final production backend.
- `backend/python/fmea/fmea_generator_logic.py` is a copied frozen parity module used by the first real execution slice.
- The desktop bridge now reuses a managed Python session across commands and tears it down on normal shell shutdown.
- Template-preserved writes, fill-gaps execution, heartbeat supervision, crash restart policy, cancellation, and run-stream execution are still later phases.
- No current Flet code was modified to create this migration track.
