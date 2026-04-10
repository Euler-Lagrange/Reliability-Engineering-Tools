---
name: design-architect
description: Design and architecture guidance for this Tauri desktop repository. Use when Codex needs to design a new feature, plan a workflow addition, assess cross-layer impact, architect UI plus backend changes, or define interface changes across React, Rust, Python, contracts, and tests.
---

This skill is for OpenAI GPT Codex in this repository. Claude Code should ignore this skill.

# Design Architect

- Start by classifying the request: frontend-only, Rust bridge, Python sidecar, contracts, tests, or a cross-layer change.
- Read `docs/ARCHITECTURE.md` before planning anything that touches commands, run events, workflow routing, or sidecar lifecycle.
- Read `docs/DESIGN_SYSTEM.md` before proposing UI changes. Preserve the token-first styling model and existing shell/component patterns.
- Read `docs/DEVELOPMENT.md` when the request adds a tool, workflow, command, or build-facing behavior.

## Planning Workflow

- Identify the affected layer boundaries before suggesting an implementation path.
- Name the public surfaces that change:
  workflow ids, file roles, request payloads, response schemas, run events, settings, or tool registry entries.
- Call out whether the request requires coordinated edits across frontend, Rust, Python, contracts, mocks, and tests.
- Prefer designs that fit the existing tool-runtime pattern, run lifecycle model, and sidecar command routing.
- Treat schema drift as a design bug. If one layer changes shape, plan the corresponding updates everywhere.

## Frontend Guidance

- Preserve browser-preview usefulness. When a user flow changes, plan matching updates in `frontend/src/mocks/scenarios.ts`.
- Reuse the established shell and shared components before inventing new ones.
- Put new visual tokens in `frontend/src/theme/styles.css` before using them in component styles.
- Keep feature design aligned with the current AppShell, tool registry, and shared backend lifecycle patterns documented in `docs/ARCHITECTURE.md`.

## Backend And Bridge Guidance

- Keep the backend offline and compatible with the security-audit expectations.
- Preserve the NDJSON-over-stdio contract and the Rust bridge ownership of the Python session.
- Do not route the frontend directly to Python or bypass the Rust bridge.
- When changing long-running execution behavior, account for ack, streamed events, cancellation, and terminal result handling together.

## Output Expectations

- Produce plans that are decision-complete and explicit about layer ownership.
- State the interface changes, major risks, migration points, and required tests.
- End with the smallest coherent implementation slice that preserves repo patterns.
