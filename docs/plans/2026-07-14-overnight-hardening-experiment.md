# Overnight Hardening Experiment

**Status:** DRAFT — write the plan now; do not execute it until the user supplies
the final baseline commit after a clean release build.

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
- No dependency upgrades, lockfile refreshes, new linters, or downloaded audit tools.
- No protocol/schema/event-order changes.
- No version bump or release publication.
- No performance rewrite without a reproduced performance defect and baseline.
- No blanket formatter, import sorter, mass rename, or repository-wide comment churn.
- No removal based only on a filename, age, TODO, warning suppression, or one static
  search result.
- No push, PR, merge to `main`, force operation, destructive reset, or history rewrite.
- No changes to user-owned workbooks, examples, local logs, build outputs, credentials,
  or untracked files.

---

## 3. Isolation and start protocol (blocking)

### 3.1 Required handoff from the user

Do not begin implementation until the user provides:

- the exact baseline commit SHA;
- confirmation that `scripts\release.bat --no-pause` succeeded at that SHA;
- permission to create the experimental branch/worktree; and
- any files or active plans that must be quarantined from the experiment.

Record the SHA and release-log path in the morning report before editing.

### 3.2 Worktree model

Use a fresh worktree, not the canonical repo and not an old development copy:

- Canonical/review repo: `C:\Reliability_Eng_Tools` — read-only during the run.
- Experimental worktree: `C:\Reliability_Eng_Tools_Overnight` (or another empty,
  user-approved path).
- Branch: `codex/overnight-hardening-<YYYYMMDD>`.

At plan-writing time, `C:\Reliability_Eng_Tools_Dev` has unrelated history and
user-owned untracked files. Never reuse, clean, reset, move, or delete that workspace.
Re-check this fact at execution time rather than assuming it remains true.

Create the worktree from the user-supplied local SHA. Do not fetch, pull, or contact
the network unless the user explicitly asks.

### 3.3 Preflight

Before any edit:

1. Verify the canonical worktree is clean and its `HEAD` equals the supplied SHA.
2. Verify the experimental destination does not already exist.
3. Create the `codex/` branch and worktree from that SHA.
4. Verify the experimental tree is clean and has the same SHA.
5. Record `git status`, `git log -1`, suite counts, Node/Python/Rust versions, and the
   release-log location in `docs/reviews/<RUN_ID>-overnight-ledger.md`.
6. Run the baseline gates in the new worktree:

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
npm ls --depth=0
.venv\Scripts\python.exe -m pip check
npm run tauri:readiness
npm run version:check
npm run typecheck
npm run typecheck:tests
npm run cargo:check
npm run cargo:test
.venv\Scripts\python.exe -m pytest backend\tests -q -p no:cacheprovider
npm test
.venv\Scripts\python.exe backend\python\sidecar_main.py --self-test
```

If the baseline is not clean and green, stop before editing and report the mismatch.
Do not repair an unexplained baseline failure as part of this experiment.

### 3.4 Active-change quarantine

At start, re-read every active plan and list files named by unchecked tasks. Do not
touch those files overnight; log observations instead. While Tasks 4.4–4.7 in
`docs/plans/2026-07-13-external-review-remediation.md` remain open, quarantine their
FMEA analyzer/writer/runtime, FMEA frontend, test, naming, and help/documentation
surfaces. This avoids producing a branch that is technically good but painful to
integrate with the active remediation work.

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
- Removing a proven-unused dependency is allowed only in its own lockfile-aware commit
  after static references, dynamic registration, build output, and full suites agree.
  Adding or upgrading a dependency remains out of scope.
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
| C — protocol, process lifetime, concurrency semantics, installer behavior, user-data migration, active Wave-4 area | Audit and report only unless the user explicitly expands authority before sleeping. |

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
6. Truthful invariant comments and maintainer documentation.
7. Cosmetic cleanup.

“Looks old” and “an LLM says unused” are not evidence.

---

## 6. Eight-hour work sequence

### Phase 0 — Baseline and conflict map (0:00–0:40)

- Complete Section 3.
- Map current entry points, registries, dynamic imports, Tauri command registration,
  sidecar routes, PyInstaller hidden imports/data, test globs, and package roots.
- Build the active-change quarantine list.
- Create the evidence ledger; make no source edits.

### Phase 1 — Mechanical audit and triage (0:40–1:40)

Use existing tools only (`rg`, `git`, compilers, and test runners). Inventory:

- `TODO`, `FIXME`, `HACK`, `XXX`, suppressions, and stale comments;
- broad Python exception handlers and cancellation ordering;
- direct Excel/CSV/PDF/file reads and writes that bypass shared helpers;
- repeated normalization, error-description, run-state, and output-path logic;
- frontend `invoke`/`listen`/store ownership and stale async continuations;
- Rust lock scopes, detached tasks, error conversions, and platform gates;
- build-script/documentation/version/PyInstaller coupling;
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

### Phase 3 — Exception, cancellation, and modularity audit (3:20–4:50)

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

### Phase 4 — Comments and future-LLM guardrails (4:50–5:45)

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

### Phase 5 — Dead-code proof and reversible archive (5:45–6:35)

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
- baseline SHA and move commit;
- restoration command; and
- any residual uncertainty.

The archive must remain outside `backend/python`, `backend/tests`, `frontend`,
`src-tauri`, `scripts`, and `contracts`. Confirm all current scanners/package roots
exclude `_archive`; add an explicit exclusion only if a real global scan requires it.
Append `.archived` to executable source, test, script, and package/config suffixes so a
future broad scanner cannot accidentally import or run the payload. Never place an
`__init__.py`, `package.json`, `Cargo.toml`, or executable launcher in the archive.
Verify the hash again on restore.

A tracked archive is still visible to Git hosting, code indexers, and repository-level
secret scanners. Therefore it may never contain credentials, user data, logs, workbook
samples, or anything that was unsafe to commit at its original path.
Ignored build products, caches, coverage, logs, and user-local files are not archive
material and must not be committed.

If nothing meets the proof standard, create no archive folder and say so.

### Phase 6 — Build and release truthfulness (6:35–7:10)

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
  source trees added as data, or archive content. Package imports as code and include
  only genuine runtime data.
- Audit local build/self-test timeouts; an overnight gate must fail with diagnostics
  rather than wait forever, but Windows process-tree termination changes require tests.
- Compare documented Node/Python/Rust requirements with the locked toolchain's actual
  minimums. Correct proven documentation drift; do not add pins or change supported
  versions without explicit approval.
- Run `npm run build` after frontend/build-config changes.
- Any change to `release.bat`, sidecar packaging, Tauri config, Cargo config, or
  PyInstaller inputs requires the final full packaged release gate.

No installer target change, signing change, dependency upgrade, or release publication.

### Phase 7 — Final verification and morning report (7:10–8:00)

1. Run `git diff --check` and inspect every staged diff.
2. Run the complete gate set from Section 3.3.
3. Run `npm run build`.
4. Run the full release and verify both packaged self-tests plus promotion of the
   verified desktop/sidecar pair. Until the public wrapper is proven to exit, automation
   may call `scripts\release.bat __INNER__ --no-pause`; the current public
   `scripts\release.bat --no-pause` path opens `cmd /k` and may retain the shell.
5. Inspect the staged sidecar with the installed PyInstaller archive viewer. Reject
   unexpected source/bytecode/cache/archive entries and record executable SHA-256 hashes.
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
- the canonical worktree would need mutation;
- a credential, network fetch, dependency install, or destructive operation is needed;
- full suites reveal an unexplained baseline regression;
- the branch cannot be left clean and independently reviewable.

Skip a candidate and record it if:

- intentional behavior is ambiguous;
- proof depends on production data unavailable in the repo;
- it overlaps an active-plan quarantine;
- it changes protocol/process/concurrency/installer semantics without explicit authority;
- it cannot be protected by a meaningful regression test;
- it expands beyond the change budget; or
- two independent searches do not support a dead-code claim.

If one lane blocks, preserve its evidence and move to an independent lower-risk lane.
Do not spend the night repeatedly forcing one uncertain change through.

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

---

## 11. Future execution authorization template

The user can start the experiment with:

> Baseline is `<SHA>` and `scripts\release.bat --no-pause` is green. Execute
> `docs/plans/2026-07-14-overnight-hardening-experiment.md` in a fresh
> `codex/overnight-hardening-<date>` worktree for up to 8 hours. Respect the active-plan
> quarantine, commit each accepted task separately, do not push, and stop with the full
> morning report and clean experimental tree.

That authorization starts the plan; it does not waive any safety, scope, test, archive,
or stop condition above.
