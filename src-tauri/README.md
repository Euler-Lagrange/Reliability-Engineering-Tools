# src-tauri

Rust desktop bridge between the React frontend and the Python sidecar. The
Tauri shell owns the native window, manages the sidecar child process, and
relays NDJSON messages between the two sides.

## Purpose

- Spawn and supervise `reliability-tools-sidecar.exe` (Python, PyInstaller-bundled).
- Forward frontend commands to the sidecar over stdin.
- Stream sidecar events (`result`, `status`, `progress`, `log`, `ack`,
  `cancelled`, `backend_error`) back to the frontend over Tauri event channels.
- Enforce the 15-second heartbeat timeout and emit a `backend://session`
  disconnect event; the frontend (`useBackendBootstrap`) owns reconnection
  with exponential backoff — the bridge itself never reconnects.

## Key File

All bridge logic lives in `src/lib.rs`. Highlights:

- `ManagedSidecar` — wraps the child process and its stdin/stdout handles.
  On Windows it also owns the Job Object (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`,
  spawned `CREATE_SUSPENDED` → assign → resume) so a dying bridge can never
  orphan a live sidecar.
- Stdout reader thread — parses NDJSON line-by-line, dispatches by `kind`.
  Non-JSON lines are logged and skipped; only EOF or a read error tears the
  session down.
- Heartbeat supervisor — checks the last-seen heartbeat every 5s, kills the
  session if more than 15s elapse without one. Reader and supervisor are
  pinned to a session-generation counter so a stale thread can never act on
  a newer session.
- Stdin write lock — every command is serialized through a single `Mutex` so
  two concurrent Tauri commands cannot interleave bytes on the pipe.
- Bounded waits — sidecar-ready and per-command timeouts fail pending
  requests loudly instead of hanging the UI.
- Fatal-error detail merge — the most recent error-level sidecar log line is
  folded into the user-visible disconnect notification.
- `reveal_in_file_manager` command, `--self-test` / `--self-test-backend`
  entry points, and a crash-dump panic hook (`crash_rust_*.log`).

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
