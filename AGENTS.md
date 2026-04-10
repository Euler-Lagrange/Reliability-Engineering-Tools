# AGENTS.md - OpenAI GPT Codex Guidance

This file is for OpenAI GPT Codex in this repository. Claude Code should ignore this file.

## Repo Identity

- Desktop application: Tauri 2.x + React 19 + TypeScript + Rust + Python sidecar
- Frontend: `frontend/`
- Rust bridge: `src-tauri/`
- Python backend: `backend/python/`
- Protocol: NDJSON over stdio between Rust and Python
- Backend constraint: offline / air-gapped; do not introduce network behavior into `backend/python/`

## Read These First

Consult these docs before making or reviewing non-trivial changes:

- `docs/ARCHITECTURE.md` for layer boundaries, protocol lifecycle, and routing patterns
- `docs/DESIGN_SYSTEM.md` for design tokens, component styling rules, and shell conventions
- `docs/DEVELOPMENT.md` for setup, build, and feature wiring patterns
- `docs/TESTING.md` for suite structure, subprocess patterns, and test expectations

## Working Mode For Feature Design

- Start by identifying which layers change: frontend, Rust bridge, Python sidecar, contracts, tests.
- Classify the request before proposing implementation: frontend-only, protocol-only, backend-only, or cross-layer.
- When workflows, commands, or streamed run behavior change, reason across all affected layers before editing any one file.
- Treat protocol/schema drift as a first-class risk. Keep Rust responses, Python payloads, and frontend Zod schemas aligned.
- Preserve browser-preview usability. If a frontend flow changes, update or add mock scenarios so `npm run dev` remains useful without Tauri.
- Preserve the existing design system. Add or adjust tokens in `frontend/src/theme/styles.css` before hardcoding new visual values.
- Prefer small, coherent changes that match repo patterns over novel abstractions.

## Non-Negotiable Invariants

- Keep the Python backend offline and compatible with the existing security audit expectations.
- Preserve the single-active-run rule for `execute_run`.
- Preserve stdin write atomicity in the Rust bridge: payload, newline, and flush under one lock scope.
- Preserve the heartbeat contract: Python heartbeat every 5s by default, Rust timeout at 15s unless intentionally changed everywhere.
- Preserve Python import behavior rooted at `backend/python/`; do not add production `sys.path` hacks.
- Keep the frontend talking to Python only through Tauri and the Rust bridge.

## Testing Expectations

- Validate every touched layer, not just the file you edited.
- Frontend changes should normally include `npm run typecheck` and relevant Vitest coverage.
- Backend or protocol changes should normally include targeted `pytest backend/tests` coverage, especially subprocess tests in `backend/tests/test_sidecar_main.py`.
- Contract changes must be checked across Python payload shape, Rust enrichment, and frontend schema validation.
- If validation is incomplete, say exactly what was not run and what risk remains.

## Repo-Local Skill Routing

Use these repo-local Codex skills proactively when they fit the task:

- `.codex/skills/design-architect/` for feature design, workflow additions, interface planning, and cross-layer architecture
- `.codex/skills/code-reviewer/` for diff review, regression hunting, and pre-merge review
- `.codex/skills/debug-investigator/` for runtime failures, flaky behavior, failed tests, and protocol tracing
- `.codex/skills/quality-guard/` for completion checks, hardening, readiness review, and repo-specific best-practice enforcement

## Collaboration Notes

- This repo already has `CLAUDE.md`. Treat this `AGENTS.md` as Codex-specific guidance that complements it rather than mirroring it.
- If instructions appear to conflict, prefer repo facts from code and docs, then follow the Codex-specific guidance in this file for Codex behavior.
