# RefDes pin-label plan — review round 2

Reviewed 2026-09-16 against code commit `a23fad1aa947b3091a89cc3c5b4d0a91f6ab8628`.

**Source clarification:** the newly pasted attachment was the original 382-line document, with only `G5` changed to `G` in the ground-ball list. This review instead covers the actual revision 2 saved in `docs/superpowers/specs/2026-09-16-refdes-pin-label-resolution-design.md`, whose header explicitly identifies it as revision 2. Plan line references below refer to that file as reviewed.

**Verdict: improved, but changes still required before implementation.** The central-U2 prerequisite, mapping occurrence identity, explicit sparse-page trigger, occurrence-level diagnostics, and corrected xfail expectations are meaningful improvements. The remaining issues concern whether the evidence actually establishes pin ownership, and whether all intended paths reach that evidence.

## Findings

### 1. [P1] Same-occurrence geometry still bypasses resistor ownership

Plan lines 195–196 put geometry before the in-box owner; the Piece-Part implementation at line 303 follows that order. Functional line 212 reverses it. Thus the modes still disagree about the protection described at line 204.

Occurrence matching proves that a mapping belongs to this printed word. It does not prove that the printed word is an IC pin. `_create_pins_from_tokens` still synthesizes pins from numeric labels near a body (`backend/python/refdes_extractor/geometry_analyzer.py:1784`).

**Verified counterexample:** U2's right edge is at x=540; resistor R29's RefDes is at x=610; its terminals are at x=565 and x=580. R29 remains a component, but the geometry pass produces `U2-1` and `U2-2` at those exact terminal occurrences. Revised tier 1 accepts them before owner tier 1b can drop them. G2 does not help because these words are outside U2.

**Required revision:** make the ownership/parent-prefix safeguards apply before acceptance of text-synthesized mappings, consistently in both modes. Alternatively, distinguish mapping evidence types and apply the safeguards appropriate to each type. Add the above geometry-backed resistor test; a resolver test with an empty map would miss the defect. The original review's finding 2 remains open.

### 2. [P1] Interior pin names can return through a later fallback

G2 at plan line 250 suppresses interior BUSY in geometry classification. Tier 2 at line 197 also excludes interiors. However, tiers 1b, 3, and 4 do not specify an interior exclusion, and the Functional flow still permits body-adjacency tier 3.

Harvesting reads raw page words and calls `ga.is_pin_candidate` independently (`backend/python/refdes_test/nextgen_engine.py:1907`). It does not consume the geometry classifier's JUNK decision.

**Verified counterexample:** `is_pin_candidate("BUSY", 4)` returns true. A partition extending into the body to include BUSY overlaps U2. When BUSY has no mapping and fails tier 2's outside test, the existing group-parent fallback selects U2 (`nextgen_engine.py:1773`). Piece-Part can therefore emit `U2-BUSY`, contradicting P22 and Increment 2. Functional can also emit U2 for the wrong supporting word.

**Required revision:** specify an occurrence-level interior exclusion before all pin-resolution fallbacks. Preserve interior component RefDes text such as U2 and apply the one-point boundary tolerance consistently. Test a box containing both B7 and BUSY, plus a box containing only the interior name.

### 3. [P1] The adjacency rule does not protect P1's real capacitor, and the residual can be silent

Tier 2 at plan line 197 allows both the token and its containing box to be within the same 50 pt threshold. If the box contains the token, its minimum distance to the body cannot exceed the token's distance. This box check therefore provides no additional protection for normal contained words.

**Concrete counterexample:** body edge x=540; genuine capacitor C4 center x=570; its box begins at x=560. The token is 30 pt away and the box is 20 pt away. Both checks pass even though the box does not touch the body. P1 at line 358 incorrectly expects that non-touching box to block reassignment. Its `0.1uF` value no longer helps because revision 2 withdrew the passive-evidence guard. A same-occurrence synthesized tier-1 mapping can accept the capacitor even earlier.

There is also a visibility gap. P2 requires a flagged residual, but with no BOM and one nearby body, there is no `bom-collision`, no `interior` flag, and no multi-candidate ambiguity. The specified diagnostics can therefore report the false reassignment without any warning.

**Required revision:** define a meaningful ownership constraint, such as validated connection evidence or a genuinely tighter annotation-to-body relationship, and align the P1 oracle with it. If weakly supported reassignment remains an accepted limitation, give that evidence class its own uncertainty flag even without a BOM collision. A collision flag alone cannot represent every false-positive risk.

### 4. [P1] The text-only owner rule still hides legitimate multi-pin partitions

Plan line 184 defines the owner as the unique RefDes not resolved as a pin. The fast pass has no geometry, so short ball labels can become owners before their true role is knowable. Lines 224–226 then use that owner to veto strong-partition status.

**Verified using the existing candidate, RefDes, and prefix predicates:**

- `H7 G7` becomes owner H7 and qualifies as neither strong nor weak. H is a pin-analyzed prefix (`backend/python/common/refdes_utils.py:195`).
- `H7 BUSY` has the same problem.
- `C4 B7` becomes strong: changing only the BGA row letter changes eligibility.
- An ordinary `U3 C7 C8` box has no unique owner and becomes strong, so ordinary mixed-component boxes can consume the priority reserved for pin partitions.

Functional-only pages in the first cases remain ineligible even with adaptive geometry disabled because line 235 uses the same eligibility calculation. This defeats P26 and the intended multi-pin behavior.

**Required revision:** do not let an ambiguous RefDes-shaped ball veto geometry based solely on text. Separate a geometry-free suspicion heuristic from the final owner classification. Add H7/G7 and IC-plus-decoupler priority tests, including a one-page geometry cap.

### 5. [P2] Disabling annotation-first mode is not yet a specified working pinlist path

Plan line 245 tells users to disable annotation-first mode to use geometry, and Increment 5 line 325 promises this resolves the problem. The setting controls an early orchestration shortcut; it does not disable pinlist clustering inside the harvester.

Qualification still runs whenever a Piece-Part group and pinlist exist (`backend/python/refdes_test/nextgen_engine.py:1703`). A rejected cluster is consumed before geometry (`:1936`, `:1958`).

**In-memory harvest probe:** supplied a valid U2-B7 mapping, a pinlist containing U2-B7, an isolated B7 partition, and nearby R29 text. Without the pinlist, the group emitted U2-B7. With the pinlist and `pinlist_prefers_annotation_mode=False`, it emitted no pin and recorded `pinlist-drop: ambiguous_low_hits`.

**Required revision:** specify precedence between an occurrence-validated geometry result and cluster rejection in the geometry-enabled pinlist path. Retain the intended pinlist membership filter (`nextgen_engine.py:2083`) when introducing the new resolver; bypassing clustering must not silently bypass the pinlist itself. Test B7 as well as C4, accepted and absent pinlist entries, and a nearby passive component. If this path is deferred too, the warning must offer a workaround that actually works.

### 6. [P2] Increment 3 depends on routing scheduled for Increment 4

Increment 3 at plan lines 311–312 requires a Functional-only public-entry test to pass with adaptive geometry disabled. The current early exit at `backend/python/refdes_test/nextgen_engine.py:982` skips geometry when no Piece-Part groups exist, and non-adaptive geometry at `:1211` still uses only `pn_pages`. Those eligibility changes remain scheduled for Increment 4 at line 318.

**Required revision:** move removal of the Functional early exit and non-adaptive eligibility into Increment 3 or an earlier routing increment. Leave adaptive triggering and ranking for Increment 4. Alternatively, explicitly defer Increment 3's public-entry acceptance until Increment 4. The current ordering conflicts with independently green commits after each increment.

## Scope and disposition notes

- Deferring full pinlist and legacy support is a scope reduction, not closure of their original correctness requirements. Revision 2 appropriately lists user decisions; do not silently convert the recommended defaults into accepted scope. Once selected, make the done criteria explicitly name NextGen/legacy and supported pinlist configurations.
- If warning-only legacy behavior is selected, cover explicit legacy runs as well as Auto fallback. Section 4.9(b) and Increment 6 currently describe only Auto fallback, while P17 expects the warning for forced legacy too. The forced branch is separate at `backend/python/refdes_test/refdes_test_logic.py:359`.
- Section 9 says round-1 findings 1 and 2 were not received. The complete report is in `docs/reviews/2026-09-16-refdes-pin-label-plan-review.md`. G2 now addresses finding 1 at design level; the synthesized-mapping safeguard bypass in finding 2 remains open above. The central-U2 issue was reported in round 1.
- The original PDF remains necessary to confirm annotation form and body encoding. Deferring four-separate-line body assembly is a stated limitation; keep target-document support conditional until the probe establishes the actual representation.

## What is addressed at design level

Revision 2 explicitly adds the central-U2 classification prerequisite, actual drawing-item checks, PyMuPDF endpoint handling, per-occurrence mapping coordinates and serializer support, a sparse-page trigger with minimum-count exemption, per-group diagnostics and collision notes, correct strict-xfail expectations, and frontend test typechecking. These should now be validated during implementation; the previous issues should not all be reported as unchanged.

The repaired tick parser's unlabeled graphical pins were also checked for interference with text synthesis. The current deduplication predicate requires a matching non-null label (`geometry_analyzer.py:1803`), so those ticks do not suppress the synthesized ball mapping. No new blocker was found there.

## Verification scope

Reviewed the actual local revision-2 plan and relevant source, and ran focused in-memory geometry, predicate, and harvest probes. No application implementation was changed. The proposed resolver is not implemented; counterexamples describe behavior implied by its stated rules and the existing functions it reuses. No full backend/frontend suite was run. The original PDF and BOM remain unavailable.
