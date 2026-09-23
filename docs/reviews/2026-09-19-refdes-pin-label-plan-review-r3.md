# RefDes pin-label plan — review round 3

Reviewed 2026-09-19 against code commit `a23fad1aa947b3091a89cc3c5b4d0a91f6ab8628`.

**Reviewed source:** the actual revision 3 in `docs/superpowers/specs/2026-09-16-refdes-pin-label-resolution-design.md`. The latest attachment is identical to the previous stale 382-line attachment; it is not revision 3. Plan line references below identify the local revision reviewed. Its SHA-256 was `12F370D4B228D5B48D0B06BFD155D419E148CAFDF4E73B4BFC8E4BFF94276CE8`.

**Verdict: changes required.** Revision 3 addresses the specific round-2 interior-name, shared-ordering, routing, and pinlist-precedence findings. The following counterexamples remain, including an existing pinlist behavior that the proposed universal ladder would remove.

## Findings

### 1. [P1] Pass A can consume the resistor RefDes before it becomes an owner

Plan lines 188–196 resolve ball-like words before establishing the in-box owner. R29 is itself ball-like. If it satisfies weak S4 evidence, Pass A changes it into a U2 pin and removes the component that S3 needs to protect the resistor terminals.

**Verified geometry input:** U2 right edge x=540, genuine resistor R29 at x=570, terminals at x=562/578, all in a box abutting U2. The existing producer at `backend/python/refdes_extractor/geometry_analyzer.py:1784` produces `text` mappings `U2-R29`, `U2-1`, and `U2-2`. Under the stated new ladder, R29 resolves first at S4. No owner remains for S3, so the terminals resolve at S4 too.

This violates the tight-resistor oracle at plan line 54. P36 constrains the terminals' positions but does not ensure the fixture tests the resistor RefDes inside the threshold too. The earlier example placed R29 outside it.

**Required revision:** protect component ownership from weak reassignment before the ball-like pass consumes an owner. Define the evidence used to establish that protection without turning every ambiguous ball label into an owner. Extend the geometry-backed test so the resistor's own label and both terminals lie within the 50 pt band, in both modes.

### 2. [P1] The adaptive heuristic still excludes valid partitions by pin spelling or count

Plan lines 226–230 fix H7/G7, but retain other hard exclusions:

- `B8 R29 1 2` has a strong signal because B8 is not RefDes-shaped. The equivalent `C4 R29 1 2` has no strong signal, and its numeric terminals veto the weak signal.
- `C4 D8 F6` has no strong signal and exceeds the maximum of two RefDes-shaped words for a weak signal.

Both are legitimate multi-pin/mixed partition patterns covered by the intended behavior. Pure probes using the actual candidate and RefDes predicates confirmed the misses. A Functional-only page becomes ineligible. A Piece-Part page with three swallowed labels also misses the existing five-orphan trigger (`backend/python/refdes_extractor/extraction_engine.py:1815`). Unlike a page-cap exclusion, this can fail without the new cap warning because the heuristic never recognizes a partition.

**Required revision:** use these ambiguous negative patterns to rank work, not to rule out geometry, unless another evidence source establishes that they cannot be pin partitions. Add adaptive public-entry tests for mixed C4/R29 and a three-ball collision-only box. Keep the ordinary-component page-cost control separate from extraction correctness.

### 3. [P1] Universal S1 drops pins that whole-component pinlist extraction currently preserves

Plan S1 at line 193 drops pins whenever the annotation contains their body. Section 4.6 at line 234 runs S0–S4 before pinlist clustering. Together these remove the current pinlist exception.

The existing code deliberately tests `not normalized_pinlist` before applying whole-body suppression in both the mapping and parent branches (`backend/python/refdes_test/nextgen_engine.py:2041`, `:2061`).

**In-memory harvest probe:** a Piece-Part box containing the U2 body and its B7 label emitted only U2 without a pinlist, but emitted `U2, U2-B7` with `pinlist={"U2-B7"}` and `pinlist_prefers_annotation_mode=False`. The new S1 would discard B7 before its allowed pinlist entry could be used.

**Required revision:** preserve this exception, or explicitly propose and justify changing existing pinlist behavior. Add a geometry-enabled whole-component Piece-Part test with an included pin and an excluded pin. The current single-pin-box tests do not cover the regression.

### 4. [P1] The exterior U2 prerequisite still excludes the plan's above-body fixture

G2(b) at plan line 240 retains the dynamic radius and existing biased distance for exterior RefDes selection. Those calculations operate from the body center (`backend/python/refdes_extractor/geometry_analyzer.py:2041`).

For the specified 240 × 380 pt body, the default dynamic radius is `max(100, 0.3 × diagonal) = 134.83 pt`. A label centered 10 pt above the top edge is 200 pt from the body center. It therefore fails the radius test at `:2057`, even when it is outside every aligned pin run.

This contradicts Increment 0 at plan line 276 and P44 at line 378. Reordering classification alone does not make that test pass.

**Required revision:** explicitly define the exterior-label search distance and bounds, for example relative to the outline, while retaining protection against selecting neighboring components or ball labels. Test the actual 240 × 380 dimensions with U2 at the specified above-body position; do not shrink the fixture to fit the current radius.

### 5. [P2] Global interior exclusion needs to distinguish a symbol from a surrounding block

Plan line 180 defines interior with respect to a detected body, and S0 at line 192 executes before strong evidence. The plan also recognizes functional-block outlines in P47. A word can be outside its own IC symbol but inside a surrounding block rectangle.

Existing body detection and deduplication retain an outer rectangle `(300,100,800,580)` and inner U2 rectangle `(300,150,540,530)` (`backend/python/refdes_extractor/geometry_analyzer.py:964`). Put U9 at the outer center `(550,340)` and U2 at the inner center `(420,340)`: the proposed G2 rules select distinct owners, preserving separate serialized keys at `nextgen_engine.py:417`. A U2 ball at `(558,250)` is exterior to U2 but interior to the outer rectangle. Global S0 therefore drops plain B7 or keeps C4 as a component before considering a valid U2 stub. Detection and coordinate predicates were executed; the future G2 owner selection was evaluated from the proposed rules.

**Required revision:** define containment relative to the candidate owning symbol and account for nesting/outline roles. Extend P47 to contain an actual U2 symbol and its exterior pins, not just isolated component text. Verify the rectangles' assigned identities and serialized body candidates so the test exercises the full path, not only raw rectangle detection.

### 6. [P2] Later text fallbacks omit the existing passive-prefix rejection

S3 at plan line 195 intentionally leaves grid-style B8 unclaimed by a passive R29 owner. S5/S6 at lines 197–198 can subsequently choose R29 again, but those rules do not require a pin-analyzed parent prefix. The corresponding current-code rejection is explicit at `backend/python/refdes_test/nextgen_engine.py:2023`.

**Verified current behavior:** with no geometry, a box containing R29 and B8 emits only R29 and records a `passive-prefix` orphan for B8. Following the proposed ladder literally yields `R29-B8` through S5 or S6. That contradicts the promise at plan line 230 that geometry-disabled behavior remains unchanged.

**Required revision:** require the passive-prefix check for every parent-returning fallback, not only S2–S4. Add the no-body R29/B8 regression alongside the successful U2/B8/R29 mixed-box case.

### 7. [P2] P46's visible-residual requirement is absent from the strong-evidence flag policy

P46 at plan line 380 accepts possible stub misassociation when a genuine capacitor label is nearer the edge than the ball label. It requires a BOM-collision flag or the no-BOM note. However, the table at lines 250–254 gives strong evidence a collision flag only when that word is in the BOM. The no-BOM note is specified only for weak evidence.

Thus a wrongly associated strong C4 occurrence with no BOM gets neither of the promised diagnostics. With an incomplete BOM that omits C4, it has the same gap. A generic unverified-component result is not the specified explanation of the pin-reading uncertainty.

**Required revision:** reconcile P46 with the evidence/flag policy. Either strengthen stub association enough to reject this case, or define which uncertainty flag/note makes this accepted residual visible. Add explicit no-BOM and BOM-omits-C4 variants. Do not mark P46 satisfied solely by putting the limitation in documentation when its oracle requires an output diagnostic.

## Round-2 items addressed at design level

- Interior BUSY is now rejected before every fallback.
- Both modes use the same ladder, and text evidence is distinguished from stub evidence.
- The box-abut tolerance is genuinely tighter than the token threshold; weak evidence is retained in diagnostics.
- H7/G7 no longer fails because H is treated as an owner in the fast pass. Finding 2 above concerns different patterns excluded by the replacement heuristic.
- Functional routing moves with Functional implementation, closing the increment-ordering gap.
- Geometry-enabled pinlist precedence and final membership filtering are now explicit. Finding 3 concerns the separate whole-body exception.
- Forced legacy and Auto fallback warnings are both specified, and scope reductions remain pending user decisions rather than being presented as accepted parity.

## Scope and verification

The plan's legacy/pinlist choices and support for the actual PDF still require the decisions/evidence identified in §7. Those are distinct from the correctness findings above. The source PDF and BOM have not been provided; the photograph cannot establish annotation encoding or actual vector representation.

Verification consisted of source inspection and bounded in-memory geometry, predicate, and harvest probes. Proposed behavior is assessed from revision 3's written rules; no new resolver implementation exists. No application code was edited and no full backend/frontend suite was run.
