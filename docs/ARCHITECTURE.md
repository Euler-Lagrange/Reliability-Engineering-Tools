# Tauri Build Architecture

`tauri_build/` is the separate desktop migration track for the Reliability Tools suite.

## Top-Level Layout

- `frontend/` React shell, tool UI, shell state, themes, tests
- `src-tauri/` Tauri host, packaging, desktop entrypoint
- `backend/python/` copied Python logic and sidecar entrypoints
- `backend/tests/` backend parity and protocol tests
- `contracts/` protocol docs and examples
- `scripts/` build, release, readiness, and future sidecar packaging helpers

## Shell Model

- Suite shell uses app-state tab navigation, not browser routing.
- Dark Star FMEA is the only active migrated tool in the first slice.
- Other tools remain placeholders inside the same shell.
- Theme, notifications, active tool, and backend status are shell-level concerns.

## Backend Model

- One Python sidecar process per app in v1.
- NDJSON over stdio with request correlation.
- No live workbook or pandas objects cross IPC.
- Large artifacts remain on disk and are referenced by metadata.
