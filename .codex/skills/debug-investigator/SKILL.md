---
name: debug-investigator
description: Debugging guidance for this repository. Use when Codex needs to investigate runtime failures, flaky behavior, failed tests, protocol issues, startup problems, session disconnects, cancellation bugs, or unclear behavior across the React frontend, Rust bridge, and Python sidecar.
---

This skill is for OpenAI GPT Codex in this repository. Claude Code should ignore this skill.

# Debug Investigator

- Reproduce first when feasible.
- Isolate the failing layer before proposing fixes: frontend state, Rust bridge/session management, Python sidecar logic, protocol shape, or test harness.
- Use `docs/ARCHITECTURE.md` and `docs/TESTING.md` to trace how a request should move through the system.

## Investigation Workflow

- Capture the observed symptom, expected behavior, and narrowest reproduction.
- Determine whether the failure is:
  validation error, backend runtime error, bridge/session error, protocol mismatch, UI-state bug, or test-only issue.
- Check request correlation and lifecycle behavior when long-running runs are involved:
  `request_id`, `run_id`, `ack`, streamed events, cancellation, and terminal result handling.
- Pay special attention to heartbeat timeout behavior, single-active-run enforcement, and subprocess test patterns.
- When the issue touches schemas, compare Python payload shape, Rust response enrichment, and frontend schema validation together.

## Repo-Specific Risks

- Preserve offline backend assumptions while debugging.
- Do not suggest bypassing the Rust bridge to "simplify" debugging.
- Be careful with cancellation and exception handling paths, especially where `CancellationError` inheritance matters.
- For frontend issues, confirm whether the bug occurs in browser-preview mode, desktop mode, or both.

## Output Expectations

- End with the most likely root cause, the evidence supporting it, and the smallest safe fix path.
- Distinguish facts from hypotheses.
- Note any missing reproduction or validation that still blocks confidence.
