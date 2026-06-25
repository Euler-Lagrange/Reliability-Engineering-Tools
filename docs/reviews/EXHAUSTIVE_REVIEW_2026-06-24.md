# Reliability Tools Desktop — Final Verified Review (2026-06-24, v0.4.6 @ 9cab706)

## Bottom line

All 12 review dimensions are now swept and **every finding has been adversarially verified** (two independent skeptic lenses per finding — a line-by-line code trace and a real-world-scenario attempt-to-refute). The verification workflow completed in full this time: 33 agents, no spend-limit cutoff. Several of the data-correctness findings were **empirically reproduced** in your actual venv, not just argued.

**Headline:** the app is sound, but it has a cluster of *silent data-correctness* bugs in the number-producing paths (Failure Rate, BOM Compare, FMEA) that can ship wrong numbers in a deliverable with no error — and a cluster of *lost-feedback* bugs where a successful run gives you no confirmation. These are exactly the "looks fine, is subtly wrong" failures that matter most for reliability work.

**Two corrections to my earlier (June 10) report — I was wrong on these, the verification caught it:**

1. **The run-start "ack race" (was my Tier 1 #1) is NOT a live bug.** My earlier inline trace was incomplete — I missed that the Rust bridge resolves the `executeRun` promise (which stores the run ID) *before* it emits any worker event, so the await-continuation that stores the ID is already queued ahead of any event that could be dropped. The drop *mechanism* (no event buffer) is real, but no realistic path fires it. Downgraded to latent hardening. I'd rather tell you this than leave a phantom bug at the top of the list.
2. **"A failed finalize DELETES your finished workbook" was overstated.** `os.replace` is atomic, so a *pre-existing* file at the target is never destroyed. What actually happens: on a finalize failure (target locked open in Excel mid-save), the freshly-computed, verified-good `.part` output is unlinked instead of being kept for rescue — so a long FMEA run can end with an error and no file, forcing a full re-run. Real, worth fixing, but it's *lost compute*, not *destroyed prior deliverable*. Reframed and downgraded to Tier 2.

Counts: **48 findings verified → 41 confirmed, 1 refuted, 5 split-latent (real code, no real-world trigger today), plus the 1 downgrade above.** Coverage caveat at the bottom: 8 subsystems were never opened and are listed honestly.

---

## TIER 1 — Wrong numbers in a deliverable (fix first; all confirmed, most empirically reproduced)

These can silently corrupt the numeric output you hand off. This is the tier that matters for your engineering deliverables.

**1. Part-Usage `=1/N` formula cells silently become 1.0 → Mode_FR overstated up to 250× (Failure Rate)** · `common/validation_utils.py:387-388`, `failure_rate/failure_rate_logic.py:276-279`
A usage cell holding a formula (`=1/4`) with no cached value reads as NaN, then defaults to `1.0`. In Failure Rate it flows straight into `Mode_FR = part_fr × usage × ratio` and into the output column. *Reproduced: a 1/250 part reads as 1.0 → 250× overstatement.* Excel-saved files cache the computed value and are safe; the trigger is usage cells written by a script/PLM/openpyxl export (or a file that skipped recalc-on-save). In FMEA and BOM Compare the same coercion is **completely silent** (no note at all).

**2. Failure Rate Linker has no circuit-block filtering → Function_FR double-counts (Failure Rate)** · `failure_rate/failure_rate_logic.py:242, 337-340`
Feeding a generated FMEA back into the linker (the documented workflow): each circuit-block aggregate row carries a comma-separated RefDes list; the linker grabs the *first* RefDes, assigns it the full part failure rate, then sums it into `Function_FR` on top of that part's real piece-part rows. *Reproduced: 4.700e-6 vs correct 3.700e-6 — a 27% inflation.* BOM Compare already excludes circuit-block rows here; Failure Rate has no equivalent guard.

**3. Unparseable prediction FR cell → silent 0.0, reported as a successful link (Failure Rate)** · `failure_rate/failure_rate_logic.py:159`
The prediction FR column is `pd.to_numeric(..., errors='coerce').fillna(0.0)`. A FR cell that's `TBD`, `1.2 FIT`, or a formula string becomes `0.0`, and because the RefDes *is* present, it's counted as a successful link (`linked_count += 1`) — no "not in prediction" note. The part silently contributes `Mode_FR = 0`, understating the rolled-up rate, and is indistinguishable from a real 0.0. (Usage/ratio defaults *do* warn here; FR does not — a telling asymmetry.)

**4. BOM load failure silently downgrades the whole extraction to "no BOM" (RefDes Extractor)** · `refdes_extractor/runtime.py:357-359`
When you supply a BOM for cross-check and it fails to load (wrong sheet, locked file, missing RefDes column), the error is caught as a warning and `bom_set` is emptied. Extraction then runs and labels **every** component "UNGROUPED (NOT IN BOM)" — a full report that looks done but says everything is missing, with only one easy-to-miss log line. The run reports success.

**5. Custom BOM Compare always reports "0 differences" — the column-value diff is unreachable** · `bom_compare/runtime.py:514-543`, `bom_compare/custom_compare.py:702`, `BomCompareTool.tsx:126-138`
The backend reads `compare_columns`/`key_mode`/`display_names`, but no frontend control or contract ever sends them (the options UI is six checkboxes). So the entire per-column value-diff loop is skipped and the summary always says "0 differences," regardless of changed part numbers/descriptions on matched RefDes. The RefDes presence/absence diff *does* still work, so it's not a total no-op — but an engineer comparing revisions reads "0 differences" as "identical" and ships a silently-changed MPN. (Violates your Wiring Invariant #1.)

**6. NaN / non-numeric Ratio silently passes the FMR-sum check (BOM Compare)** · `bom_compare/group_analysis.py:495-499`, `custom_compare.py:915-919`
A blank or text ratio cell becomes NaN/0.0; `abs(nan - 1.0) > tolerance` is `False`, so a RefDes whose ratios don't actually sum to 1.0 is silently dropped from the "Failure Mode Ratio Errors" sheet (or the row gets a wrong sum with no diagnostic). Confirmed at 2 sites; the Failure Rate path is immune (it converts NaN→1.0 before summing).

**7. `fill_gaps` gives wrong "1/N" usage guidance from an empty variant map (FMEA)** · `fmea/fmea_generator_logic.py:689-691 (stale comment), 2103-2105`
A code comment claims the inheritance path is unreachable; it isn't. Run Fill Gaps with an old FMEA listing a variant (e.g. `U200-1`, base `U200` in BOM) and no grouping file → the "New RefDes" sheet advises usage `1/1` when the part actually has N instances. The paste-back guidance you'd copy into the BOM is wrong.

**8. Multi-RefDes cause cells lose every RefDes after the first (Failure Rate)** · `failure_rate/failure_rate_logic.py:242`
A cause cell listing `U1, U2, U3` links only `U1`; `U2`/`U3` get no failure rate and no warning — silent under-count. The tool is architected one-RefDes-per-row, so this only bites hand-authored/legacy FMEAs with multi-RefDes cells, but when it does it's silent.

**9. Loose base-match has no residual-digit guard in 3 of 4 directions → `R1` "covers" `R12` (BOM Compare)** · `group_analysis.py:317`, `custom_compare.py:621`
Only `_find_missing_in_bom` guards `c[len(base):].isdigit()`; the other three directions don't, so `R1` and `R12` falsely cover each other and a genuinely missing/extra part escapes the discrepancy report. **Only active when you enable the "base match" checkbox** (defaults off), which limits exposure.

---

## TIER 2 — Lost feedback or stuck UI (confirmed; no wrong numbers, but real run-integrity failures)

**10. Every successful desktop run silently loses its success toast + "saved to…" message** · `useDesktopRunController.ts:208-226`
The sidecar emits `status:success` then `result` as two separate events. The terminal handler marks the run "handled" on the first one — when `result` is still null — so the success branch (toast + shell "Generated workbook at…" message) never fires. The Run panel still shows the result, so it's silent UX loss, not a hang — but it happens on *every* successful run. (High frequency; the tests jump straight to `result` and never replay the real two-event ordering, so it's uncaught.)

**11. Cancel-after-finish strands the UI in a permanent "Cancelling…"** · `runLifecycle.ts:116-130`, `runStore.ts:67-70`, `sidecar_main.py:393-425`
If you hit Cancel in the narrow window between a run's `result` and its cleanup, the sidecar emits a late `cancelling` status that overwrites the terminal `success` phase — and the apply path has no terminal guard (unlike `markDisconnected`, which does). The UI sticks on "Cancelling…" forever, busy chip never clears, result lost. Narrow timing window, but a hard stuck state when hit.

**12. New toasts self-evict once 5 sticky error toasts are pinned** · `notificationStore.ts:71-89`
Error toasts never auto-dismiss. With 5 on screen, the eviction candidate list *includes the incoming toast*, so each new success/info/warning deletes itself on arrival — including the keep-alive completion toast. *Reproduced.* Among errors the FIFO is correct; the defect is specifically non-error toasts vanishing.

**13. A stray non-JSON line on the sidecar's stdout kills a healthy in-flight run** · `lib.rs:636-648`
The Rust stdout reader treats *any* unparseable line as a fatal session error (kills the child, fails all pending) with no NDJSON resync. Python never guards fd 1, so a single stray write from a C extension (MuPDF/openpyxl) on a malformed input would tear down a perfectly healthy run as a generic "invalid JSON" disconnect. (Note the asymmetry: the Python command loop *does* skip-and-continue on a bad inbound line; Rust does the opposite.)

**14. A hung Python import freezes the connect step forever (no readiness timeout)** · `lib.rs:974-993`
`spawn_managed_sidecar` blocks in an unbounded `read_line` waiting for `ready`, *before* the heartbeat supervisor starts. A cold-disk `import fitz` or an AV scan stalling the PyInstaller bootloader → the triggering command (the bootstrap health check) hangs silently with no watchdog active. Distinct from the known recv()-deadline hang.

**15. A dead UNC/network path freezes the whole backend invisibly** · `sidecar_main.py:654-668`, `lib.rs:503`
Non-execute commands run inline on the single stdin thread; a stale `\\server\share` blocks the OS file check 30–120 s, queuing *everything* (including cancel). Rust `recv()` has no deadline, and the heartbeat keeps flowing from its own thread, so the 15-s watchdog never fires. App looks dead, zero feedback. Self-recovers on OS timeout.

**16. Switching workflow/output-strategy mid-run orphans the backend job** · `FmeaTool.tsx:503, 526`, `BomCompareTool.tsx:286`
The WorkflowSelector/StrategySelector are never disabled during a run, and their change effects call the *unguarded* `resetSession` (not `resetSessionUnlessLive`). A mid-run switch wipes the live run from the store; subsequent events are dropped, the terminal toast never fires, the workbook is written by the orphan, the UI shows idle, and the next run is blocked until the orphan finishes.

**17. File-inspection busy chip is instantly wiped by a lingering completed run** · `useBackendBusyReset.ts:54-62`
After a run finishes, its terminal phase lingers in the store. Browsing a new file or changing a sheet flips the chip to "busy: Inspecting…", which re-runs the reset hook — it sees (terminal phase + busy) and clears the chip immediately. You get a blank/stale status for the whole inspect window. (Cross-tool variant — tool A's finished run wipes tool B's inspect chip — is the same root cause, cosmetic.)

**18. FMEA preserve-formatting mode silently ignores the chosen Output Folder** · `fmea/runtime.py:943`, `fmea_template_writer.py:748-751`
In preserve mode the resolved output directory is overwritten with the *template's* parent folder, so the merged workbook lands next to the template regardless of the picker, with no warning. (Wiring Invariant #1; the new-workbook path honors it correctly.)

**19. `outputDirectory` is never validated at validate-time → output silently relocates** · `shared/pre_run_validation.py`, each runtime's `validate_run_request`
A bad/unwritable/disconnected output folder passes validation green, then `_resolve_output_directory` falls back to the input-file's folder with only a buried warning. You look in the folder you picked and the file isn't there. Compounds #18 for FMEA.

**20. Pinlist clustering failure silently drops pin qualification for a page** · `refdes_extractor/extraction_engine.py:1220-1222`
A per-page `qualify_pins_via_pinlist` failure is logged only to the rotating *file* log (`_logger.error`), not the streamed run log you see, and the page's qualified set is emptied. You supplied a pinlist to qualify pins; the output looks complete but silently has none for that page.

**21. Unguarded envelope Zod parse can strand a run on schema drift** · `client.ts:271-273`
The envelope-level `sidecarRunEventSchema.parse` runs at the top of the Tauri listener with no try/catch (unlike the guarded *inner* result parse). Not triggerable by today's shipping code (all emitted values are in-enum), but on any future schema skew — very plausible on your two-machine build setup where a newer sidecar outruns an older bundled frontend — a dropped terminal event strands the run in "running" forever. Robustness/forward-compat gap.

---

## TIER 3 — Engineering-practice gaps (you pre-authorized these; all verified)

**22. No `requirements.txt`** (verified inline — none exists). Python is the only unpinned layer; your venv already drifted to pandas 3.0 / Python 3.13 vs dev's 2.x/3.12, and release.bat bundles whatever's installed.
**23. No CI** (verified inline — no `.github/workflows`). A ~30-line windows-latest workflow (typecheck, vitest, pytest, audit, cargo check+test) catches your cross-machine drift on every push.
**24. release.bat self-destruct + ungated checks** · `scripts/release.bat:102` (verified): copies the new exe over `local_build` *before* the self-tests, so a failed release clobbers the last-good exe at the path teammates grab; `cargo:test` is never run in the gate (only `cargo:check`); `bump-version.mjs --check` is never called; **v0.4.6 was never tagged** (tags stop at v0.4.5 — verified).
**25. security_audit blind spots** · `common/security_audit.py:158` (verified): matches only `subprocess.run(...)`; `from subprocess import run`, `import subprocess as sp`, `os.system/popen/startfile`, ctypes, importlib all pass clean. Low real risk (in-house, air-gapped, documented as non-adversarial) but worth closing + softening CLAUDE.md's "enforced statically" wording.
**26. Banned error-message ternary reintroduced at exactly 7 folder/reveal sites** (verified): `FmeaTool.tsx:649,710`, `BomCompareTool.tsx:350`, `FailureRateTool.tsx:181`, `RefDesExtractorTool.tsx:188`, `SettingsTool.tsx:130`, `OutputFolderPicker.tsx:49`. The 5 `revealInFileManager` sites are the harmful ones — Tauri rejects with a raw string, so `instanceof Error` is false and the real "Path does not exist: C:\…" message is discarded for a generic toast. Fix: use `describeBackendError`. (Wiring Invariant #5.)
**27. Doc fixes** (verified inline): README's `pip install` line omits pyinstaller then points at the portable build that needs it (`README.md:40, 62`); `DEVELOPMENT.md:7` says Python 3.12 while nothing enforces it. Both fold into the requirements.txt change.
**28. Four cheap test gaps** (verified inline): FMEA execute payload keys are asserted nowhere frontend-side (`toolRunDispatch.test.tsx` covers BOM/FR/RefDes only — the `hdaSource` bug class could ship again); `App.test.tsx` never asserts the shell-level subscription/bootstrap hooks are installed (deleting either leaves the suite green); no registry-wide scenario-completeness test; a regression test for #10 (the success-toast race) rides along with that fix.

---

## TIER 4 — Low-severity / hardening (confirmed, low urgency)

`fio-triple-parse` input parsed up to 3× incl. one pre-ack blocking the command loop (`sidecar_main.py:552`) · `fio-orphan-temps` hard-kill leaves hidden `.part` clutter · `fio-attrib-pin` hydrated OneDrive files permanently pinned local (`utils.py:131`) · `fio-dead-code` the 260-char long-path guard + input-preflight helper are dead code, so the long-path protection never actually runs · `pd-checkfmr-key` FMR keys on the raw cell not `canonicalize_refdes` → false-positive FMR errors on PDF-pasted invisible chars · `proto-fmea-colsel` `columnSelection`/`dnp_regex` unreachable from UI (defaults are correct) · `proto-loglevel` leading-keyword `WARNING:`/`ERROR:` lines mis-colored as info in the log panel (`sidecar_main.py:322-330`) · `reveal-path-gate` no UNC/comma gate on reveal · `crash-retention` crash dumps never pruned · `pd-xls-import` picker offers `.xls` but xlrd isn't installed → clean dead-end · `new-frontend-state-1` previewStore never cleared on input change → Review drawer shows a stale preview · `new-frontend-state-2` `disconnected` phase in the terminal guard list has no branch (latent trap) · `new-lifecycle-races-2` cross-tool busy-chip clear (cosmetic) · `new-cancellation-1` broad `except Exception` swallows `CancellationError` in BOM part-usage classification (`group_analysis.py:595`; a downstream check saves it today, but it's the exact gotcha CLAUDE.md warns about) · `new-silent-failures-5` `list_sheets` returns `[]` on a file-access error with no log · `new-rust-bridge-3` command `timestamp` is a Rust Debug string, not ISO-8601 · `new-rust-bridge-4` interpreter/script resolution walks every ancestor to drive-root → can bind the wrong `.venv` (reinforces ask-D) · `new-rust-bridge-5` non-Windows sidecar orphan (Windows-targeted, dev-only) · `proto-role-field` `role` field on inspect/analyze read by nothing · `proto-stale-comment` stale "Phase 4 outputDirectory" comments.

---

## SPLIT / latent — real code, no real-world trigger today (no action urgent)

- **`proto-reqid-drop`** — error envelopes without a `request_id` are dropped by Rust, but the only producer is a malformed-frame defensive path the trusted bridge never hits.
- **`pd-xls-floats`** — xlrd would mint `"1234560.0"` from float cells, but xlrd isn't installed. *Flag for whoever fixes `pd-xls-import`: force integer/text coercion if you add xlrd.*
- **`proto-enrich-hardfail`** — legacy-enrichment hard-fail lives at execute not validate, but no shipped client sends `enrichments`.

## Refuted

- **`new-rust-bridge-2`** — the `\\?\` canonicalized path does *not* degrade OneDrive detection (the readability check short-circuits before the OneDrive branch). Dropped.

---

## Coverage boundary — 8 subsystems never opened (honest gaps; optional next sweep)

The completeness critic flagged these as un-reviewed. Two are **potential new data-correctness bugs worth a follow-up**:

1. **Excel-vs-CSV NA coercion divergence** (`utils.try_read_table`): the CSV branch passes `keep_default_na=False`; the Excel branch doesn't — so a cell with literal text `NA`/`N/A` becomes NaN *only* for `.xlsx`, and downstream `pd.notna()` guards silently drop those rows. ← worth checking.
2. **Duplicate header names**: `inspect_input` (openpyxl) doesn't dedupe, but the runtime's pandas `read_excel` auto-renames `Part Number` → `Part Number.1`, so a user override by name can bind the wrong column. ← worth checking.
3. Zustand persisted stores have no version/migrate (stale output dirs/theme ids rehydrate verbatim — overlaps ask-E).
4. RefDes NextGen engine (`nextgen_engine.py`) geometry/clustering math — never reviewed.
5. FMEA template analyzer merged-cell / multi-row header handling — never reviewed.
6. Frontend a11y / focus traps (CommandPalette, ContextDrawer, CustomSelect) — never reviewed.
7. Tauri capability schema diff — **I checked this: whitespace/CRLF only, no permission change. Clean.**
8. `CancellationToken.reset()` race with an in-flight `check()` from an orphaned thread (sits under the orphan-job findings).

---

## Verified clean (independent agents tried to break these and couldn't)

All six v0.4.6 fix claims true in code; production CSP tight; Tauri capability surface minimal and unchanged; Job Object spawn sequence exact; both NDJSON atomicity locks correct; `read_flet_config` namespace-allowlisted; output-path containment correct; `emit()` properly locked; `protocol_version` checked (warn-only); FMEA's own `parse_usage("=1/250")` returns `(None,None)` rather than defaulting (so the formula-cell bug is read-path specific). 1 of 48 findings refuted.

---

## Possibly-intentional — your call (still outstanding from June 10)

- **A.** OneDrive detection keys on the substring `"onedrive"` — keep the heuristic or tie it to the real env vars?
- **B.** Crash dumps are unredacted (can embed BOM/customer part data) and docs tell users to share the folder — acceptable or truncate/flag?
- **C.** `analyze_template` loads workbooks fully with no size cap — guard or leave?
- **D.** Sidecar resolution walks every ancestor dir (now reinforced by `new-rust-bridge-4`) — tighten to exe-adjacent in release builds, or keep the dev convenience?
- **E.** User prefs persist with no version/migration (reinforced by critic #3) — add a version field now or accept re-picking folders after a profile reset?

---

## Proposed execution order (pending your go-ahead — no code touched yet)

1. **Tier 1 data-correctness** (#1–#9), each with a regression test. These ship wrong numbers; they go first.
2. **Tier 2 run-integrity** (#10–#21) — start with #10 (every-run toast loss) and #16 (mid-run orphan) since they're highest-frequency.
3. **Tier 3 practices** (#22–#28) — the pre-authorized "just do it" batch; fold doc + test-count syncs into the same commits (Invariant #10).
4. **Tier 4** cherry-picks as cheap riders.
5. **Your A–E answers** decide which become fixes vs documented deferrals; optionally a quick follow-up sweep of critic items #1–#2 (the two possible new data bugs) before I call the audit closed.
