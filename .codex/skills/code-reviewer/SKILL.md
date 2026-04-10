---
name: code-reviewer
description: Code review guidance for this repository. Use when Codex is asked to review changes, inspect a diff, look for regressions, perform pre-merge review, assess maintainability, or validate cross-layer completeness across the React frontend, Rust bridge, Python sidecar, and tests.
---

This skill is for OpenAI GPT Codex in this repository. Claude Code should ignore this skill.

# Code Reviewer

- Lead with findings, not summary.
- Prioritize correctness, regression risk, missing tests, contract mismatches, unsafe error handling, and violations of offline/security assumptions.
- Use repo docs as the review baseline instead of generic style preferences:
  `docs/ARCHITECTURE.md`, `docs/DESIGN_SYSTEM.md`, `docs/DEVELOPMENT.md`, and `docs/TESTING.md`.

## Review Priorities

- Check whether the change is complete across all impacted layers.
- If workflow ids, payloads, response shapes, or run events changed, verify the frontend, Rust bridge, Python sidecar, contracts, mocks, and tests move together.
- Flag changes that appear to break browser-preview mock mode.
- Flag changes that appear to break sidecar routing, session lifecycle, heartbeat behavior, or cancellation flow.
- Flag changes that weaken the backend's offline/security posture.
- Flag UI work that ignores the token-based design system or introduces inconsistent shell patterns.

## Review Method

- Inspect the highest-risk behavior first, not the easiest file.
- Compare the implementation against documented repo patterns before suggesting alternatives.
- Treat missing validation as a review issue when the touched area normally requires frontend tests, backend subprocess tests, or type/schema checks.
- Prefer concrete, reproducible findings with clear impact over speculative cleanup advice.

## Output Expectations

- Report findings in severity order with file and line references when available.
- Keep summaries brief and secondary to findings.
- If no findings are present, say so explicitly and note any residual testing gaps or unchecked risk.
