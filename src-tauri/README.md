# src-tauri

Rust desktop bridge between the React frontend and the Python sidecar. The
Tauri shell owns the native window, manages the sidecar child process, and
relays NDJSON messages between the two sides.

## Purpose

- Spawn and supervise `reliability-tools-sidecar.exe` (Python, PyInstaller-bundled).
- Forward frontend commands to the sidecar over stdin.
- Stream sidecar events (`result`, `status`, `progress`, `log`, `ack`,
  `cancelled`, `backend_error`) back to the frontend over Tauri event channels.
- Enforce the 15-second heartbeat timeout and trigger reconnect on disconnect.

## Key File

All bridge logic lives in `src/lib.rs`. Highlights:

- `ManagedSidecar` — wraps the child process and its stdin/stdout handles.
- Stdout reader thread — parses NDJSON line-by-line, dispatches by `kind`.
- Heartbeat supervisor — checks the last-seen heartbeat every 5s, kills the
  session if more than 15s elapse without one.
- Stdin write lock — every command is serialized through a single `Mutex` so
  two concurrent Tauri commands cannot interleave bytes on the pipe.

`src/main.rs` is a thin entrypoint that defers to `lib.rs`.

## Build

Always build from the repository root, not from `src-tauri/`:

```powershell
npm run tauri:build:portable
```

This produces `src-tauri/target/x86_64-pc-windows-msvc/release/reliability-tools-desktop.exe`.
The full release pipeline (`scripts/release.bat`) copies it to
`local_build/ReliabilityToolsDesktop.exe` alongside the sidecar exe.

## Toolchain

- Rust stable via `rustup` (confirmed working on 1.94.1)
- MSVC build tools (Visual Studio Build Tools, C++ workload)
- WebView2 runtime (preinstalled on Windows 10/11)

## Runtime Shape

- One managed sidecar session per app launch.
- One active run at a time — a second `execute_run` while one is in flight is
  rejected by the sidecar with an `error` envelope.
- Reconnect on disconnect uses exponential backoff: 2s, 4s, 8s, 15s, 30s.

## See Also

- `../docs/ARCHITECTURE.md` — full three-layer picture (React / Rust / Python)
- `../contracts/sidecar-protocol.md` — NDJSON protocol spec
- `../backend/python/sidecar_main.py` — sidecar source of truth
