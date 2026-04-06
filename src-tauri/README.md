# Tauri Phase 2 Scaffold

This directory now contains the desktop-wrapper bootstrap for the prototype.

## Current Purpose

- Keep the frontend aligned to a real desktop shell target
- Provide the minimum Rust/Tauri bootstrap for running the current UI in a native window
- Document what is required before `.exe` packaging succeeds on another machine

## Files

- `tauri.conf.json`: planned desktop window and frontend build wiring
- `Cargo.toml`: Rust crate metadata and Tauri dependencies
- `build.rs`: Tauri build integration
- `src/`: desktop entrypoint and builder
- `capabilities/default.json`: default app capability for the main window

## Prerequisites Before Packaging

- Rust toolchain with `cargo` and `rustc`
- Microsoft C++ build tools / MSVC-compatible environment
- WebView2-compatible Windows runtime
- Tauri CLI installation choice for the project

## Expected Future Commands

```powershell
npm run tauri:readiness
npm run tauri:dev
npm run tauri:build
```

## Planned Command Behavior

- `tauri:readiness` checks local prerequisites and reports gaps
- `tauri:dev` will eventually run the desktop wrapper in development mode
- `tauri:build` will eventually build the Windows executable

Current phase: first desktop shell prototype. A real Python sidecar and production packaging hardening are still future work.
