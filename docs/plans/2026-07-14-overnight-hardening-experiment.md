# Overnight Hardening Experiment

**Status:** REVIEWED DRAFT — anti-stall execution contract added. Do not execute it
until the user supplies the final baseline commit after a clean release build and
the supervised preflight reaches `READY FOR GOAL`.

**Timebox:** Up to 8 hours. Eight hours is a ceiling, not a quota. Never invent
churn merely to consume the timebox.

**Intent:** Improve reliability, maintainability, future-LLM edit safety, file-I/O
defenses, build truthfulness, and code hygiene without adding product features or
changing intentional user-visible behavior. Keep every experiment isolated and
easy to accept, cherry-pick, or reject in the morning.

---

## 1. Definition of success

The run is successful when:

1. It starts from the exact commit the user built and approved.
2. The canonical `main` worktree remains untouched.
3. Every behavior fix begins with a failing regression test. Behavior-preserving
   refactors begin with characterization coverage where existing tests are weak.
4. Changes are small, single-purpose commits with a clear evidence trail.
5. No dependency, protocol, feature, workflow, UI, or file-format change sneaks in.
6. Anything moved to the archive is proven unreachable by more than one signal,
   remains excluded from runtime/build/test scans, and has a restoration manifest.
7. All applicable suites and the full packaged release pipeline finish green.
8. A morning report makes accepting all, some, or none of the branch straightforward.

If the audit finds little worth changing, a short branch plus a strong evidence
report is a better result than speculative cleanup.

---

## 2. Non-goals

- No new tools, workflows, controls, output sheets, options, or visual redesign.
- No dependency addition, removal, upgrade, lockfile refresh, new linter, or downloaded
  audit tool. Dependency cleanup is evidence/report-only in this experiment.
- No protocol/schema/event-order changes.
- No version bump or release publication.
- No performance rewrite without a reproduced performance defect and baseline.
- No blanket formatter, import sorter, mass rename, or repository-wide comment churn.
- No removal based only on a filename, age, TODO, warning suppression, or one static
  search result.
- No push, PR, merge to `main`, force operation, destructive reset, or history rewrite.
- No changes to canonical or pre-existing user-owned workbooks, examples, logs, build
  outputs, credentials, or untracked files. Tests/builds may create ignored artifacts
  inside the disposable experimental worktree; never commit or move them to the archive.

---

## 3. Isolation and start protocol (blocking)

### 3.1 Required handoff from the user

Do not begin implementation until the user provides:

- the exact baseline commit SHA;
- confirmation that this reviewed plan is tracked at that SHA;
- confirmation that the full release succeeded at that SHA, preferably via
  `scripts\release.bat __INNER__ --no-pause` for automation, plus its log path;
- permission to create the experimental branch/worktree; and
- any files or active plans that must be quarantined from the experiment; and
- the build-lane authority: **audit-only** (default), or explicit permission for
  test-backed release staging/promotion and frozen-payload membership changes;
- a new, empty experimental-worktree path and `RUN_ID`; and
- confirmation that the computer will remain awake, the Codex desktop app will remain
  running, and no other agent/process will write to either checkout during the goal.

Capture the SHA and release-log path in the external preflight note before editing;
copy them into the tracked ledger and morning report only after the baseline is green.

### 3.2 Worktree model

Use a fresh worktree, not the canonical repo and not an old development copy:

- Canonical/review repo: `C:\Reliability_Eng_Tools` — read-only during the run.
- Experimental worktree: `C:\Reliability_Eng_Tools_Overnight_<RUN_ID>` (or another
  empty, user-approved path).
- Branch: `codex/overnight-hardening-<RUN_ID>`.

`C:\Reliability_Eng_Tools_Overnight` already contains the superseded plan-only branch
from the first attempt. Do not reuse, clean, reset, delete, or build from it. A later
cleanup of that worktree is a separate user-authorized operation.

At plan-writing time, `C:\Reliability_Eng_Tools_Dev` has unrelated history and
user-owned untracked files. Never reuse, clean, reset, move, or delete that workspace.
Re-check this fact at execution time rather than assuming it remains true.

Create the worktree from the user-supplied local SHA. Do not fetch, pull, or contact
the network unless the user explicitly asks.

A fresh worktree does not contain ignored `.venv` or `node_modules` directories. Before
running gates, make isolated copies of the user-approved canonical environments inside
the experimental worktree. Do not junction/symlink writable dependency directories back
to the canonical repo. Verify Python's `sys.prefix` and Node module resolution point at
the experimental copies. If a safe copy is unavailable or lacks disk space, stop and ask
instead of installing dependencies or mutating the canonical environment.

### 3.3 Preflight

Before any edit:

1. Verify the canonical worktree is clean, its `HEAD` equals the supplied SHA, the
   reviewed plan is tracked at that SHA, and no concurrent writer is active.
2. Verify the experimental destination does not already exist and is not registered as
   an old Git worktree; verify the unique `codex/overnight-hardening-<RUN_ID>` branch
   does not already exist locally.
3. Create the `codex/` branch and worktree from that SHA.
4. Verify the experimental tree is clean and has the same SHA.
5. Copy the approved dependency environments, verify they resolve inside the new
   worktree, and resolve every required permission/approval while the user is present.
   Do not start an unattended goal that is expected to pause for access.
6. Capture `git status`, `git log -1`, suite counts, Node/Python/Rust versions, and the
   release-log location in an external scratch note under `C:\tmp`; do not create a
   tracked ledger yet.
7. Run the baseline gates in the new worktree while the user is still present:

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
npm ls --depth=0
.\.venv\Scripts\python.exe -m pip check
npm run tauri:readiness
npm run version:check
npm run typecheck
npm run typecheck:tests
npm run cargo:check
npm run cargo:test
.\.venv\Scripts\python.exe -m pytest backend\tests -q -p no:cacheprovider
npm test
npm run build
.\.venv\Scripts\python.exe backend\python\sidecar_main.py --self-test
```

If the baseline is not clean and green, stop before editing and report the mismatch.
Do not repair an unexplained baseline failure as part of this experiment.
Keep preflight evidence outside the repository under `C:\tmp`; the supervised preflight
must leave the experimental Git tree clean. Before source edits, use the installed
PyInstaller archive viewer on the approved baseline sidecar and record its payload
inventory externally. This distinguishes pre-existing packaging debt from an overnight
regression.

Record the baseline gate durations, especially the full packaged release. Select the
first eligible candidate and write `READY FOR GOAL` plus a timestamp to the external
preflight note. The eight-hour clock starts only after the user sees that marker and
launches Goal mode; setup, dependency copying, approvals, and baseline repair are never
allowed to consume the unattended implementation window.

Obtain the packaged-release duration from explicit timestamps in the supplied successful
release log. If that log cannot prove a trustworthy duration, rerun the release during
supervised preflight. If neither is possible, do not issue `READY FOR GOAL`.

### 3.4 Active-change quarantine

At start, re-read every active plan and list files named by unchecked tasks. Do not
touch those files overnight; log observations instead. Quarantine the specifically
named files—not every documentation file in the repository. This avoids producing a
branch that is technically good but painful to integrate while still allowing unrelated
corrections. Completed Wave 4 work is not an active quarantine, but any new review or
release-preparation work must be assessed from the final baseline rather than memory.

Before every commit, compare `git diff --name-only <BASELINE_SHA>` with the recorded
quarantine list. Any overlap stops that candidate; do not reason around the check.

### 3.5 Supervised launch receipt

Preflight is complete only when the executor reports all of the following in the
external note: baseline SHA, tracked-plan identity, release-log path, fresh branch and
worktree, both Git statuses, isolated Python/Node resolution, baseline counts and
durations, frozen-payload inventory, quarantine list, build-lane authority, verified
command permissions, absolute receipt path, `FINAL_RESERVE`, `IMPLEMENTATION_WINDOW`,
the first eligible candidate, and proof that every required unattended final command
(especially the release) has a bounded runner with verified process-tree cleanup.

The user must see a green receipt and explicitly launch the Stage-B Goal from Section 11.
That launch starts the eight-hour clock. As its first tracked action, the Goal creates
`docs/reviews/<RUN_ID>-overnight-ledger.md` from the external receipt. If any receipt
field changes before launch, return to supervised preflight instead of improvising. The
receipt expires after 30 minutes or immediately on any canonical/worktree status change,
whichever happens first.

---

## 4. Hard safety rules

The following repository invariants are load-bearing and remain unchanged:

- Python stays offline/air-gapped and passes the security audit.
- The sidecar keeps one active run, 5-second heartbeat, and 15-second Rust timeout.
- Rust writes each NDJSON payload + newline + flush under one stdin lock.
- Windows Job Object ownership remains intact.
- `CancellationError` is re-raised before broad exception handlers.
- There is one shell-level `backend://run-event` subscription.
- Tool components remain mounted after first visit.
- Backend errors continue through `describeBackendError`.
- Mock scenarios remain role-complete but never seed desktop state.
- Atomic Excel temp files retain their real extension and are verified before promote.
- StyleArray copies remain isolated; number formats are applied after styling.
- Test counts stay synchronized in every documented location.

Additional overnight rules:

- No new production dependency or tool installation.
- No public API change solely to make code look cleaner.
- No cross-language change unless a reproduced bug truly crosses that boundary and
  all affected contract tests can be run.
- Never log workbook cell contents, paths containing sensitive project names, or user
  data merely to improve diagnostics.
- Do not convert a best-effort warning into a hard failure without explicit approval.
- Do not weaken tests, timeouts, assertions, security checks, or release gates to make
  a change pass.
- Maximum 10 implementation commits and roughly 2,000 changed source lines excluding
  tests, docs, and archived content. Stop earlier if quality would decline.

### Change tiers

| Tier | Overnight action |
|---|---|
| A — local, behavior-preserving, directly testable | May implement with characterization tests and focused gates. |
| B — reproduced correctness/reliability bug | May implement TDD, then run every affected layer and a batch review. |
| C — protocol, process lifetime, concurrency semantics, installer behavior, user-data migration, active remediation area | Audit and report only unless the user explicitly expands authority before sleeping. |

Release documentation, assertions, and behavior-preserving pure build-helper refactors
can be Tier A/B. Desktop/sidecar promotion semantics and frozen-payload membership are
audit-only unless the handoff explicitly opts into the build lane. Installer target,
signing, Windows process lifetime, and Rust path/security semantic changes remain Tier C.

---

## 5. Evidence ledger and selection rubric

Every candidate goes into the ledger before code changes:

| ID | Area | Evidence | User impact | Confidence | Blast radius | Testability | Conflict risk | Decision |
|---|---|---|---|---|---|---|---|---|

Score each dimension High/Medium/Low. Implement only when evidence and testability
are high enough to outweigh blast radius and integration conflict. Priority order:

1. User-data loss/corruption or misreporting.
2. Cancellation, process, output-commit, and stuck-state reliability.
3. File-loading validation and actionable errors.
4. Build/release correctness.
5. Proven duplication or modularity debt that obstructs safe changes.
6. Proven accessibility or interaction inconsistency with a local regression test.
7. Truthful invariant comments and maintainer documentation.
8. Cosmetic cleanup.

“Looks old” and “an LLM says unused” are not evidence.

### 5.1 Anti-stall execution contract

Run the implementation in Codex Goal mode only after Section 3 reaches
`READY FOR GOAL`. The goal must name an outcome, constraints, and verification—not
merely ask for an audit. Do not end the goal after rewriting or restating this plan.

Before launch, calculate:

```text
FINAL_RESERVE = max(
  90 minutes,
  measured Section 3.3 gate-set duration + measured full-release duration + 30 minutes
)
IMPLEMENTATION_WINDOW = 8 hours - FINAL_RESERVE
```

The phase times below are planning targets, not permission to overrun the cutoff. Start
final verification earlier whenever the measured release requires it. If
`IMPLEMENTATION_WINDOW` is less than 60 minutes, do not launch Stage B; reschedule or
obtain separate approval for a report-only run.

During the goal:

- Update the ledger at least every 30 minutes with the active candidate, last completed
  action or commit, running command, next fallback, and elapsed time.
- Give every unattended command a wall-clock timeout and expected quiet period derived
  from its measured baseline. Use it unattended only when timeout cleanup of the whole
  process tree is already proven; otherwise run it during supervised preflight or skip
  it and report why.
- Default focused-command deadline: `max(10 minutes, 3 × analogous baseline duration +
  5 minutes)`. Default full-release deadline: `max(30 minutes, 2 × measured release
  duration + 15 minutes)`. Poll long commands often enough that no wait hides progress
  for more than 60 seconds. A required final gate timing out is a global finalization
  event, never permission to weaken or omit the gate.
- If no file, ledger, test, or command-output progress occurs for 30 minutes outside a
  declared quiet period, treat the candidate as stalled: stop it safely, preserve the
  evidence, and move to the next independent candidate.
- A candidate-level ambiguity, unavailable production input, optional approval, or
  change that would require unsafe cleanup is a **skip before it is run**, not a reason
  to pause the goal for the sleeping user.
- A global stop condition produces an external blocker note and a user-visible final
  status within 10 minutes when the execution environment remains available, or on the
  first resumed turn after an environment/app outage. Never wait silently for approval
  or leave the goal active without saying what blocked it.
- Never run another independently controlled agent, scheduled task, IDE action, or
  process as a concurrent writer to the same worktree. The sole executor may launch and
  await one owned child command pipeline (tests/build/release) at a time. A read-only
  status watchdog may observe the goal, but it may not become a second writer.
- Before each candidate, record a clean boundary and its owned files. If it is skipped
  after edits, reverse only those owned uncommitted edits with an explicit inverse patch;
  never use reset, checkout, clean, or broad deletion. If the candidate leaves live or
  unowned processes, or its boundary cannot be restored cleanly, perform a global stop.
- Even if no candidate qualifies for implementation, complete the evidence ledger and
  morning report with the audited surfaces, rejected candidates, exact reasons, and
  recommended follow-ups. Zero commits may be correct; zero evidence is not.

---

## 6. Eight-hour work sequence

### Phase 0 — Launch confirmation and conflict map (0:00–0:40)

- Confirm the supervised preflight says `READY FOR GOAL`, its SHA still matches both
  worktrees, and no concurrent writer appeared after sign-off. Any drift is an immediate
  global stop, not an overnight repair task.
- Map current entry points, registries, dynamic imports, Tauri command registration,
  sidecar routes, PyInstaller hidden imports/data, test globs, and package roots.
- Build the active-change quarantine list.
- Open and update the evidence ledger created after the green baseline; make no source
  edits until the conflict map is complete.

### Phase 1 — Mechanical audit and triage (0:40–1:40)

Use existing tools only (`rg`, `git`, compilers, and test runners). Inventory:

- `TODO`, `FIXME`, `HACK`, `XXX`, suppressions, and stale comments;
- broad Python exception handlers and cancellation ordering;
- direct Excel/CSV/PDF/file reads and writes that bypass shared helpers;
- repeated normalization, error-description, run-state, and output-path logic;
- frontend `invoke`/`listen`/store ownership and stale async continuations;
- keyboard/focus behavior, ARIA state, disabled-control explanations, and user-facing
  error-copy consistency; visual redesign and new interaction features remain out of scope;
- Rust lock scopes, detached tasks, error conversions, and platform gates;
- build-script/documentation/version/PyInstaller coupling;
- existing repository-configured check-only lint, format, and static-analysis commands;
  do not install a tool or turn a previously failing optional check into a surprise gate;
- tracked files with no static, dynamic, config, packaging, test, or documentation
  references.

Triage first; do not mechanically “fix every match.” A broad catch in a crash dumper,
for example, may be correct while the same shape on a run path may swallow cancel.

### Phase 2 — File-I/O and error-path hardening (1:40–3:20)

This is the highest-value implementation lane outside quarantined work.

For each input role and shared loader, check the actual path for:

- empty/wrong-type path, missing file, directory passed as file, and unsupported suffix;
- OneDrive placeholder detection/hydration and post-hydration existence;
- size guard before expensive reads;
- locked, unreadable, malformed, empty, headerless, and wrong-sheet inputs;
- explicit selected-sheet lookup failing closed instead of silently falling back;
- picker extension claims matching packaged readers and installed dependencies;
- case/whitespace normalization without changing user cell values;
- NaN/None guards before string conversion;
- cancellation around slow reads and expensive parsing;
- project exception type, user-facing label, and retained root-cause diagnostics;
- no check-then-use claim stronger than the code can guarantee.

Also inspect where filesystem work happens relative to timeouts. Path canonicalization,
UNC/share resolution, byte probes, and file stats must not sit outside the bounded
command or cancellation boundary merely because they look like cheap validation.

For outputs, check:

- validated destination and collision-proof naming;
- atomic temp-write → verify → promote ordering;
- cleanup after error/cancel without deleting a prior good output;
- truthful success/cancel/failure reporting after the commit point;
- no direct write to an irreplaceable source document.

Fix at most three confirmed defects in this lane. Each needs a red regression first,
the narrowest implementation, focused tests, and an independent diff review.

### Phase 3 — Exception, cancellation, and modularity audit (3:20–4:35)

- Classify every broad exception in touched run paths: intentional best-effort,
  translated project error, logged-and-rethrown, or bug.
- Verify `CancellationError`/`InterruptedError` ordering wherever computation or I/O
  can be cancelled.
- Extract a helper only when it creates a testable boundary, removes real duplicated
  policy, or makes an invariant explicit. Prefer pure functions and existing public
  module boundaries.
- Do not split files merely because they are long. Do not create abstraction layers
  with one caller or hide control flow behind generic frameworks.
- Keep protocol, payload, store, and runtime names stable.

Behavior-preserving refactors require before/after characterization tests. Run the
whole affected language suite before committing.

### Phase 4 — Comments and future-LLM guardrails (4:35–5:20)

Improve comments only where they prevent a plausible wrong edit:

- explain **why** an ordering, lock scope, cleanup sequence, or duplicate definition
  exists;
- place lockstep cross-references on both definitions;
- identify ownership and lifecycle boundaries near the code;
- document counterintuitive library behavior and point to its regression test;
- add concise module responsibility notes where routing is otherwise ambiguous;
- remove or correct statements contradicted by current code.

Avoid comments that narrate syntax, repeat names, cite unstable line numbers, promise
absolute guarantees the code does not provide, or refer only to an old review phase.
When a comment describes an invariant, prefer a test that fails if it drifts.

### Phase 5 — Dead-code proof and reversible archive (5:20–6:00)

Archive only **confirmed** dead tracked content. Suspected content stays in the report.

Required proof for each file/folder:

1. No static import/reference/re-export.
2. No dynamic route, registry, lazy import, string lookup, Tauri command, mock, test,
   PyInstaller hidden import/data entry, release script, docs link, or packaged asset use.
3. The relevant compiler/typecheck/tests pass without the original path.
4. The packaged release passes after the move.

Never archive fixtures, migration/compatibility code, protocol docs, release evidence,
user examples, or platform-specific code merely because the current machine does not
execute it. A justified `#[allow(dead_code)]` RAII field is not dead code.

Archive layout:

```text
_archive/<RUN_ID>/
  README.md
  manifest.json
  original/<original relative path...>.archived
```

Use `git mv` so review shows the exact relocation. `manifest.json` records:

- original and archived paths;
- classification and evidence;
- original byte size and SHA-256 hash;
- runtime/test/package exclusion proof;
- baseline/parent SHA and archive batch ID (the resulting move commit is recorded in
  the morning report because a commit cannot contain its own hash);
- restoration command; and
- any residual uncertainty.

The archive must remain outside `backend/python`, `backend/tests`, `frontend`,
`src-tauri`, `scripts`, and `contracts`. Confirm all current scanners/package roots
exclude `_archive`; add an explicit exclusion only if a real global scan requires it.
Append `.archived` to executable source, test, script, and package/config suffixes to
prevent normal import/execution and common extension-based discovery. Never place an
`__init__.py`, `package.json`, `Cargo.toml`, or executable launcher in the archive.
Verify the hash again on restore.

A tracked archive is still visible to Git hosting, code indexers, and repository-level
secret scanners. Therefore it may never contain credentials, user data, logs, workbook
samples, or anything that was unsafe to commit at its original path.
Ignored build products, caches, coverage, logs, and user-local files are not archive
material and must not be committed.

If nothing meets the proof standard, create no archive folder and say so.

### Phase 6 — Build and release truthfulness (6:00–6:30)

- Reconcile scripts, package manifests, and docs with the actual 16-step release flow.
- Verify version lockstep, quoting/path-with-spaces behavior, errorlevel propagation,
  sidecar staging, packaged self-tests, and promote-last semantics.
- Prove the last-good desktop/sidecar **pair** remains intact after every failed build;
  building a new sidecar directly into `local_build` before pair verification is not a
  transactional promotion.
- Ensure `--no-pause` automation actually exits instead of leaving an outer `cmd /k`.
- Reject stale executable discovery: a release must identify artifacts produced by the
  current invocation, not the first recursive filename match under an old target tree.
- Compare PyInstaller package/hidden-import declarations with live backend routes and
  imports. Report uncertain dynamic-import cases; do not “simplify” them casually.
- Inspect the frozen sidecar payload for `__pycache__`, `.pyc`, stale removed modules,
  source trees added as data, or archive content. In audit-only mode, compare with the
  recorded baseline and report existing debt; in authorized mode, package imports as
  code and include only genuine runtime data.
- Audit local build/self-test timeouts; an overnight gate must fail with diagnostics
  rather than wait forever, but Windows process-tree termination changes require tests.
- Compare documented Node/Python/Rust requirements with the locked toolchain's actual
  minimums. Correct proven documentation drift; do not add pins or change supported
  versions without explicit approval.
- Run `npm run build` after frontend/build-config changes.
- Any change to `release.bat`, sidecar packaging, Tauri config, Cargo config, or
  PyInstaller inputs requires the final full packaged release gate.

No installer target change, signing change, dependency upgrade, or release publication.
In audit-only build mode, the bullets above produce evidence and recommendations; source
changes are limited to truthful docs, assertions, and pure helpers that do not alter
artifact selection, membership, staging, promotion, or installer behavior.

### Phase 7 — Final verification and morning report
(`IMPLEMENTATION_CUTOFF_AT`–`HARD_STOP_AT`)

This is a hard implementation cutoff. Begin no later than 6:30 and earlier when required
by `FINAL_RESERVE`. Use this window only for gates, packaged-artifact inspection,
adversarial review, fixes to confirmed review blockers, and the report.

1. Run `git diff --check` and inspect every staged diff.
2. Run the complete gate set from Section 3.3.
3. Run `npm run build`.
4. Run the full release and verify both packaged self-tests plus promotion of the
   verified desktop/sidecar pair. Until the public wrapper is proven to exit, automation
   may call `scripts\release.bat __INNER__ --no-pause`; the current public
   `scripts\release.bat --no-pause` path opens `cmd /k` and may retain the shell.
5. Inspect the staged sidecar with the installed PyInstaller archive viewer and record
   executable SHA-256 hashes. In audit-only mode, reject archive content or entries newly
   introduced relative to the baseline, but report pre-existing source/bytecode/cache
   debt without failing the gate. When packaging membership is explicitly authorized,
   enforce the new payload assertion and require those entries to be eliminated.
6. Re-run any performance probe only if its writer/critical loop changed.
7. Synchronize test counts and relevant architecture/development docs.
8. Obtain an independent adversarial review of the full branch diff.
9. Fix only confirmed review blockers, re-run affected gates, and commit.
10. Produce `docs/reviews/<RUN_ID>-overnight-hardening-report.md`.
11. Leave the experimental worktree clean, branch local, and unpushed.

---

## 7. TDD, review, and commit discipline

For every accepted change:

1. Record the evidence and expected behavior in the ledger.
2. Add a regression/characterization test and observe the intended failure where a
   behavior bug exists.
3. Make the smallest coherent change.
4. Run focused tests, then the affected language suite.
5. Review cancellation, errors, user data, protocol, packaging, and docs implications.
6. Ask an independent reviewer to challenge the diff.
7. Stage named files only; run staged diff and whitespace checks.
8. Commit one concern with `<Area>: <present-tense action>` under 72 characters.

Do not mix behavior fixes, refactors, comments, archive moves, and report bookkeeping
in one commit. Run all three language suites after at most three commits and after any
cross-layer change. Never amend, squash, reset, or bypass hooks during the experiment.

Suggested commit shapes (only when evidence supports them):

- `Common I/O: Reject <reproduced invalid input> before parsing`
- `RefDes: Preserve cancellation through <specific phase>`
- `Frontend: Extract <specific duplicated lifecycle policy>`
- `Build: Align release checks and packaging documentation`
- `Docs: Mark <specific invariant> at both coupled definitions`
- `Archive: Quarantine proven-unreferenced legacy handoff material`
- `Review: Record overnight hardening evidence and gates`

---

## 8. Stop/skip conditions

Stop the whole run if:

- the supplied baseline SHA or release evidence does not match;
- the `READY FOR GOAL` marker is missing/stale or another writer appears;
- the canonical worktree would need mutation;
- a credential, network fetch, dependency install, or destructive operation is needed;
- full suites reveal an unexplained baseline regression;
- a required final gate fails or times out without a verified resolution;
- the machine, Codex app, repository, or experimental worktree becomes unavailable;
- a candidate boundary cannot be restored cleanly or an owned process tree cannot be
  stopped without risking unrelated processes; or
- the branch cannot be left clean and independently reviewable.

Skip a candidate and record it if:

- intentional behavior is ambiguous;
- proof depends on production data unavailable in the repo;
- it overlaps an active-plan quarantine;
- it changes protocol/process/concurrency/installer semantics without explicit authority;
- it cannot be protected by a meaningful regression test;
- it needs optional user approval during the unattended window;
- its bounded command times out but the clean candidate boundary is safely restored;
- it expands beyond the change budget; or
- two independent searches do not support a dead-code claim.

If one lane blocks, preserve its evidence and move to an independent lower-risk lane.
Do not spend the night repeatedly forcing one uncertain change through.

Apply the anti-stall contract in Section 5.1 before deciding that the whole goal is
blocked. A candidate skip must not be mislabeled as a global stop.

“Clean experimental tree” means Git-clean: no tracked modifications and no non-ignored
untracked files. Ignored build/test artifacts may remain in the disposable worktree;
list them in the report and do not delete them without separate authorization.

---

## 9. Morning report contract

The final report must contain:

1. **Verdict:** ready / ready with exclusions / reject.
2. **Isolation proof:** baseline SHA, branch, worktree, final SHA, canonical tree status,
   and confirmation that nothing was pushed.
3. **Commit table:** hash, purpose, risk, files, tests, and whether it is independently
   cherry-pickable.
4. **Confirmed bugs fixed:** exact trigger, prior outcome, new outcome, regression test.
5. **Refactors/comments:** why each change improves future edit safety.
6. **Archive inventory:** manifest rows, proof, restore path, and package exclusion.
7. **Rejected/suspected work:** what was deliberately not changed and why.
8. **Gates:** exact command, result, count, duration, and release-log path.
9. **Metrics:** tests before/after, files moved, source lines changed, and build size/time
   where available. Metrics are descriptive, not targets.
10. **Integration choices:** accept all, cherry-pick named commits, or reject the branch,
    including dependencies between commits and expected conflict areas.
11. **Residual risks:** anything not testable or not run.
12. **Anti-stall record:** `READY FOR GOAL` time, implementation cutoff, ledger heartbeat
    gaps, timed-out commands, skipped candidates, and any global-stop notification.

Do not claim “all tech debt fixed.” State exactly what was examined.

---

## 10. Preliminary leads from plan drafting (not authorization to fix)

These are starting points only; re-verify against the final baseline:

- `frontend/vite.config.ts` says `version:check` is not wired into `release.bat`, while
  the current release script runs it at step 2. This is a confirmed stale comment.
- The directory tree in `docs/ARCHITECTURE.md` calls `release.bat` a 12-step pipeline,
  while the current script and later docs describe 16 steps.
- `HANDOFF_2026-06-25.md` has no discovered references and carries obsolete suite
  counts, making it an archive candidate—not yet proven safe to move.
- `src-tauri/src/lib.rs` has an `#[allow(dead_code)]` Job Object field whose comment
  explains RAII process-tree ownership. It is an example of code that must **not** be
  classified dead from a compiler suppression alone.
- Existing TODOs for dropped-file support and future FMEA UI work describe features;
  they are out of scope, not overnight cleanup tasks.
- Broad Python catches exist in both intentional last-resort paths and run paths; audit
  cancellation ordering individually rather than replacing catches mechanically.
- Generated targets/caches are ignored and not tracked. Do not move them into `_archive`.

### Evidence-backed candidate queue

Re-check line numbers and behavior at the final baseline; work in this order only when
the candidate is outside the active-change quarantine:

1. **Selected-sheet fail-closed behavior.** Sidecar inspection has been observed to
   fall back to the first worksheet when an explicitly requested sheet disappeared,
   while runtime reads reject it. Add a red regression and make both paths agree.
2. **Picker/reader lockstep.** The native picker advertises legacy `.xls`, while the
   packaged readers are openpyxl-based and no `xlrd` dependency is shipped. Test the
   coupling and report the product choice; do not add `xlrd` overnight.
3. **Bounded preview reads.** `shared/output_preview.py` claims non-blocking behavior
   but can perform a full table read, and execute-time validation can repeat preview
   work before ack. Characterize read counts and preview limits before changing it.
4. **Rust timeout boundary.** File-command handlers have performed `canonicalize()`
   before entering the bounded sidecar request. A stale UNC/share can therefore block
   outside the timeout. Audit/report only overnight: moving canonicalization can change
   path and security semantics even if a pure lexical helper is unit-testable.
5. **Frontend browse failures.** Several native-dialog calls occur before the common
   inspection `try` block, so plugin rejection may skip the usual toast/state reset.
   Pin dialog rejection and stale-completion behavior before consolidation.
6. **OneDrive cancellation.** Hydration uses real reads, `attrib`, and non-interruptible
   backoff sleeps. Narrow cancellation improvements are candidates; automatic unpinning
   or a new hydration policy is report-only.
7. **Output transaction duplication.** Temp write → verify → cancel → promote → cleanup
   is repeated across runtimes. Characterize each variant and migrate at most one tool
   per commit; do not hide tool-specific cancellation or workbook ownership.
8. **Build pair promotion.** `build_sidecar.py` writes a new sidecar into
   `local_build` before the desktop/backend pair passes packaged self-tests. Design a
   unique staging directory and pair-level promote-last contract with failure tests;
   implement only when the handoff explicitly enables the build lane.
9. **Frozen payload hygiene.** Entire Python package directories are added as data, so
   ignored stale bytecode can enter the executable. Capture and report the baseline
   inventory immediately. Add a gating frozen-payload assertion or change packaging
   inputs only when the handoff explicitly enables the build lane and imports are proven
   complete; otherwise fail only on new payload regressions or archive inclusion.
10. **Build runner quoting.** `tauri-runner.mjs` and `cargo-runner.mjs` duplicate MSVC
    discovery and build a `cmd.exe` command string. Extract pure resolution/argument
    functions only if paths-with-spaces tests preserve current x64 behavior; ARM64
    toolchain changes are report-only without an ARM host.
11. **Log-level parsing.** The known out-of-scope ledger notes that a leading
    `WARNING:` is classified as INFO because only embedded `" WARNING:"` matches.
    Address separately with a protocol-level regression if it remains open.
12. **Comment truthfulness.** Additional stale claims include output preview doing no
    blocking I/O, old Flet ownership language, incorrect output-directory status, and
    verification-order prose. Correct only statements disproven by current code.
13. **Archive candidate.** `HANDOFF_2026-06-25.md` is a strong historical candidate.
    `frontend/public/examples/README.md` has conflicting signals (placeholder contract
    versus apparently unused copied asset), so keep it unless intent is resolved.

Do not attempt broad RefDes private-helper untangling, PyMuPDF zombie-thread redesign,
automatic OneDrive unpinning, immutable snapshots across every tool, or frontend tool
catalog/run-lifecycle restructuring during an unsupervised run. Characterize and report
those opportunities instead.

---

## 11. Two-stage launch templates

### Stage A — supervised preflight (user remains available)

Send this as a normal message, not as the overnight Goal:

> Prepare the overnight hardening experiment from
> `docs/plans/2026-07-14-overnight-hardening-experiment.md`. Baseline is `<SHA>`; the
> full release is green at `<ABSOLUTE_RELEASE_LOG_PATH>`; build authority is
> `<AUDIT_ONLY | EXPLICITLY_AUTHORIZED>`; final reviewer/Fable addendum is
> `<PASTE_ADDENDUM_OR_NONE>`. Perform Sections 3.1–3.5 only in the brand-new
> `<FRESH_EMPTY_WORKTREE_PATH>` worktree on branch
> `codex/overnight-hardening-<RUN_ID>`, using run ID `<RUN_ID>`. If any angle-bracket
> placeholder in this message remains unresolved, make no mutation and list every one.
> Otherwise verify isolated
> dependencies, every baseline gate, command permissions, measured durations, payload
> inventory, quarantine, and sole-writer state. Do not edit tracked files or begin
> implementation. Return the absolute external receipt path, complete green launch
> receipt, `FINAL_RESERVE`, `IMPLEMENTATION_WINDOW`, and a fully populated Stage-B Goal
> prompt. If any launch condition fails, report it immediately instead of repairing or
> waiting silently.

### Stage B — overnight Goal (only after a green launch receipt)

Replace every placeholder, then paste this into Codex:

```text
/goal

Execute the approved Overnight Hardening Experiment for Reliability Tools Desktop.
Do not write another plan, stop after summarizing the plan, or treat completion of one
response or one lane as completion of this Goal.

Authoritative inputs:
- Plan: <ABSOLUTE_EXPERIMENTAL_WORKTREE>\docs\plans\2026-07-14-overnight-hardening-experiment.md
- Baseline: <BASELINE_SHA>
- Green release log: <ABSOLUTE_RELEASE_LOG_PATH>
- Canonical checkout, read-only: C:\Reliability_Eng_Tools
- Experimental worktree: <ABSOLUTE_EXPERIMENTAL_WORKTREE>
- Branch: <EXPERIMENTAL_BRANCH>
- Run ID / green launch receipt: <RUN_ID>
- External launch-receipt path: <ABSOLUTE_C_TMP_RECEIPT_PATH>
- Build-lane authority: <AUDIT_ONLY | EXPLICITLY_AUTHORIZED>
- Active quarantine/exclusions: <LIST_OR_NONE>
- Final reviewer/Fable addendum: <PASTE_ADDENDUM_OR_NONE>
- FINAL_RESERVE: <DURATION>
- IMPLEMENTATION_WINDOW: <DURATION>

If any angle-bracket placeholder anywhere in this Goal remains unresolved, make no
mutation and report every unresolved token. Otherwise verify the exact external receipt,
its age, every receipt field, and that no concurrent writer appeared. If it expired or
anything drifted, make no tracked edit: stop within 10 minutes with the exact mismatch.

When the receipt is valid, record GOAL_START now, calculate HARD_STOP_AT = GOAL_START +
8 hours and IMPLEMENTATION_CUTOFF_AT = GOAL_START + IMPLEMENTATION_WINDOW, and append all
three times to the external watchdog. Then create the tracked ledger from the receipt and
begin the first eligible candidate immediately. The eight-hour clock starts at GOAL_START.

Outcome: leave a clean, local, unpushed experimental branch containing only
high-confidence, evidence-backed hardening allowed by the plan, with one single-purpose
commit per accepted task, complete verification evidence, and a self-contained morning
report that makes accepting all, some, or none of the commits straightforward. Zero
implementation commits is acceptable only with a complete evidence ledger and report.

Follow the plan's phase order, evidence rubric, change tiers, quarantine, TDD,
characterization, review, commit, archive, safety, and reporting rules exactly. Be the
sole writer. Subagents may perform read-only audits, run non-mutating checks, or review
diffs; they may not edit, format, generate, stage, or commit in this worktree. Do not
push, fetch, pull, publish, install/update dependencies, contact the network, modify the
canonical checkout, use destructive Git operations, add features, change intentional
behavior, weaken a gate, or exceed build-lane authority.

Maintain a watchdog entry at least every 30 minutes and after every commit, timeout,
lane change, or stop condition. Record the candidate, last completed action, last
commit, active bounded command/deadline, elapsed time, and next fallback. Poll long
commands so no wait hides progress for more than 60 seconds. Apply the finite deadlines
and proven process-tree cleanup in Section 5.1.

A candidate problem is not a blocked Goal. Record and skip a candidate when behavior is
ambiguous, production data is unavailable, it overlaps quarantine, it lacks a safe test
seam, it exceeds Tier/build authority, it needs optional approval, it times out safely,
or evidence is insufficient. Move immediately to the next independent lane. Never wait
for sleeping-user approval and never invent churn merely to create commits.

Stop the whole Goal only for a Section-8 global condition: baseline/receipt drift,
loss of isolation or sole-writer state, an unexplained required-gate failure, required
credential/network/dependency/destructive authority, unavailable machine/app/workspace,
or inability to leave a clean reviewable branch. On global stop, preserve safe evidence
and take the minimum-report path immediately; do not end silently.

At IMPLEMENTATION_CUTOFF_AT, begin no new candidate. Use FINAL_RESERVE only for the full
required gates, packaged-artifact and payload inspection, independent adversarial review,
confirmed blocker fixes, documentation/count synchronization, and the report. Stop at
HARD_STOP_AT with the truthful state recorded. Leave:
- docs/reviews/<RUN_ID>-overnight-ledger.md
- docs/reviews/<RUN_ID>-overnight-hardening-report.md

The Goal is complete only when the plan's required final gates are green, both documents
are complete, the experimental tree is clean and independently reviewable, the canonical
checkout is untouched, and nothing was pushed; or when a genuine global stop has produced
a concrete stop report and the safest reviewable state possible. Report the verdict as
ready, ready with exclusions, or reject. Never claim success with a skipped, timed-out,
or red required gate.
```

Stage B starts the Goal; it does not waive any safety, scope, test, archive, quarantine,
or stop condition. If the receipt changed, return to Stage A rather than improvising.
