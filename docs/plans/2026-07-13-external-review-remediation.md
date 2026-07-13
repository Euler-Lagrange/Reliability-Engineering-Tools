# External-Review Remediation Implementation Plan

> **For the implementing agent (Codex):** You found these defects in your three review
> rounds (2026-07-11..13). Every finding below was independently re-verified against the
> code by a second reviewer before entering this plan — do NOT re-litigate whether a
> finding is real, and do NOT re-decide the design choices marked **DECIDED**. Where this
> plan cites file:line, treat it as an anchor from the verification pass — line numbers
> drift; locate by symbol name. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all verified findings from the three-round architecture review — cancellation
truthfulness, Rust session integrity, frontend run-lifecycle unification, and
preserve-formatting merge data integrity — in four independently shippable waves.

**Architecture:** Each wave is a self-contained TDD batch: write failing tests first,
implement minimally, keep the full suite green, commit, then STOP for reviewer sign-off
before the next wave. No wave depends on a later wave.

**Tech stack:** Python 3.12 sidecar (pandas, openpyxl 3.1.5 — pinned, do not upgrade),
Rust/Tauri 2 bridge, React 19 + TypeScript + Zustand frontend, pytest + Vitest + cargo test.

---

## Ground rules (read before Wave 1)

**Repo:** `C:\Reliability_Eng_Tools`, branch `main`, baseline HEAD `aacc80a`,
suite baseline **393 backend / 306 frontend / 17 Rust = 716 green**.

**Commands:**
- Backend tests: `.venv\Scripts\python.exe -m pytest backend/tests -q`
- Sidecar self-test (runs security audit): `.venv\Scripts\python.exe backend/python/sidecar_main.py --self-test`
- Frontend: `npm run typecheck` and `npx vitest run --config frontend/vite.config.ts`
- Rust: `npm run cargo:test`

**Process, per wave:**
1. TDD: every behavior change gets a failing test FIRST; watch it fail for the right
   reason before implementing. Deletion-only or comment/doc-only changes are exempt.
2. One commit per task (or small logical group), message format
   `<Area>: <Action verb> <specific change>` (see `git-workflow` conventions; first line
   < 72 chars, present tense).
3. At the end of each wave: full backend + frontend + Rust suites green, then **STOP.
   Do not push. Do not start the next wave.** The reviewer (Claude) audits the wave's
   commits and approves the push.
4. Test-count bookkeeping travels with each wave: update the counts in `CLAUDE.md`
   (two places), `README.md`, and `docs/TESTING.md` (two tables) in the same commit
   that changes them.
5. Add a `docs/CHANGELOG.md` `[Unreleased]` entry per wave.
6. If you find an adjacent bug outside this plan's scope: do NOT fix it. Add it to a
   `## Discovered out-of-scope` section at the bottom of this file and move on.

**Load-bearing invariants you must not break** (each shipped a real bug once —
full list in `CLAUDE.md` "Critical Gotchas" and "Wiring Invariants"):
- `CancellationError → InterruptedError → OSError → Exception`: always re-raise
  cancellation BEFORE any broad `except`.
- Rust stdin writes: payload+newline+flush under ONE mutex guard.
- Python emissions: everything through `emit()` under `EMIT_LOCK`.
- Keep-alive tool shell: never remount tools or key tool panes.
- Shell-level run subscription is the only `backend://run-event` listener.
- A disabled control gets a hint; never render a control that is silently ignored.
- Atomic temp files keep their `.xlsx`/`.xlsm` suffix (`.part<suffix>` scheme).
- Sidecar tests are subprocess-based: `stderr=subprocess.DEVNULL`,
  `SIDECAR_HEARTBEAT_INTERVAL=9999`, `RELIABILITY_TOOLS_LOG_DIR` isolation.

**Explicitly deferred — do not implement:** event sequence numbers / message-ID dedup;
per-tool run history store; `PROC_THREAD_ATTRIBUTE_JOB_LIST` process creation; Excel COM
or raw-OOXML merge rewrite; moving synchronous sidecar commands to an executor thread;
Rust-side event buffering; Pillow dependency (images are warn-only by user decision);
a global cross-tool "execute pending" gate (the pre-registration double-dispatch race is
tolerated — the backend rejects the loser safely); a semantic post-write verifier
(fingerprint + audit sheet stand in for it); startup cleanup of stale `.part` files;
run-event listener-install retry.

---

## Wave 1 — Backend cancellation truthfulness (Python only)

Fixes round-1 findings: accepted-cancel→success, accepted-cancel→backend_error,
uncancellable write/promote windows, RefDes fallback hang risk, unsafe doc close.

### Task 1.1: Cancel checks around write → verify → promote in all four runtimes

**Files:**
- Modify: `backend/python/fmea/runtime.py` (both output strategies: standard write block
  and preserve block, near `atomic_write_path` → `verify_excel_readable` → `atomic_finalize`)
- Modify: `backend/python/bom_compare/runtime.py` (three blocks: group path, custom path,
  extraction-compare path)
- Modify: `backend/python/failure_rate/runtime.py` (around `logic.save_results`)
- Modify: `backend/python/refdes_extractor/runtime.py` (output phase after the engine
  returns: before `annotate_results`, before workbook build, and around save/verify/promote)
- Test: `backend/tests/test_cancel_bridge.py` (extend) and/or per-tool runtime test files

**DECIDED semantics:** `atomic_finalize` (the `os.replace`) is the commit point. The
runtime must check cancellation (raising `CancellationError`) at three positions:
(a) immediately after the writer returns, (b) immediately after `verify_excel_readable`,
(c) immediately before `atomic_finalize`. A cancel that lands before the commit point
must produce the `cancelled` terminal and clean up the `.part` temp (the existing
exception-unwind cleanup already does this — verify per tool, don't duplicate cleanup).
A cancel that lands after the commit point completes as success (Task 1.2 handles its
reporting). RefDes additionally gets a `bridge.cancel.check()` after the extraction
engine returns and before coverage/annotation post-processing (currently the last check
is before group detection — the whole output phase is uncancellable).

- [x] **Step 1:** For each tool, write a failing test: start a run against tiny fixture
  inputs with a cancel latched via the tool's cancel bridge *after* the compare/generate
  phase but *before* promote. Recommended technique (already used in
  `test_fmea_phase_d.py`'s write-phase cancellation test — mirror it): monkeypatch
  `verify_excel_readable` (or the tool writer) to set the cancel event, then assert the
  run raises `CancellationError` and **no final output file exists** (only-temp-cleaned).
  One test per tool path = 6 tests (fmea standard, fmea preserve, bom group, bom custom,
  extraction compare, failure rate, refdes → 7).
- [x] **Step 2:** Run them; confirm each fails because the run completes successfully.
- [x] **Step 3:** Implement the checks. Keep them one-liners
  (`bridge.cancel.check("Cancelled before finalizing output")` or the tool's equivalent);
  do not restructure the write blocks.
- [x] **Step 4:** Full backend suite green.
- [x] **Step 5:** Commit: `Runtimes: Check cancellation across write/verify/promote`

### Task 1.2: Cancel-aware terminal reporting in `_run_in_background`

**Files:**
- Modify: `backend/python/sidecar_main.py` (`_run_in_background`, ~414–462)
- Modify: `contracts/sidecar-protocol.md` (terminal-outcome section)
- Test: `backend/tests/test_sidecar_main.py`

**DECIDED semantics:**
1. **Error path:** in the generic `except Exception` handler, if
   `run.cancel_requested.is_set()`, emit the `cancelled` terminal pair
   (`status(cancelled)` + `cancelled` envelope) instead of `backend_error`. Log the
   swallowed exception's type/message + traceback into the run log first (INFO level,
   prefixed `Cancellation superseded error:`) so diagnostics survive. This fixes the
   verified accepted-cancel→backend_error path (pre-bind validation failure after ack).
2. **Success path:** after the adapter returns normally, if `run.cancel_requested.is_set()`,
   do NOT convert the outcome (the output file is already promoted — reporting
   `cancelled` would lie about the file). Emit success as today PLUS one run-log line:
   `"Cancel arrived after the output was finalized; the run completed and the report was written."`
   Document this residual (microsecond-scale) window in `contracts/sidecar-protocol.md`.

- [x] **Step 1:** Failing subprocess test A: send `execute_run` for a workflow whose
  validation will fail at execute time (e.g. input file deleted between validate and
  execute — the existing sidecar tests show how to stage this), latch `cancel_run`
  immediately after the ack, assert the terminal envelope is `cancelled`, not
  `backend_error`.
- [x] **Step 2:** Failing (or characterization) test B: cancel latched after adapter
  success → terminal is still `result` (success) AND the run log contains the
  "finalized" line.
- [x] **Step 3:** Implement; re-run; green. Update the protocol doc in the same commit.
- [x] **Step 4:** Commit: `Sidecar: Report cancelled when a latched cancel supersedes an error`

### Task 1.3: RefDes fallback — stop_event + timeout wrapper

**Files:**
- Modify: `backend/python/refdes_extractor/runtime.py` (`detect_groups_with_fallback`
  call, ~line 808 — currently passes no `stop_event`)
- Modify: `backend/python/refdes_extractor/refdes_extractor_logic.py`
  (`detect_groups_with_fallback`, bare `page.get_text("words")` probe ~line 696)
- Test: `backend/tests/test_extraction_engine.py` or a refdes runtime test

**Semantics:** Pass the runtime's stop_event into `detect_groups_with_fallback`. Replace
the bare `page.get_text("words")` probe with the existing timeout wrapper
(`extraction_engine._get_words_with_timeout` — import it or expose a thin helper; do NOT
copy-paste its thread logic). Timeout value: reuse the wrapper's existing default.

- [x] **Step 1:** Failing test: call `detect_groups_with_fallback` with a pre-set
  stop_event and a stub doc; assert it raises the cancellation path instead of scanning
  (the function's internal stop checks exist but were inert with `stop_event=None`).
- [x] **Step 2:** Implement, green, commit:
  `RefDes: Wire stop_event + get_text timeout into group-detection fallback`

### Task 1.4: Zombie-thread-aware document close + analyzer cancel pass-through

**Files:**
- Modify: `backend/python/refdes_extractor/runtime.py` (finally block:
  `cleanup_words_extraction_threads()` return value is currently discarded, then
  `doc.close()` unconditionally)
- Modify: `backend/python/fmea/fmea_template_analyzer.py` (pandas re-read ~585–592:
  pass `cancel_check` into `try_read_table`; the parameter already exists on
  `try_read_table`)
- Test: `backend/tests/test_refdes_runtime.py`, `backend/tests/test_fmea_phase_d.py`

**DECIDED semantics:** If `cleanup_words_extraction_threads()` reports live zombie
threads (capture its return; if it doesn't return a count, make it return one — it
already knows), **skip `doc.close()`** and emit a run-log WARNING
(`"N extraction thread(s) still running; leaving the PDF handle open to avoid a native crash."`).
Deliberately leaking one fitz document beats a C-level crash — the module's own comments
say so.

- [x] **Step 1:** Failing test: monkeypatch cleanup to report 1 zombie; assert
  `doc.close` is NOT called and the warning is logged. Second test: zero zombies →
  close IS called.
- [x] **Step 2:** Implement both changes, green, commit:
  `RefDes/FMEA: Guard doc close on zombie threads; cancellable analyzer re-read`

**Wave 1 exit:** suites green; CHANGELOG entry; counts synced; STOP for review.

---

## Wave 2 — Rust session integrity + documentation honesty

Fixes round-2 F4 (reader can kill successor session), silent emit drops, and the
round-1 orphan-guarantee overstatements. Rust only + docs.

### Task 2.1: Session-identity-guarded teardown (`disconnect_if_current`)

**Files:**
- Modify: `src-tauri/src/lib.rs` — `spawn_stdout_reader` (EOF arm and read-error arm both
  call `disconnect_managed_session`), `kill_managed_session` (~418–424, blind
  `session_guard.take()`), heartbeat supervisor (~788–815)
- Test: Rust unit tests in `lib.rs` (`#[cfg(test)]` module — follow the existing
  forwarding-filter tests' style)

**Semantics:** Every teardown initiated by a per-session task (stdout reader, heartbeat
supervisor) must only kill the session it belongs to. Capture the session generation in
the reader at spawn (the heartbeat already captures `my_generation` — mirror that).
Replace their calls with a `disconnect_if_current(shared, expected_generation, ...)`
that, **under the session lock in one critical section**: reads the current generation,
returns without side effects if it differs, otherwise takes + kills the session and runs
the disconnect bookkeeping. `shutdown()` and explicit `force_disconnect` paths keep the
unconditional behavior (they act on behalf of the whole app, not one session). The
heartbeat's existing check-then-kill becomes atomic by going through the same function.

- [x] **Step 1:** Failing unit test for the guard itself: construct the shared state,
  advance the generation past the caller's, call `disconnect_if_current`, assert the
  current session survives; matching-generation call kills it. (Test the state machine,
  not a real child process — factor the identity check so it's testable without
  spawning python.)
- [x] **Step 2:** Implement; wire reader + heartbeat through it; `npm run cargo:test`
  green; full app suites still green.
- [x] **Step 3:** Commit: `Bridge: Teardown paths kill only their own session generation`

### Task 2.2: Log dropped webview emits

**Files:** Modify `src-tauri/src/lib.rs` (`emit_run_event` ~384, `emit_session_event`
~392 — both currently `let _ =`).

**Semantics:** On `Err`, `eprintln!` (or the crate's existing logging) with event kind +
run_id. No retry, no user surface. Comment why (diagnostic breadcrumb for the
no-exactly-once caveat).

- [x] Implement + commit (no test required — logging only):
  `Bridge: Log webview emit failures instead of discarding`

### Task 2.3: Execute-timeout must not strand a ghost run silently

**Files:**
- Modify: `frontend/src/shared/backend/` tool dispatch error handling (all four tools'
  `catch` around `executeRun` — the shared helper if one exists, else each tool)
- Modify: `contracts/sidecar-protocol.md`
- Test: `frontend/src/features/toolRunDispatch.test.tsx`

**DECIDED semantics (reviewer decision — do not kill the session):** When the
`executeRun` invoke rejects with the bridge's timeout error (match the timeout error
string the bridge returns — find it in `lib.rs` and export/document the exact text),
the tool must NOT show a generic failure. Show a warning toast:
title `"Backend is still preparing the run"`, detail
`"Validation is taking unusually long (large or cloud-synced files). The run will attach automatically if the backend accepts it."`
and leave local state idle. Recovery happens via Wave 3's ack-fallback registration
(Task 3.3) — note the pairing in a comment. Non-timeout errors keep today's behavior.

- [x] **Step 1:** Failing test: mock `executeRun` to reject with the timeout message;
  assert warning toast (not error) and no session reset side effects.
- [x] **Step 2:** Implement, green, commit:
  `Tools: Treat execute-timeout as acceptance-unknown, not failure`

### Task 2.4: Honesty fixes — orphan guarantee + false race comment

**Files:**
- Modify: `src-tauri/src/lib.rs` spawn-sequence comment (~1009–1016) and `windows_job`
  module comment (~49–52)
- Modify: `docs/ARCHITECTURE.md` (~186–189 "never orphaned" + the ~575 symptom-table row)

**Semantics:** State precisely what is guaranteed: after `AssignProcessToJobObject`, the
job kills the tree on bridge death; `CREATE_SUSPENDED` guarantees the child never *runs*
outside the job; an external force-kill of the bridge between `spawn()` and assignment
can leave one *suspended, never-scheduled* `python.exe` (inert orphan). Name the
accepted residual risk and why `PROC_THREAD_ATTRIBUTE_JOB_LIST` was deferred.

- [x] Doc/comment edits + commit: `Docs: Qualify the sidecar orphan guarantee honestly`

**Wave 2 exit:** suites green; CHANGELOG; STOP for review.

---

## Wave 3 — Frontend run-lifecycle unification

Fixes round-2 F1/F3/F5/F6/F7/F8/F9 and round-1's Browse-during-run cancel delay.

### Task 3.1: One terminal-phase vocabulary

**Files:**
- Modify: `frontend/src/shared/backend/runLifecycle.ts` (export the definitions; fix the
  status-event guard ~124–131)
- Modify: `frontend/src/stores/runStore.ts` (`TERMINAL_PHASES` ~127–132,
  `markDisconnected` ~90–112)
- Modify: `frontend/src/shared/backend/useBackendBusyReset.ts` (`TERMINAL_RUN_PHASES`)
- Modify: `frontend/src/shared/backend/useDesktopRunController.ts` (terminal-effect list
  ~210; `resetSessionUnlessLive` live-set ~351–362)
- Test: `frontend/src/shared/backend/runLifecycle.test.ts`, `useBackendBusyReset.test.ts`,
  `useDesktopRunController.test.ts`

**DECIDED semantics — exactly two exported sets, all five current call sites re-derived
from them (delete the local copies):**

```ts
// runLifecycle.ts — single source of truth
export const SETTLED_PHASES = ["success", "failure", "cancelled"] as const;      // run truly over
export const INACTIVE_PHASES = [...SETTLED_PHASES, "disconnected"] as const;     // does not block a new start
export const LIVE_PHASES = ["starting", "running", "cancelling"] as const;       // protected from reset
```

Consumer mapping (fix each to the named set):
- status-event guard (`patchFromRunEvent`): reject a non-settled status when current
  phase is in `SETTLED_PHASES` (as today) **and additionally**: when current phase is
  `cancelling`, accept only settled statuses (sticky cancelling — a late `running` can
  no longer regress it); when current phase is `disconnected`, reject ALL status events
  (only reconnect logic or a new run may leave `disconnected`).
- `markDisconnected`: skip only `SETTLED_PHASES` (unchanged behavior, shared constant).
- `findLiveRunConflict` / cross-tool gate: non-conflicting = `INACTIVE_PHASES` (unchanged).
- `useBackendBusyReset`: reset on `SETTLED_PHASES` (unchanged, shared constant).
- controller terminal effect: fire on `INACTIVE_PHASES` members it handles today.
- `resetSessionUnlessLive`: protect `LIVE_PHASES` (this adds `cancelling` — the F6 fix).

- [ ] **Step 1:** Failing tests: (a) `running` status after `cancelling` → patch is null;
  (b) `running` status after `disconnected` → null; (c) `resetSessionUnlessLive` with a
  `cancelling` run → session survives; (d) existing guard behaviors still pass.
- [ ] **Step 2:** Implement, typecheck + vitest green.
- [ ] **Step 3:** Commit: `Lifecycle: One terminal vocabulary; sticky cancelling/disconnected`

### Task 3.2: Generation-aware reconnect clearing

**Files:**
- Modify: `frontend/src/shared/backend/useBackendBootstrap.ts` (the unconditional
  `clearActiveRun()` ~60–62; capture generation at disconnect in the subscription
  handler ~135–157)
- Test: `frontend/src/shared/backend/useBackendBootstrap.test.ts` (REWRITE the test that
  encodes "clears any active run when reconnect succeeds" — it encodes the bug)

**Semantics:** When a `disconnected` session event arrives, record
`disconnectedGeneration = <the generation of the session that died>` (the session event
carries it; if not, use the current activeRun's `sessionGeneration`). On health-check
success, clear the active run **only if** `activeRun.sessionGeneration <= disconnectedGeneration`.
A run registered on the fresh session (higher generation) survives. Also cancel pending
reconnect timers when any run is accepted on a new session (the accepted response
carries `session_generation` — compare and clear timers).

- [ ] **Step 1:** Failing test: disconnect at gen 1 → user starts run accepted at gen 2 →
  scheduled health callback resolves → assert the gen-2 run is STILL active. Keep a
  companion test: gen-1 stale run IS cleared.
- [ ] **Step 2:** Implement, green, commit:
  `Bootstrap: Reconnect clears only runs from the dead session generation`

### Task 3.3: Ack-fallback run registration

**Files:**
- Modify: `frontend/src/shared/backend/useBackendRunSubscription.ts` (~14–18 drop gate)
- Modify: `frontend/src/shared/backend/runLifecycle.ts` (`beginAcceptedRun` idempotency;
  the `case "ack": return null` projector arm stays null for *registered* runs)
- Possibly modify: `backend/python/sidecar_main.py` ack payload (additive only) + zod
  schema + `contracts/sidecar-protocol.md`, IF the ack payload lacks what's needed
- Test: `frontend/src/shared/backend/useBackendRunSubscription.test.ts`

**Semantics:** When an `ack` run event arrives and **no** active run is registered,
register the run from the ack (runId, sessionGeneration, toolId, workflowId, startedAt).
Determine `toolId` from the ack's `workflow_id` via the existing workflow→tool mapping
(the tool registry / dispatch tables already know it); only if the ack payload lacks
`workflow_id` extend the Python ack payload additively and update the zod schema +
protocol doc. When an ack arrives and a run with the SAME runId is already registered,
no-op (today's behavior). `beginAcceptedRun` must be idempotent for a matching runId
(the invoke response may resolve after the ack event already registered the run) —
same-runId re-registration must not reset accumulated phase/log state.

This closes both verified windows: fast-terminal-before-registration (F1) and the
timeout ghost run (F2/Task 2.3) — the late ack now attaches the run to the UI, making
it visible and cancellable.

- [ ] **Step 1:** Failing tests: (a) ack with no active run → run registered with correct
  toolId; subsequent `status`/`result` events apply. (b) ack for already-registered
  runId → state unchanged. (c) `beginAcceptedRun` after ack-registration of the same
  runId → phase/logs preserved.
- [ ] **Step 2:** Implement, green, commit:
  `Subscription: Register runs from ack when the invoke response lost the race`

### Task 3.4: Disable run-invalidating controls during live phases

**Files:**
- Modify: `frontend/src/components/WorkflowSelector.tsx`, `StrategySelector.tsx`
  (add `disabled?: boolean` — set `disabled` + `aria-disabled` on the buttons, visually
  dim per existing disabled patterns)
- Modify: all four tool components (pass `disabled` while the owning tool's phase is in
  `LIVE_PHASES`; disable `InputGrid` Browse in ALL tools while ANY run is live)
- Modify: `frontend/src/components/InputGrid.tsx` (accept a `browseDisabledReason?: string`
  → disabled + `title` hint, per wiring invariant #2)
- Test: `frontend/src/components/WorkflowSelector.test.tsx`, `InputGrid.test.tsx`,
  tool tests

**DECIDED semantics (reviewer decision):** Browse is disabled app-wide during any live
run because `list_sheets`/`inspect_input` run on the sidecar's single stdin thread and
delay `cancel_run` (verified head-of-line finding). Hint text:
`"File inspection is paused while a run is active."` Workflow/strategy cards are
disabled only within the tool that owns the live run (they trigger
`resetSessionUnlessLive`, which Task 3.1 already hardened — this is defense in depth).

- [ ] **Step 1:** Failing tests: selector honors `disabled`; InputGrid Browse disabled
  with hint when a cross-tool run is live.
- [ ] **Step 2:** Implement, green, commit:
  `UI: Disable Browse and workflow controls during live runs`

### Task 3.5: RefDes cross-check failure produces a qualified outcome

**Files:**
- Modify: `backend/python/refdes_extractor/runtime.py` (the soft-fail paths that set
  `bom_load_error` / zero-RefDes and build the result payload ~740–767, ~964–1005)
- Test: `backend/tests/test_refdes_runtime.py`,
  `frontend/src/shared/backend/useDesktopRunController.test.ts` (existing warning-count
  toast mapping — extend only if needed)

**Semantics:** When the BOM cross-check soft-fails, increment the result's existing
`warning_count` (or set it if absent) so the frontend's ALREADY-EXISTING
warning-qualified toast path fires (verifier confirmed the controller appends
`— N warning(s)` when `warning_count > 0`). No new frontend code unless the count is
not currently plumbed for refdes.

**Also (round-2 F9a truthfulness):** in the subscription's result-parse-failure path
(`errorCode: "RESULT_SCHEMA_MISMATCH"`), the failure toast currently reads like an
ordinary run failure. Change the toast copy for that specific errorCode to
`"Run completed, but the result could not be displayed"` (detail: the output file was
written; check the run log) — the backend DID succeed and the output exists. Keep the
phase conversion itself (the panel must not pretend it can render an unparseable
result); update the existing test that covers this path.

- [ ] **Step 1:** Failing backend test: cross-check soft-fail run → result
  `warning_count >= 1`.
- [ ] **Step 2:** Implement, green, commit:
  `RefDes: Count BOM cross-check failure as a warning so the toast qualifies`

**Wave 3 exit:** typecheck + all suites green; CHANGELOG; counts synced; STOP for review.

---

## Wave 4 — Preserve-formatting merge data integrity (highest stakes)

Fixes round-3 F1–F15 per the four **user decisions**: (1) blanks NEVER overwrite; real
conflicts overwrite WITH a per-cell audit sheet; (2) filename token `DarkStar` → `Merged`;
(3) flag-never-guess identity; (4) images warn-only (NO Pillow).

**Fixture prerequisite (build FIRST — every task below uses it):** a pytest fixture
factory in `backend/tests/` producing a preserve-target workbook that contains, at
minimum: a header row NOT at row 1; two function groups incl. two rows sharing
(RefDes, failure mode) with different part numbers; hand-authored text in
Local Effect / End Effect cells; a formula cell in a mapped column; an unmanaged
"Engineering Notes" column; a merged range below the insertion region; a custom row
height; a user sheet literally named `Validation_Warnings` with content; and a second
plain sheet. Round-trip helpers: load output with openpyxl and assert cell-level facts.
The existing preserve test (`test_fmea_phase_d.py` ~3831) has NO piece-part rows — do
not copy its fixture shape.

### Task 4.1: Blank-guard + Merge Changes audit sheet

**Files:**
- Modify: `backend/python/fmea/fmea_template_writer.py`
  (`_update_cell_preserving_format` ~122–137 and the matched-row loop ~324–333)
- Test: `backend/tests/test_fmea_phase_d.py`

**DECIDED semantics:**
- Blank generated value = `""`, `None`, or NaN. Blank NEVER overwrites a non-blank
  existing cell — skip the write, increment a per-column `blanks_skipped` counter
  (reported as one summary line per column on Template_Merge_Summary; no per-cell rows).
- Non-blank generated value ≠ existing non-blank value → write it AND record a row on a
  new **`Merge Changes`** sheet: `Excel Row | RefDes | FMEA-ID | Column | Previous Value | New Value`.
  Values equal after `str().strip()` comparison → no write, no record.
- Non-blank generated onto blank cell → write, no audit row (that's the merge doing its
  job on empty cells).
- The `Merge Changes` sheet is tool-authored: banner row + ownership marker per Task 4.3,
  styled like the other diagnostic sheets, written only when it has rows.

- [ ] **Step 1:** Failing tests: (a) hand-written End Effect survives a piece-part
  generation merge (generated blank), byte-identical; (b) formula cell in a mapped
  column survives a blank; (c) real differing value overwrites AND appears on
  `Merge Changes` with old+new; (d) equal values produce no audit row; (e) blank-skip
  counts appear on the summary sheet.
- [ ] **Step 2:** Implement, green, commit:
  `FMEA preserve: Blanks never overwrite; audit real changes on Merge Changes sheet`

### Task 4.2: Flag-never-guess identity

**Files:**
- Modify: `backend/python/fmea/fmea_template_writer.py` (positional pairing ~307–321;
  group index pop ~508)
- Modify: `backend/python/fmea/fmea_template_analyzer.py` (duplicate-group warning
  ~628–638 becomes a hard signal)
- Modify: `backend/python/fmea/runtime.py` (surface the blocking error at the earliest
  gate that has the analysis in hand)
- Test: `backend/tests/test_fmea_phase_d.py`

**DECIDED semantics:**
- Duplicate (RefDes, failure-mode) keys on EITHER side within a group: pair only when
  exactly 1:1. Otherwise: template rows left completely untouched (no value writes) and
  flagged on `Template_Merge_Issues` with reason `AMBIGUOUS_IDENTITY` (add to the
  REASON_CODE_LABELS vocabulary — there is a lockstep test that scans emitted reason
  codes; extend it); the corresponding generated rows are NOT inserted (they'd otherwise
  duplicate) and are listed on the issues sheet too.
- Duplicate normalized group IDs (`CPU-001-A` + `CPU-001-B` → `CPU-001`): blocking
  friendly `ValidationError` BEFORE any workbook mutation, naming the colliding sheet
  rows/IDs: `"Function groups 'CPU-001-A' (row 12) and 'CPU-001-B' (row 40) collapse to the same ID 'CPU-001'. Give them distinct IDs and re-run."`
  Remove the now-dead independent-processing warning text.
- Whitespace hygiene: normalize failure-mode identity with `" ".join(s.split()).upper()`
  (internal-whitespace collapse) on BOTH sides — closes the verified
  `"OPEN  CIRCUIT"` mismatch without loosening anything else.

- [ ] **Step 1:** Failing tests: (a) two `U1/OPEN` template rows + two generated →
  neither touched, both flagged, unmanaged "Engineering Notes" cells untouched;
  (b) colliding group IDs → ValidationError naming both, workbook file unchanged;
  (c) `OPEN  CIRCUIT` (double space) matches `OPEN CIRCUIT`.
- [ ] **Step 2:** Implement, green, commit:
  `FMEA preserve: Never guess identity — flag ambiguity, block colliding groups`

### Task 4.3: Sheet ownership markers

**Files:**
- Modify: `backend/python/fmea/fmea_template_writer.py` (all `del wb[name]` sites
  ~679–723) and the diagnostic-sheet writers in `fmea_generator_logic.py` (banner
  writers — several sheets already start with a banner row; formalize it)
- Test: `backend/tests/test_fmea_phase_d.py`

**Semantics:** Every tool-authored sheet gets a deterministic ownership marker: cell A1
of the sheet begins with the existing banner text prefix — standardize on a constant
`TOOL_SHEET_MARKER = "Generated by Reliability Tools"` embedded at the start of each
banner (adjust existing banner strings to start with it; keep their explanatory tails).
Before deleting a colliding sheet: delete only if its A1 value starts with the marker.
Otherwise it is a USER sheet: do not delete; write the tool sheet as
`<name> (Generated)` (apply Excel's 31-char cap via the existing sanitize helper),
log a WARNING, and add a `Template_Merge_Issues` row reason `SHEET_NAME_CONFLICT`.

- [ ] **Step 1:** Failing tests: (a) user sheet named `Validation_Warnings` with content
  survives byte-identical; tool output lands on `Validation_Warnings (Generated)`;
  issues row present; (b) second run over a previous output replaces the tool-authored
  sheets in place (marker match → delete+recreate).
- [ ] **Step 2:** Implement (banner constant + guard), green, commit:
  `FMEA: Ownership-marked diagnostic sheets; never delete user sheets`

### Task 4.4: Insertion rebasing + false-comment fix + lossy-feature preflight

**Files:**
- Modify: `backend/python/fmea/fmea_template_writer.py` (insert block ~346–365; DELETE
  the false comment `# openpyxl 3.1+ auto-adjusts merged-cell references on insert`)
- Test: `backend/tests/test_fmea_phase_d.py`

**DECIDED semantics (openpyxl 3.1.5 moves cells ONLY — verified in vendored source):**
After each `ws.insert_rows(insert_at, amount)`:
1. Rebase merged ranges: for each range in a pre-insertion snapshot of
   `ws.merged_cells.ranges`: `max_row < insert_at` → untouched;
   `min_row >= insert_at` → shift both bounds by `amount`;
   straddling (`min_row < insert_at <= max_row`) → extend `max_row += amount`
   (matches Excel's own insert-inside-merge behavior). Unmerge/remerge via coordinates.
2. Rebase `row_dimensions` (height, hidden, outline) for rows `>= insert_at`: shift keys
   by `amount` (iterate a snapshot descending to avoid collisions).
3. Do NOT attempt validations / conditional formatting / tables / formulas / hyperlinks.
   Instead, detect whether any of those exist at rows `>= insert_at` on the FMEA sheet
   and, if so, emit ONE run-log WARNING naming the feature kinds and add a
   `Template_Merge_Issues` row reason `NOT_REBASED_FEATURES` listing them.
4. Preflight (analysis stage, once per run): if the workbook contains embedded images
   (`ws._images`) or charts, emit a run-log WARNING that images/shapes are not carried
   into the output (Pillow deliberately absent — user decision). Add one USER_GUIDE
   sentence for rich text being flattened (no runtime detection — documented limitation).

- [ ] **Step 1:** Failing tests: (a) merged range below an insertion lands shifted by
  `amount` in the saved output; (b) straddling merge extends; (c) custom row height
  moves with its row; (d) validation-below-insertion produces the warning + issues row.
- [ ] **Step 2:** Implement, green, commit:
  `FMEA preserve: Rebase merges/row-dims after insertion; warn on what can't move`

### Task 4.5: Column-mapping injectivity + fail-closed analysis

**Files:**
- Modify: `backend/python/fmea/fmea_template_analyzer.py` (mapping loop ~327–350;
  `col_to_index` duplicate-header collapse ~315–325; `_detect_header_row` ~247–281;
  missing identity columns ~401–409)
- Test: `backend/tests/test_fmea_phase_d.py`

**Semantics:**
- Injective mapping: maintain a claimed-destinations set; a second output header
  resolving to a claimed template column is treated as unmapped (falls into the
  appended-new-columns path) + run-log WARNING naming both contenders.
- Duplicate template headers: keep current last-wins binding but WARN
  (`Template_Merge_Issues` reason `DUPLICATE_TEMPLATE_HEADER`).
- Header detection: require a minimum score (`>= 2` matched known headers — mirror
  `_detect_fmea_sheet`'s threshold); below it raise friendly `ValidationError`
  (`"Couldn't find the FMEA header row in sheet '<name>' (looked in the first 10 rows for columns like FMEA-ID, Reference Designator, Failure Mode)."`).
- Missing RefDes or Failure-Mode template mapping: friendly `ValidationError` instead of
  silent `("", "")` identity keys.

- [ ] **Step 1:** Failing tests: (a) combined "Part Number / Part Description" column
  claimed once, second field appended as new column + warning; (b) headerless sheet →
  ValidationError, not a row-1 guess; (c) template without a detectable RefDes column →
  ValidationError.
- [ ] **Step 2:** Implement, green, commit:
  `FMEA analyzer: Injective mapping; fail closed on headers and identity columns`

### Task 4.6: Snapshot fingerprint + per-column insert styles + naming

**Files:**
- Modify: `backend/python/fmea/fmea_template_analyzer.py` (fingerprint capture at load
  ~542–550; re-check before the pandas re-read ~585; per-column style capture ~454–461)
- Modify: `backend/python/fmea/runtime.py` (fingerprint re-check after write, before
  `atomic_finalize`; `mode="DarkStar"` call site ~972–976)
- Modify: `backend/python/fmea/fmea_template_writer.py` (`build_template_output_path`;
  per-column style application ~357–365)
- Modify: `backend/python/common/utils.py` (collision-proof output naming — shared
  helper used by `build_output_filename` and the template path builder)
- Test: `backend/tests/test_fmea_phase_d.py`, `backend/tests/test_output_directory_helpers.py`

**Semantics:**
- Fingerprint = `(st_mtime_ns, st_size)` of the target captured at analyzer load.
  Re-verify before the pandas re-read and again in the runtime immediately before
  `atomic_finalize`. Mismatch → friendly `ValidationError`:
  `"The target workbook changed on disk while the merge was running (is it open in Excel or syncing?). No output was written — close it and re-run."`
  (temp cleaned by the existing unwind).
- Per-column styles: capture the style tuple per column from the first piece-part row
  (falling back to column A's for columns beyond the captured row's width); apply
  column-wise on inserted rows.
- Filename: `mode="Merged"` (grep for other `"DarkStar"` literals in backend/ and fix
  the same way; the frontend brand mark is out of scope).
- Handle-leak guard (round-3 F17): wrap the analyzer's post-`load_workbook` work in
  `try/finally` so the workbook handle is closed when sheet detection, the pandas
  re-read, or classification raises mid-analysis (today the close only happens after a
  successful return). On success, ownership of the open workbook still transfers to the
  writer exactly as today — only the analyzer's own failure paths gain the close.
- Collision-proof naming: shared helper — if the derived output path exists, append
  `" (2)"`, `" (3)"`, … before the extension until free (bounded at 99 with a
  ValidationError beyond). Wire it into BOTH `build_output_filename` and
  `build_template_output_path` so every tool benefits.

- [ ] **Step 1:** Failing tests: (a) touch the target file mid-merge (monkeypatch the
  writer to modify mtime) → ValidationError, no output file; (b) inserted row's column-H
  cell carries column-H's prototype number format, not column A's; (c) preserve output
  name contains `_Merged_` and no `DarkStar`; (d) pre-existing output at the derived
  name → new file gets ` (2)` suffix, original untouched.
- [ ] **Step 2:** Implement, green, commit:
  `FMEA preserve: Snapshot fingerprint, per-column styles, Merged naming, no-clobber outputs`

### Task 4.7: Protection warning + docs truthfulness sweep

**Files:**
- Modify: `frontend/src/features/fmea/FmeaTool.tsx` (analysis card: render a warning
  chip/badge when `protectedSheet` is true — the state already exists and is never read;
  text: `"Sheet is protected — the merge will modify it without the password."`)
- Modify: `backend/python/fmea/runtime.py` (run-log WARNING when merging into a
  protected sheet)
- Modify: `docs/USER_GUIDE.md` + `frontend/src/features/settings/HelpGuide.tsx`
  (KEEP IN SYNC — rewrite the preserve-mode section: blanks never overwrite; real
  changes audited on Merge Changes; ambiguity flagged not guessed; what is preserved /
  lost / warned, distilled from the review's loss inventory: rich text flattened,
  images/shapes dropped with warning, validations/CF/tables/formulas below insertions
  not rebased; collision-proof `_Merged_` naming). Remove/replace the two false claims:
  "Existing rows … are kept" (§ output strategies) and "Local/Next/End Effect …
  Preserved from the source FMEA" (columns table) — state the new semantics instead.
- Modify: `docs/CHANGELOG.md` (Unreleased: user-facing summary of all Wave-4 changes,
  incl. the `DarkStar` → `Merged` filename rename notice)
- Test: `frontend/src/features/fmea/FmeaTool.inspection.test.tsx` (protection chip)

- [ ] **Step 1:** Failing test: analysis result with `protected_sheet: true` renders the
  warning chip.
- [ ] **Step 2:** Implement + full docs sweep, green, commit:
  `FMEA preserve: Surface sheet protection; make the docs tell the truth`

**Wave 4 exit:** full suites green (expect substantial new-test growth — sync all four
count locations); sidecar self-test green; CHANGELOG complete; STOP for final review.

---

## Discovered out-of-scope

(Implementing agent: append items here instead of fixing them.)

- `sidecar_main._parse_log_level` recognizes embedded `" WARNING:"` text but not
  the common leading `"WARNING:"` form (or an unprefixed semantic warning), so
  many streamed warning lines are currently classified as INFO.
- Direct legacy/NextGen RefDes engine entry points that own their own fitz
  document still leave document closure to a context manager even if word-thread
  cleanup reports a survivor. The desktop runtime-supplied document path is now
  guarded, but the direct API ownership paths need a separate lifecycle design.
- `detect_groups_from_drawings` retains an unbounded direct word-read default for
  compatibility. Its sole in-repo production caller supplies the bounded reader,
  but a future direct caller could omit it and reintroduce the hang risk.
- Generation-guarded teardown prevents an old stdout reader from killing a new
  sidecar, but the old reader can still process buffered frames before EOF. Such
  a frame can refresh the shared heartbeat/fatal-detail state or be forwarded
  after enrichment with the successor's generation. Retiring stale readers from
  all frame processing needs a separate event-session identity design.
- The detailed frontend inventory in `docs/TESTING.md` has pre-existing stale
  per-file counts for the contract, command-palette, run-lifecycle, and BOM
  Compare suites even though the primary inventory and aggregate suite count are
  current. Reconciling historical inventory drift is outside this remediation.
- `CLAUDE.md`'s Windows Job Object gotcha correctly requires assignment for live
  sidecar cleanup but compresses the guarantee and omits the accepted
  pre-assignment suspended-process residual. Task 2.4's documentation scope is
  `docs/ARCHITECTURE.md` plus the Rust source comments; reconcile the shorter
  contributor note in a later documentation sweep.
