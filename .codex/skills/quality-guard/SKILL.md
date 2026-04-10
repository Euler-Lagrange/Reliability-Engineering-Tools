---
name: quality-guard
description: Quality-control guidance for this repository. Use when Codex needs to check whether work is truly done, harden a change, assess readiness, enforce best practices, review acceptance criteria, or verify testing and contract completeness before release or handoff.
---

This skill is for OpenAI GPT Codex in this repository. Claude Code should ignore this skill.

# Quality Guard

- Perform completion checks before declaring work done.
- Use repo standards, not generic polish, as the quality bar.
- Read `docs/TESTING.md`, `docs/ARCHITECTURE.md`, and `docs/DESIGN_SYSTEM.md` when the change spans behavior, contracts, or UI.

## Quality Checklist

- Verify the changed area has the right validation coverage:
  frontend tests, backend subprocess tests, in-process backend tests, type checks, or contract checks.
- Verify docs, types, contracts, mocks, and build implications for the touched behavior.
- Enforce repo-specific best practices:
  offline backend, no accidental network dependencies, token-based styling, browser-preview mock coverage, and coherent run lifecycle behavior.
- Prefer small, coherent changes over broad rewrites that increase risk without clear value.
- Require an explicit residual-risk note when validation is incomplete.

## Completion Standard

- A change is not "done" if the implementation compiles but leaves contract drift, missing mock coverage, missing tests, or repo-invariant violations.
- A change is not "done" if it silently weakens release, build, or runtime expectations documented in repo docs.
- When quality gaps exist, surface the highest-value fixes first.

## Output Expectations

- Return a concise readiness assessment backed by concrete checks.
- Separate confirmed quality gaps from optional follow-up improvements.
- Make the final recommendation easy to act on: ready, ready with noted risk, or not ready.
