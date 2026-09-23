# Review: RefDes pin-label resolution plan

Reviewed 2026-09-16 against `a23fad1aa947b3091a89cc3c5b4d0a91f6ab8628`, the pasted review document, its local counterpart `docs/superpowers/specs/2026-09-16-refdes-pin-label-resolution-design.md`, and the supplied U2/AD4858 photograph. Ordinary `DIO-XXX` labels are assumed to be distinct numbered labels such as `DIO-054`, as requested. Repeated placeholder labels are therefore not a finding.

**Verdict: revise before implementation.** The shared resolver is a reasonable direction, and the component-first harvest diagnosis is correct. However, the plan relies on geometry properties that the current implementation does not have. Its proposed happy-path fixture, default adaptive behavior, and optional pinlist path need more than the listed changes.

This is a review of a proposal. The document's implementation, commit, and push instructions were not treated as authorization to execute them. No application code was changed.

## Findings

### 1. [P1] Preserve the central U2 RefDes before relying on body ownership

Plan: §2.3, §4.2, Increment 0 (lines 226–233).

`geometry_analyzer.py:1466` returns zero distance for every point inside a body, including its center. At `:1615`, a short RefDes such as `U2` that is also a pin candidate therefore becomes `PIN_LABEL`. Body ownership at `:2024` accepts only `REFDES` tokens.

**Verified probe:** an in-memory PDF with the planned 240 × 380 pt rectangle, centered `U2`, and C4/B7/E8 labels produced one detected body, `assigned_refdes=None`, and zero pin mappings. The body's center was reported as zero distance from its edge.

Add a production geometry prerequisite that distinguishes interior component identification from perimeter pin labels. Keep `U2` in the center in the acceptance fixture. Moving it outside the body, changing its text, or otherwise tuning the fixture to avoid this failure would stop testing the photograph's key condition. Test that `U2` remains both the body's owner and the intended ungrouped component.

### 2. [P1] Tier 1 is not tick-anchored and bypasses the proposed safeguards

Plan: §4.2 tier 1 (line 171), resistor protection rationale (line 179), P1/P10.

`process_page_geometry` synthesizes pins from text at `geometry_analyzer.py:808`. `_create_pins_from_tokens` at `:1784` does not apply the proposed passive-context or allowed-parent-prefix guards. Graphical tick constructors leave `label_token=None`; the label assignment at `:1813` occurs during token synthesis. Consequently, a mapping's existence is not proof of a detected, labeled graphical pin tick.

**Verified probe:** with no ticks, a body already identified as `U2`, a `C4` label 30 pt outside its edge, `0.1uF` 20 pt from that label, and numeric labels `1`/`2`, the geometry processor emitted `U2-C4`, `U2-1`, and `U2-2`. The planned first-successful-tier rule would accept these before checking any tier-2 protection.

Give mappings explicit evidence provenance. Apply the corresponding passive, parent-prefix, and group-ownership checks to token-derived mappings. If genuine tick evidence is meant to override weaker safeguards, implement and test actual tick-to-label association separately. Do not label all current mappings as stronger evidence than body proximity.

### 3. [P1] Resolve a specific text occurrence, not every matching string on a page

Plan: §4.2 tier 1, §4.3 UNGROUPED suppression, §4.4 parent exclusions.

`PinMapping` at `geometry_analyzer.py:374` lacks token coordinates and evidence provenance. NextGen retrieves mappings by `(page, text)` at `nextgen_engine.py:1999` and directly accepts a singleton at `:2005`. `_disambiguate_pin_mapping` at `extraction_engine.py:1684` also accepts a singleton unconditionally; its final fallback has no maximum distance.

**Verified probe:** the mapping for a genuine `U2-C4` was returned for a remote capacitor `C4` in a group at `(900,650,1000,700)` while the IC body was at `(300,150,540,530)`.

The new resolver would convert that real capacitor to `U2-C4`, even with its own value text, because tier 1 wins. The same mistake could remove a genuine unboxed capacitor through the proposed UNGROUPED skip.

Carry token position or an occurrence identity into the mapping and validate spatial compatibility even for a single candidate. Add same-page tests with a U2 ball C4 and a distant real capacitor C4, both boxed and unboxed. Keep true nearby alternative-parent ambiguity distinct from a completely unrelated occurrence.

### 4. [P1] Explicitly trigger geometry for sparse pin partitions and bypass minimum-pin suppression

Plan: §4.5, Increment 4, §7.3.

Adding labels to eligibility and orphan metrics does not guarantee geometry. `extraction_engine.py:1815` requires both the orphan-count and orphan-ratio thresholds. `:1857` separately suppresses pages with fewer than three candidates.

**Verified probe:** pages with one, two, or three candidates were not selected under defaults. Even forcing the trigger left one- and two-candidate pages suppressed.

Resolve §7.3 in the actual specification: suspicious pin partitions must get an explicit trigger and an appropriate exception to the minimum-pin suppression. Cover a single `C4` box and a single Functional `B7` box. Otherwise the dense U2 fixture can pass while the feature named in the plan still fails.

Also reconcile the conflicting definitions: §4.2 restricts a *likely-ball* using BOM/value context, whereas §4.5 labels *every* unresolved ball-like component. A gate based only on non-BOM candidates would miss the very BOM-collision case D2 promises to resolve; labeling all short components may consume the page budget on ordinary component pages. Specify selection priority and warn for all relevant pages skipped by the cap, including pages with only unresolved plain pins.

### 5. [P1] Admitting C4 into pinlist clustering does not make single-pin resolution work

Plan: §4.6 and Increment 5.

There are two additional blockers beyond the candidate skip at `pinlist_parenting.py:949`:

- The page spatial index still classifies `C4` as a passive RefDes. `has_passive_evidence_nearby` at `:549` sees the candidate itself. It becomes an ambiguous cluster, and `should_accept_cluster` at `:845` requires two distinct pinlist hits.
- NextGen's emission still handles RefDes-shaped words before consuming the qualified pinlist result (`nextgen_engine.py:1907`, `:1936`). The proposed ball-like tiers 1–2 do not describe a pinlist result branch. Functional groups are also excluded from the qualification call at `:1703`.

**Verified probe:** after directly admitting a single C4 token, with `U2-C4` in the pinlist and U2 available nearby, the existing functions resolved parent U2 with one hit but rejected the cluster as `ambiguous_low_hits` because C4 supplied its own passive evidence.

Define a safe singleton policy, prevent self-contamination, and wire qualified results into emission. If the increment is cut, explicitly handle the default geometry bypass when a pinlist is loaded instead of implying that geometry resolution still applies. Decide whether Functional pinlist mode is supported and test the chosen behavior.

Related helper correction: the proposed reuse of `has_passive_evidence_nearby` needs a new contract. It checks passive RefDes as well as values; its value regex does not recognize bare `30.1` or `1%`, but does recognize `63mW`, `0.1uF`, `3.3V`, and `5V`. A page-wide 120 pt value radius can also let a neighboring resistor or supply suppress a genuine IC ball. Test ownership/locality of passive evidence rather than only its existence somewhere nearby.

### 6. [P1] Legacy parity requires dispatcher and diagnostics work

Plan: D3, Increment 6 (line 276), done criteria.

Changing the legacy token loop cannot satisfy the proposed acceptance matrix:

- `refdes_extractor_logic.py:1100` exits before geometry for Functional-only pages.
- Non-adaptive geometry at `:1138` and adaptive filtering at `:1419` consider only Piece-Part pages.
- `extraction_engine.py:1201` has its own UNGROUPED capture path.
- `refdes_test_logic.py:342`, `:359`, and `:429` deliberately leave legacy diagnostics empty.

Expand the increment to cover eligibility, early exits, UNGROUPED handling, and diagnostics if collision notes and warning counts are part of parity. Test both forced legacy and an actual Auto fallback, in both extraction modes with adaptive geometry on and off. Calling the increment cuttable also needs an explicit reduced acceptance scope; it cannot simultaneously be omitted and satisfy §8.

### 7. [P2] Make Functional fallback instructions consistent

Plan: §4.2–4.3 versus Increment 3 (line 258).

Increment 3 says every candidate uses tiers 1–2, but tier 2 is restricted to ball-like tokens. §4.3 instead sends plain B7/E8 candidates through the body portion of tier 3 when the group is pin-only. NextGen currently skips Functional groups when precomputing parents (`nextgen_engine.py:1833`).

Specify the same path in design and implementation steps. Test Functional B7/E8 boxes without detected ticks and a neighboring resistor box with pins 1/2. Letting all plain candidates use tier 2 is not an equivalent fix because it defeats the intended resistor protection.

### 8. [P2] Preserve pin provenance per partition before collapsing Functional output to U2

Plan: §4.3, §4.7, Increment 3, §7.7–7.8.

`_record_token_diag` uses only the output token as its key and overwrites fields (`nextgen_engine.py:1285`). The later fold merges groups/pages but not per-occurrence evidence (`:1326`). Component Detail writes one row per token (`runtime.py:607`), while ambiguity notes are applied globally by token (`validation_notes.py:142`).

**Verified probe:** recording U2 once through C4/geometry and once through B7/body-edge retained only the second source, pin, and candidate count. One ambiguous U2 partition can therefore contaminate all U2 notes, or lose its ambiguity when a later clear mapping overwrites it.

Retain provenance by group, page, and pin occurrence, then deduplicate the displayed Functional component within each group. Add explicit validation-note plumbing for BOM collisions: `_flag_bom_collision` currently creates a log/orphan record, not the promised main-sheet sentence. Define aggregation before counting warnings once per group.

### 9. [P2] Test actual PDF vector representations before asserting geometry support

Plan: Increment 0 and §7.10.

The detector at `geometry_analyzer.py:874` treats a drawing's bounding rectangle as a body without validating a rectangular outline. The tick parser at `:1067` accepts tuple/list endpoints but excludes actual `fitz.Point` endpoints returned by PyMuPDF. Its midpoint alignment at `:1118` uses a strict five-point tolerance, so the proposed ten-point stub also fails that alignment check with tuple endpoints.

**Verified PDF probes:** `page.draw_rect` produced one body; the same outline drawn as four separate lines produced none; an open zigzag produced a false body. Real PyMuPDF line endpoints produced zero ticks. These are different representation failures from the 500 pt size cap.

Include rectangle, four-line outline, grouped path, continuous wire, and rotated-label variants. Assert detected graphical evidence separately from text-synthesized mappings. A tuned synthetic fixture cannot establish the representation used by the photographed source PDF.

## Corrections to the trace and acceptance tests

- The component-first harvest, prefix collision, Functional geometry exclusion, and central-parent distance diagnoses are supported by the source. The assertion that the current map is necessarily tick-anchored is not.
- Increment 0's strict xfails are inverted: tests asserting today's incorrect output pass today, producing strict XPASS failures. Assert the desired output under strict xfail, then remove the marker when fixed; or use ordinary characterization tests and explicitly replace their expectations.
- P11 is not a safe oracle. `12D7` is a pin candidate, as verified. Since it is a plain candidate, the proposed group-parent tier can still produce `U2-12D7` even when the token itself is far from the body. Distance from a tick alone does not establish that it remains `PIN-12D7`.
- Rectangle plus separate FreeText does not necessarily mean no group. The probe returned a group using only the small FreeText rectangle, while discarding the intended enclosing rectangle. Report this as wrong group bounds, which can then lose the pin, rather than uniformly claiming no detected group.
- Add `npm run typecheck:tests` to final verification, as required by the repository's frontend expectations when the HelpGuide changes.

## Answers to the open questions

1. **Annotation form:** cannot be established from red text in a photograph. It could be FreeText, separate annotations, or flattened content. The original PDF's annotation/text/drawing structure is the decisive evidence. The review is conditional on a supported markup form; user clarification was requested.
2. **Tier 2:** keep a guarded fallback only after correcting interior/edge distance and removing the unguarded tier-1 bypass. Do not silently treat P2's real-capacitor misclassification as acceptable merely because the proposal calls it an accepted residual. Preserve the ambiguity visibly.
3. **Gate:** use an explicit suspicious-partition trigger, including the minimum-pin exception. Cover sparse plain-pin partitions as well as swallowed RefDes-shaped labels.
4. **Non-adaptive:** a text-only eligibility pass is reasonable. Ensure only the final harvest contributes diagnostics, and preserve cancellation checks. Confirm behavior with Functional-only pages.
5. **Body cap:** do not choose a page-relative limit from the photo alone. Retain a bounded follow-up if needed, but diagnose failure to recognize the target symbol rather than silently accepting bogus component output as successful resolution.
6. **In-box parent without geometry:** do not use absence of value text as proof that a RefDes-shaped word is a pin. Genuine capacitors may omit values. A validated occurrence-level pinlist association is a separate possible evidence source.
7. **Repeated Functional U2:** show the supporting pins per group. Expected sharing of U2 across distinct pin partitions should be distinguishable from accidentally extracting the same pin twice. This requires occurrence-level data first.
8. **Collision count:** one summary per affected group is reasonable; retain every conflicting occurrence in detail. Specify this in the implementation, since existing counters/records do not automatically perform that aggregation.
9. **Legacy:** retain parity if it remains in the done criteria. Include the orchestration/diagnostic changes above, not just the harvest mirror.
10. **Fixture representations:** yes, a four-line-body variant is necessary; it fails today. Also include real PyMuPDF endpoint objects and a negative nonrectangular-path control.

## Additional adversarial probes

- Same-page U2-C4 and genuine C4, with the genuine component alternately boxed and unboxed; no disappearance or reassignment.
- Centered U2 remains the body RefDes; no self-pin `U2-U2`, no adoption of a neighboring ball label as the body owner.
- No ticks plus nearby passive values and numeric terminals: synthesized mappings must not bypass safeguards.
- A page with exactly one C4 partition; exactly one B7 partition; a BOM containing a genuine C4 elsewhere; and several ordinary component pages preceding the target under a small geometry-page cap.
- A single-pin C4 box with a pinlist, no other labels in that numbered group, and a second IC offering the same ball label: accept only supported ownership and retain ambiguity when unresolved.
- Two U2 partitions with different sources and candidate counts: source, pin, ambiguity, and collision notes remain local to their own groups.
- One box containing two U2 pins: Piece-Part emits both qualified pins; Functional emits U2 once. One box containing pins of U2 and U3 emits both parents in Functional mode.
- Repeated DIO-SPARE boxes retain the complete expected set of NC pins in Piece-Part mode under the existing same-label aggregation behavior. Number ordinary partitions uniquely.
- Pin labels rotated on bottom/top edges, labels slightly inside a body boundary, whole-symbol boxes, separate-line bodies, continuous wires, and nonrectangular drawings.
- Auto fallback after a deliberately induced NextGen failure preserves the specified result and diagnostics rather than merely completing successfully.

## Verification scope

Source inspection and focused in-memory Python/PyMuPDF probes were run using the repository virtualenv. The probes established current-code behavior; the proposed implementation does not exist and has not been tested. No full backend/frontend suite was run for this review. The original vector PDF and BOM were not provided, so its true geometry, annotation encoding, and actual BOM collisions remain unverified.
