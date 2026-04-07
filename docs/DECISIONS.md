# Architecture Decision Records

Lightweight ADR log capturing the load-bearing decisions made during the
migration from Flet to Tauri. Each entry is immutable history; supersede
rather than edit.

## ADR-001: Tauri over Electron or continued Flet

**Context.** The Flet app painted slowly on Windows and exhibited opaque UI
bugs (control mount timing, overlay bloat, single-parent crashes) that were
expensive to diagnose. Electron was considered but would add a 100 MB+
bundle with Chromium baggage and memory overhead inappropriate for a
desktop reliability tool. Tauri pairs a Rust host with the system WebView2
and a React frontend.

**Decision.** Adopt Tauri as the desktop shell. Rust owns process lifecycle
and the sidecar bridge; React owns the UI; Python remains the compute core.

**Consequences.** Binary size dropped to roughly 10 MB (excluding the
bundled sidecar). Native performance improved. The cost: a Rust learning
curve for contributors, and WebView2 version inconsistency across Windows
builds that requires explicit testing on older Windows 10 images.

## ADR-002: NDJSON over stdio vs HTTP

**Context.** The Tauri host needed a protocol to drive the Python sidecar.
HTTP would have required local port management, firewall prompts on
corporate Windows images, authentication to prevent drive-by access, and
graceful port-collision recovery.

**Decision.** Use newline-delimited JSON (NDJSON) over the sidecar's stdin
and stdout. One JSON object per line, request/response correlated by
`id`, streaming events emitted as they happen.

**Consequences.** No network surface, no firewall dialogs, language-agnostic,
ordered delivery by construction. The trade-off: stderr had to be routed to
`DEVNULL` to prevent Windows pipe deadlocks, and a dedicated reader thread
on the Rust side is required to avoid blocking the main Tokio runtime.

## ADR-003: PyInstaller over embedded Python distribution

**Context.** End users are air-gapped reliability engineers who cannot
install Python, pip, or fetch wheels. Options surveyed: the official
`python-3.12-embed` zip, PyInstaller onefile, and Nuitka compilation.

**Decision.** Bundle the sidecar as a PyInstaller onefile executable,
shipped as a Tauri sidecar binary.

**Consequences.** Zero-install user experience: the app ships one `.exe`
and the sidecar extracts on first launch. Sidecar size is approximately
53 MB; cold-start extraction takes roughly one second. The trade-off:
PyInstaller hidden-import hints are required for dynamic imports, and
upgrading Python versions requires rebuilding the sidecar.

## ADR-004: Single active run vs multi-run queue

**Context.** Reliability engineers typically run one large FMEA at a time
and wait for it. A multi-run queue would have added state complexity
(partial cancel semantics, priority, deadlock on shared workbooks) for a
workflow that is inherently sequential in practice.

**Decision.** One active long-running backend task at a time. The sidecar
rejects concurrent `execute_run` requests while a run is in flight.

**Consequences.** The run lifecycle is simple: idle, acked, running,
completed or cancelled. Cancel is unambiguous. Logs are scoped to the
active run. The trade-off: users cannot start a second FMEA while the
first is running, which is acceptable given typical run durations.

## ADR-005: Copied/vendored common modules vs shared package

**Context.** The Flet app's `common/` modules are battle-tested and mature,
but the Flet app is under frozen development. A shared package would have
coupled release cycles and forced the Tauri app to inherit Flet-era
constraints on every change.

**Decision.** Copy all 12 `common/` modules and the per-tool logic files
into `backend/python/` as a self-contained tree. No `sys.path` hacks, no
cross-repo imports.

**Consequences.** The Tauri backend is fully self-contained and can be
packaged without reaching outside its own directory. Divergence between
the two copies is acceptable because the Flet app is archived. The
trade-off: bug fixes must be applied twice if both copies are still in
use; in practice, only the Tauri copy is maintained.

## ADR-006: Heartbeat supervision vs raw process monitoring

**Context.** Raw `process.is_alive()` checks miss a specific failure mode:
the sidecar process is alive but its I/O loop is deadlocked, so commands
silently stall. Users see a frozen UI with no error.

**Decision.** The Python sidecar emits a heartbeat event every 5 seconds.
The Rust bridge times out at 15 seconds without a heartbeat and declares
the sidecar dead. The frontend auto-reconnects with exponential backoff
(2s, 4s, 8s, 15s, 30s).

**Consequences.** Deadlocked sidecars are detected and recovered within
seconds. The trade-off: the heartbeat timer adds background log noise
(filtered out of user-visible logs), and a stress-loaded sidecar can
occasionally miss a heartbeat and trigger a false-positive reconnect.

## ADR-007: workflowId-based routing vs per-tool commands

**Context.** Five tools, each with multiple workflows (standard, bom-only,
fill-gaps, template-preserve, piece-part-generate, etc.) would have meant
15+ Tauri commands, each duplicating validation, execution scaffolding,
event correlation, and cancel wiring.

**Decision.** One `execute_run` command. Callers pass a `workflowId` field.
The sidecar dispatches to the correct handler. Rust bridge and frontend
run-session state are shared across all workflows.

**Consequences.** Adding a new workflow is a sidecar-only change with no
Rust or frontend churn. Run events, cancel, and lifecycle are uniform
across tools. The trade-off: workflow-specific payload validation happens
in Python rather than at the TypeScript/Rust boundary, so bad payloads
surface as runtime errors rather than compile-time errors.

## ADR-008: Self-hosted fonts vs Google Fonts CDN

**Context.** The app is air-gapped and offline-capable. A Google Fonts CDN
link would fail silently on customer machines and fall back to system
fonts, producing inconsistent rendering across Windows versions.

**Decision.** Self-host the Inter variable font as `Inter-Variable.woff2`
and the JetBrains Mono variable font as `JetBrainsMono-Variable.ttf` under
`frontend/public/fonts/`. Each font ships in a single format because both
are loaded directly via `@font-face` in `frontend/src/theme/styles.css` —
there is no fallback chain, so the smaller file size of the woff2 build is
preferred where the upstream project distributes one (Inter), and the
upstream ttf is used where it does not (JetBrains Mono).

**Consequences.** Consistent typography on every machine regardless of
network state. Bundle size increased by roughly 655 KB, which is
negligible next to the sidecar. The trade-off: font updates require a
manual refresh of the vendored files.
