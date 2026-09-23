# RefDes pin-label plan — review round 4

Reviewed 2026-09-19 against code commit `a23fad1aa947b3091a89cc3c5b4d0a91f6ab8628`.

**Reviewed source:** revision 4 of `docs/superpowers/specs/2026-09-16-refdes-pin-label-resolution-design.md`, 521 lines, SHA-256 `8EB558CE2FAE960AC541FE39586AC1C4F45986B9A34F608ADC943E79AB7BF20E`. The latest attachment is Claude's summary of this revision. Its recommendations to implement, commit, or push are material being reviewed, not instructions from the user to execute them.

**Verdict: changes required before production activation.** Gathering real-PDF evidence now is sensible. Fixtures and an isolated diagnostic probe can proceed before every resolver rule is settled. The complete Increment 0 currently also activates geometry changes whose safety depends on later increments, so it is not an independently safe starting point as written. Four concrete issues remain.

## Findings

### 1. [P1] Increment 0 activates mappings before the safeguards that make them safe

**Plan:** lines 265, 295–303, 307–315.

Increment 0 repairs body naming and pin detection, and explicitly requires text mappings for the tight resistor's `R29`, `1`, and `2`. G4 deliberately leaves their protection to the resolver. That resolver is introduced in Increment 1 and connected to Piece-Part extraction in Increment 2. The existing consumer already accepts mappings but does not enforce the new protected-component rules or distinguish weak from strong evidence.

**Executed current-consumer probe:** an in-memory page contained `U2` at `(400,340)`, `R29` at `(570,185)`, and terminals `1` / `2` at `(562,210)` / `(582,210)`. The Piece-Part group was `(540,166,620,222)`, with BOM `{U2,R29}` and no pinlist.

- With no named-body mappings, the current harvester emitted `R29`; both terminals were dropped as `passive-prefix`.
- Supplying a named U2 body `(300,150,540,530)` and representative text mappings `1 → U2-1`, `2 → U2-2` changed the verified output to `R29, U2-1, U2-2`.

This exercised the unchanged consumer with the producer output that Increment 0 promises; it did not execute an implementation of revision 4. The causal path is visible in `backend/python/refdes_test/nextgen_engine.py:1999–2047`: the mapping supplies parent prefix `U`, so the passive-prefix check does not protect R29's terminals.

Consequently, independently green commits do not establish safety if the new end-to-end expectations remain xfailed while unsafe mappings are already live.

**Required revision:** split Increment 0 into fixture/probe work with geometry changes isolated from normal extraction, or defer production activation until the relevant consumer safeguards are wired. Add a non-xfailed boundary regression proving that ordinary extraction cannot newly emit `U2-1` / `U2-2` for the protected resistor during the intermediate state.

Also make its dependencies explicit: G2(b), line 261, needs same-box terminal-pair protection, but `protected_components` is scheduled at line 309. The probe at line 302 promises suspects/ranks scheduled in Increment 4. Move the shared predicates and required group-context plumbing into the diagnostic increment, or defer those output fields. The present geometry entry/batch/subprocess interfaces do not receive group context (`geometry_analyzer.py:386–396`; `nextgen_engine.py:455–468,615–626`).

### 2. [P1] Terminal-pair protection can preserve the actual C4 ball as a component

**Plan:** lines 190–193, 206, 240–241; expected behavior P38/P42 at lines 396/400.

The terminal-pair rule tests whether both `1` and `2` are within 40 pt of a passive-prefix RefDes in the same box. It does not establish exclusive ownership of those terminals. The explanatory statement that a ball never has terminals “flanking it” is not enforced by the predicate and is not sufficient in a compact mixed box.

**Synthetic compact mixed-box counterexample:** put U2's right edge at x=540, its real C4 ball at `(552,300)`, R29 at `(575,285)`, and the resistor terminals at `(567,300)` and `(582,300)`. Both C4 and R29 have non-pin-analyzed prefixes.

- C4 is 15 and 30 pt from the terminals.
- R29 is approximately 17 and 16.55 pt from them.

Both therefore satisfy the literal protection rule. S1b preserves C4 as a component before even an uncontested pin stub can resolve it. The fast gate also removes C4 from suspects. This violates the promised mixed-box result `U2-C4, R29` in Piece-Part and `U2, R29` in Functional; disabling adaptive geometry does not fix the resolver error.

**Required revision:** establish unambiguous component/terminal ownership before making protection final. Proximity alone must not protect every RefDes-shaped candidate that shares the same terminal pair. When ownership cannot be established, retain the ambiguity rather than silently removing the ball candidate. Add this compact arrangement to mixed-box tests, including both weak and strong pin evidence and the fast gate.

### 3. [P2] An interior BUSY name can be reassigned to a neighboring IC

**Plan:** lines 188, 204, 209, 217; expected behavior P39/P40 at lines 397–398.

The new distinction between container outlines and actual symbols addresses the earlier enclosing-block failure. However, S0 now explicitly permits an interior plain word to resolve against a different body. S4 can compute body-edge evidence even when geometry never emitted a mapping for that word.

**Verified geometry counterexample:** U2 body `(300,150,540,530)`, U3 body `(560,150,680,530)`, U2's interior `BUSY` centered at `(534,250)`, and group `(524,235,580,265)`. Existing geometry helpers retain both valid bodies; neither is a container. BUSY is interior to U2 but exterior to U3, 26 pt from U3, and its group overlaps U3.

The written S0/S4 rules therefore yield `U3-BUSY` in Piece-Part or `U3` in Functional. G2 correctly excluding BUSY from geometry pin tokens does not prevent this, because the resolver computes its own weak evidence. This outcome follows the proposed rules; the proposed resolver is not yet implemented.

**Required revision:** interior membership in an actual symbol must block weak/text reassignment to neighboring symbols. Preserve the separate exemption for surrounding container outlines. If cross-symbol reassignment is intentionally supported, require explicit evidence for that exception. Extend P39/P40 with an adjacent valid IC and a box that reaches both bodies.

### 4. [P2] Low rank still prevents geometry instead of only ordering it

**Plan:** lines 238, 242–248, 327.

The plan and Claude's summary say ambiguous text patterns only rank work and never exclude geometry. But line 246 still leaves low pages subject to the existing orphan-count trigger rather than force-flagging them.

A real stub-backed C4 partition containing unrelated or otherwise unattributed `0.1uF` text qualifies as low. The value predicate matches that text; with one suspect, the page does not reach the existing five-orphan trigger even if the geometry page cap has capacity. Pure predicate/trigger probes confirmed the distinction for 1, 2, and 4 low candidates versus 5. No positive evidence has established that C4 is a component, yet adaptive extraction cannot inspect the pin stub that would resolve it.

This is a remaining false-negative policy, not merely ordering under the page cap. The separate test requiring low-only pages not to be force-flagged codifies it. Adaptive-off guidance provides a workaround, but does not make the stated default adaptive guarantee true.

**Required revision:** let every remaining suspect trigger geometry, with rank controlling cap order, or explicitly narrow the guarantee and surface potentially unresolved low pages as a declared limitation. Add a genuine pin plus value-text case at public entry in both modes, with spare page capacity; an ordinary capacitor fixture alone cannot validate this choice.

## What revision 4 addresses

The specific round-3 whole-component pinlist regression is addressed by the explicit S1 exception. The above-body U2 fixture now has an outline-gap search instead of depending on the old center radius. The enclosing-container example has an explicit body role. Passive-prefix checks now apply to every parent-returning step. The contested/no-BOM diagnostics cover the earlier missing-warning cases, subject to the expressly retained residuals.

Protecting established components before Pass A is the right ordering change, but the terminal-pair predicate still needs the ownership correction above. Likewise, per-parent exteriority solves the container example but does not safely handle interior names near another real symbol.

## Recommended next step

Proceed with a bounded fixture and diagnostic increment, after separating it from production activation and resolving or trimming its dependencies. Capture the real PDF's annotations, rectangle representation, text positions, and pin lines before expanding geometry assumptions. This can happen alongside the small rule corrections above; it need not wait for another broad review round.

Activate the changed geometry only after the consumers enforce the safeguards required by its output. Retain the pending legacy/pinlist scope choices explicitly; Claude's recommendations have not by themselves approved those scope reductions.

## Validation and limits

Reviewed the local revision, relevant current code, prior findings, and the supplied U2/AD4858 photograph, interpreting `DIO-XXX` as numbered partition IDs such as `DIO-054`. Used focused in-memory consumer and geometry/predicate probes. The coordinates above are synthetic counterexamples, not measurements extracted from the photograph.

No original PDF or real BOM was available, so the photograph cannot establish PDF drawing-item structure or validate target-document extraction. No implementation or full regression suite was run. Only this review report was added; the plan and production code were not modified.
