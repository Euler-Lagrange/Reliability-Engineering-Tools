# Distribution Guide

How to build Reliability Tools Desktop and hand it off to teammates.

## Prerequisites (Build Machine Only)

Recipients do not need any of this — only the person running the build does.

- **Node.js 18 or newer** — for the frontend toolchain and the Tauri CLI wrapper.
- **Rust (stable)** — install via [`rustup`](https://rustup.rs/). Tauri currently
  builds against stable Rust; 1.94.1 is confirmed working.
- **Microsoft C++ Build Tools (MSVC)** — install the "Desktop development with
  C++" workload from Visual Studio Build Tools.
- **Python 3.10 or newer** — a virtual environment at `.venv/` in the repo root
  with backend dependencies and PyInstaller installed.
- **WebView2 runtime** — preinstalled on Windows 10 and 11; no action needed
  unless you are on a stripped-down LTSC image.

## Building a Release

From the repository root:

```bat
scripts\release.bat
```

The build takes about two minutes on a typical dev machine. A timestamped log
is written to `logs/release_YYYYMMDD_HHMMSS.log`. On success, the script prints
`STATUS: SUCCESS` and the path to the portable exe.

## What the Pipeline Does

`release.bat` runs eight steps. Any failure aborts the build and prints
`STATUS: FAILED` along with the log path.

1. **Toolchain check** — verifies `node`, `npm`, and the backend Python
   interpreter at `.venv\Scripts\python.exe`.
2. **Backend tests** — `pytest backend\tests -q` against the Python sidecar.
3. **Frontend tests** — `npm test` against the React frontend.
4. **Sidecar build** — `python scripts\build_sidecar.py` runs PyInstaller and
   produces `reliability-tools-sidecar.exe`.
5. **Tauri build** — `npm run tauri:build:portable` produces the portable
   desktop exe under `src-tauri\target\...\release\`.
6. **Locate exe** — finds the packaged exe and copies it to
   `local_build\ReliabilityToolsDesktop.exe`.
7. **Shell self-test** — launches the portable exe with `--self-test` to
   verify the Tauri binary starts.
8. **Backend self-test** — launches with `--self-test-backend` to verify the
   shell can spawn the sidecar and exchange a `health_check`.

## Output Artifacts

Both files land in `local_build/`:

| File | Size | Role |
|------|------|------|
| `ReliabilityToolsDesktop.exe` | ~9 MB | Tauri shell, React UI, Rust bridge |
| `reliability-tools-sidecar.exe` | ~53 MB | PyInstaller-bundled Python backend |

Both files must ship together. The shell spawns the sidecar by relative path,
so they must live in the same directory on the recipient's machine.

## Distributing to Team Members

1. Zip the entire `local_build/` folder, or copy both files to a shared
   location (network share, USB, etc.).
2. Recipients extract or copy both files into one folder.
3. Double-click `ReliabilityToolsDesktop.exe`.

Recipients do not need Python, Node, Rust, or any runtime installer. WebView2
is already present on Windows 10 and 11.

## Troubleshooting

**The sidecar exe fails to spawn.**
Both files must be in the same directory. Verify `reliability-tools-sidecar.exe`
sits next to `ReliabilityToolsDesktop.exe`.

**Windows SmartScreen blocks the exe.**
The binary is not code-signed. Click `More info` then `Run anyway`. This
happens once per user per machine.

**Antivirus flags the sidecar exe.**
PyInstaller-bundled executables sometimes trigger heuristic detection. Add the
sidecar exe to the antivirus allow-list. The build pipeline runs backend tests
before packaging, so the binary is not tampered with.

**First launch is slow.**
On cold start, the PyInstaller sidecar extracts its embedded Python runtime to
a temp directory. Expect a one-time delay of roughly one second before the
backend is ready. Subsequent launches are faster.

**Connection drops mid-run.**
The Rust bridge auto-reconnects on heartbeat timeout with exponential backoff
(2s, 4s, 8s, 15s, 30s). Check the log panel in the Settings tab for details.

## Known Limitations

- **Windows x64 only.** No macOS, Linux, or ARM64 builds at this time.
- **Not code-signed.** SmartScreen warns on first launch; teams can whitelist
  the binary or accept the warning.
- **WebView2 required.** Preinstalled on Windows 10 and 11. Stripped-down
  images may need the Evergreen WebView2 runtime installed manually.
- **No auto-update.** Recipients must manually replace both exes when a new
  release is handed off.

## Future Improvements

- Code-signing certificate to remove the SmartScreen warning.
- Auto-update mechanism so recipients no longer have to re-copy files.
- MSIX packaging for Microsoft Store or corporate intranet distribution.
