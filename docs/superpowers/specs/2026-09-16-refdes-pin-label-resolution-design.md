# RefDes Extractor — Pin-label resolution for single-pin partition boxes

**Status:** design + plan, **revision 4** after external review rounds 1–3 (Codex; reports in `docs/reviews/2026-09-16-refdes-pin-label-plan-review.md`, `…-review-r2.md`, and round 3 as pasted 2026-09-19). Awaiting review round 4 and the user decisions in §7. Not implemented.
**Repo state referenced:** `main` at `a23fad1`. Every `file:line` below was read at that commit. Every "probe" result was reproduced in this repo's venv (PyMuPDF 1.27.2.2); scripts are described in Appendix C.
**Companion input:** a photo of a marked-up schematic page (AD4858 ADC, RefDes `U2`) showing the partition convention. The reviewer should have that image open alongside this document.

**What changed in revision 4:** components are **protected before any pin evidence** (a body's assigned RefDes, or a passive with a `1`/`2` terminal pair), so weak evidence can no longer consume `R29` and then its terminals (§4.2 S1b); **exteriority is evaluated against the candidate parent's own body** and container outlines never own pins (§4.2, §4.7 G5); the **passive-prefix rejection applies to every parent-returning step** (§4.2); whole-body suppression keeps its existing **pinlist exception** (§4.2 S1, §4.6); the adaptive heuristic **ranks ambiguous boxes instead of excluding them** (§4.5); exterior body-RefDes selection is measured **from the outline**, not the body centre (§4.7 G2b); contested stubs and RefDes-shaped pin readings are **always visible** (§4.8); round-3 disposition added (§9).

---

## 0. How to review this

You are reviewing a design and an implementation plan, not code. What would help most:

1. Check the **problem trace** (§2) against the source.
2. Challenge the **ladder** (§4.2): the protection rule S1b, per-candidate exteriority, the order S0–S6, the passive-owner claim rule, the abut tolerance, and the flag policy (§4.8).
3. Challenge the **gate ranking** (§4.5): is any legitimate pin partition still ruled out rather than ranked?
4. Check the **plan** (§5) for increments that cannot be green on their own.
5. Add to the **probe catalogue** (§6.2) and check the **disposition tables** (§9).

The user's goal in one sentence: *a red partition box drawn around a single pin of a large IC (e.g. the box enclosing `C4 ADC1_REFIO`) must produce `U2-C4` in Piece-Part mode and `U2` in Functional mode, never a bogus capacitor `C4`.*

---

## 1. The input

### 1.1 What the image shows

One schematic page. A large BGA IC symbol (`AD4858`, RefDes text `U2` drawn **inside the symbol body, at its centre**) with pins on all four sides. Each pin has a ball designator printed just outside the body edge, sitting just above a horizontal pin line that leaves the body (`A7`, `C4`, `B7`, `C3`, `C5`, `D8`, `E8`, `B8`, `C7`, `C8`, `D7`, `E7`, `F8`, `F7`, `G8`, `F6`, `G7`, `H7`, `H8`, a bottom row of ground balls `G2 E6 G5 A6 B3 B4 B5 B6 C2 D2 D3 D4 D5 E2 E4 E5 F2 G3 G6 G4 H6`), a pin *name* printed **inside** the body next to the edge (`PD`, `REFIO`, `CNV`, `IN0-`, `VIO`, `BUSY`, `SDO1`, `CSDO`, `CS_N`), then a net name outside (`ADC1_REFIO`, `ADC1_BUSY_1`, …, always containing an underscore), then an off-page reference in a small box (`12-D7`, `5-B5`, `5-C5`, `12-D7,5-D8`). Supply text (`3.3V`, `5V`) sits near the top-right pins. The pin lines appear to run from the body edge out to the off-page box as one long line, not a short tick.

Red rectangles are the **partition boxes** ("groups"). On this page:

- About fifteen boxes each enclose **one pin** of `U2`: the ball designator, the net name and the off-page reference. Example: the leftmost box encloses `C4  ADC1_REFIO  12-D7`. The `U2` text is **outside every box**, roughly 200 pt away from the edge boxes (estimated from the photo). Whether a box swallows the interior pin *name* (`REFIO`, `BUSY`) is not knowable from the photo.
- Five boxes each enclose **one series resistor** (`R26`–`R30`) with its pin numbers `1` and `2`, its net name, and value text (`30.1`, `1%`, `63mW`).
- Boxes around NC pins carry the label `DIO-SPARE`; every other box carries the placeholder `DIO-XXX`. In production the `XXX` is a number (`DIO-356`).
- Not boxed: the `U2` body itself, power pins (`B2 F3 F4 F5`, `VIO/D6`), `C6`, `E3`, `H8 ADC1_CS_0`, the whole ground row.

### 1.2 Annotation form (must be established from the PDF, not the photo)

Red monospace text in a photograph cannot distinguish (a) one Text Box annotation whose rectangle is the box and whose `/Contents` is the label, (b) a Rectangle annotation plus a separate Text annotation, or (c) flattened page content. The probe command in Increment 0 (§5) prints it. Target-document support stays **conditional** until that output exists.

- Form **(a)** is what every existing fixture builds and what the group detector reads first (`group_detection.py:285`). Fully supported.
- Form **(b)** produces a **wrong-bounds group**: the label is assigned to the smallest annotation containing the text's centre (`group_detection.py:338-356`), which is the text annotation itself; the enclosing rectangle is discarded and the pin text falls outside the group.
- Form **(c)** yields no annotations; the drawings fallback (`refdes_extractor_logic.py:707-754`) applies and is out of scope.

### 1.3 Expected output (the acceptance oracle)

| Box contents (label) | Today (Piece-Part) | Today (Functional) | Wanted (Piece-Part) | Wanted (Functional) |
|---|---|---|---|---|
| `C4 ADC1_REFIO 12-D7` (`DIO-356`) | `C4` as a component | `C4` as a component | `U2-C4` | `U2` |
| `B7 ADC1_BUSY_1 5-B5` (`DIO-357`) | `PIN-B7` or dropped | nothing | `U2-B7` | `U2` |
| `E8 NC` (`DIO-SPARE`) | `PIN-E8` or dropped | nothing | `U2-E8` | `U2` |
| `D8 ADC1_SCK_R 12-D7,5-D4` (`DIO-358`) | `D8` as a component | `D8` as a component | `U2-D8` | `U2` |
| `C4 D8 F6` in one box (three collision-letter balls) | three bogus components | same | `U2-C4`, `U2-D8`, `U2-F6` | `U2` |
| `R29 1 2 ADC1_SDO_0 30.1 1% 63mW` (`DIO-360`), **with `R29` and both terminals inside the 50 pt band of `U2` and the box abutting the body** | `R29` | `R29` | `R29` — never `U2-R29`, `U2-1`, `U2-2` | `R29` |
| Mixed box: a pin plus `R29 1 2` — both `B8 …` and `C4 …` spellings | `R29` (+ `PIN-B8` / bogus `C4`) | `R29` (+ bogus `C4`) | `U2-B8` / `U2-C4`, and `R29` | `U2`, `R29` |
| `R29` + `B8` in one box with **no body evidence** (geometry off, or no body) | `R29`; `B8` dropped `passive-prefix` | `R29` | unchanged | unchanged |
| A box that also swallows the interior pin name `BUSY` | `U2-BUSY`/`PIN-BUSY` possible | nothing | `U2-B7` only | `U2`, supported by `B7` only |
| A box containing **only** an interior pin name | `U2-BUSY` possible | nothing | nothing | nothing |
| Whole-component Piece-Part box around the `U2` body and its labels, **no pinlist** | `U2` (pins internal) | `U2` | unchanged | unchanged |
| Same box **with a pinlist** containing `U2-B7` but not `U2-E8` | `U2`, `U2-B7` | — | unchanged: `U2`, `U2-B7`; `U2-E8` filtered | — |
| Unboxed `U2` body text | `UNGROUPED (IN BOM)`: `U2` | same | unchanged | unchanged |
| Unboxed ball labels `D6 H8 C2 D2 …` | `UNGROUPED (NOT IN BOM)` | same | removed **only** where uncontested stub evidence exists (§4.3) | same |
| A genuine capacitor `C4` elsewhere on the page, boxed or unboxed, with or without value text, **including 30 pt from the `U2` edge in a box that does not abut the body** | `C4` | `C4` | `C4` — never reassigned, never removed | `C4` |
| An IC `U3` within 50 pt of `U2`, boxed, box abutting `U2` | `U3` | `U3` | `U3` — never `U2-U3` | `U3` |
| Off-page refs `12-D7`, `5-B5` | nothing | nothing | nothing | nothing |

Verification against the BOM: `U2-C4` verifies through its base `U2` (`nextgen_engine.py:724-740`). `PIN-*` tokens never verify by design (`nextgen_engine.py:102-103`).

---

## 2. Current behaviour — verified trace

Default engine is NextGen (`refdes_test/nextgen_engine.py`); Auto falls back to the legacy engine (`refdes_extractor/extraction_engine.py`) on error; legacy can also be forced (`refdes_test_logic.py:357-361`).

### 2.1 The RefDes test runs first and wins

Piece-Part branch, `nextgen_engine.py:1907-1931`:

```python
is_refdes = legacy_logic.REFDES_RE.fullmatch(text) and not legacy_logic.POWER_SOURCE_RE.match(text)
is_pin = ga.is_pin_candidate(text, max_length=max_pin_length)

if is_refdes:
    base = legacy_logic.strip_suffix(text)
    ...
    grouped_data[group_name]["tokens"].add(base)      # emits bare "C4"
    continue                                           # pin logic never reached

if not is_pin:
    continue
```

Functional branch, `nextgen_engine.py:1867-1873`: only `is_refdes` tokens are considered. Legacy has the identical shape at `extraction_engine.py:1463-1477`. The harvest reads raw page words and calls `is_pin_candidate` itself; it does not consume the geometry classifier's token classes.

### 2.2 Why `C4` matches: prefix collision with BGA rows

`REFDES_RE` is `\b(?:<prefixes>)\d+[A-Z]?\b` built from `IEEE_315_PREFIXES` plus user extras (`refdes_test/refdes_darkstar_shared.py:16-34`; defaults in `common/refdes_utils.py:32-97`). Single-letter prefixes include **C, D, F, H, J, K, L, M, P, R, S, T, U, X, Y, Z**; thirteen of twenty JEDEC BGA row letters collide. Some colliding prefixes are pin-analyzed (`H`, `J`, `P`, `U`) and some are not (`C`, `D`, `F`, `R`, `L`), so any rule keyed on prefix or on the *spelling* of a pin behaves differently by row letter.

### 2.3 What the geometry pin map actually is

`geometry_analyzer.py:1615-1627` classifies a RefDes-shaped token that is also a pin candidate and is "near a body edge" as `PIN_LABEL`. Pins come from graphical ticks (`:1012`; created with `label_token=None` and never labelled afterwards) and from **text-synthesized pins** (`_create_pins_from_tokens`, `:1733-1815`). `_build_pin_mappings` (`:2100-2158`) emits `"{refdes}-{pin_label}"` for each pin whose body has an assigned RefDes.

Every *labelled* mapping today is text-synthesized: its evidence is only "a pin-shaped word within 50 pt of a body edge", with no parent-prefix, ownership or context safeguard (§2.11 G4). `PinMapping` (`:374-381`) carries no token position and no evidence provenance. The harvest looks mappings up by `(page, label)` (`nextgen_engine.py:1609-1611`) and accepts a singleton unconditionally (`:2003-2005`); `_disambiguate_pin_mapping` (`extraction_engine.py:1680-1720`) does the same and its last fallback is nearest-body with no maximum distance.

### 2.4 Surviving pins usually cannot find `U2`

For `B7`/`E8` the ladder is (`nextgen_engine.py:1999-2081`): geometry pin map → group parent (`find_parent_refdes`, `:1757-1829`: body **overlapping** the group rect, else RefDes text within ~100 pt of the box centre) → RefDes text inside the box (`refdes_extractor_logic.py:536-576`) → `PIN-<text>`. Before emitting, a parent with a non-pin-analyzed prefix causes a `passive-prefix` drop (`:2015-2029`). Functional groups are skipped by the parent precompute (`:1831-1836`). A box that overlaps the body makes `U2` the group parent for **every** plain candidate in it, including an interior pin name (`is_pin_candidate("BUSY", 4)` is `True`).

Whole-body suppression (`annotation_box_contains_body` → `box-contains-body` drop) is applied in both the mapping branch and the parent branch **only when no pinlist is loaded** (`if not normalized_pinlist and …`, `:2039-2046`, `:2057-2064`). With a pinlist, a whole-component Piece-Part box keeps emitting the pins the pinlist allows.

### 2.5 Neighbouring ball labels can be chosen as the parent

`page_refdes_candidates` (`nextgen_engine.py:1645-1653`) is every RefDes-shaped word on the page, including `C3`, `D8`, and the `D7` in a split off-page ref.

### 2.6 The geometry gate and routing cannot see the problem

- If no Piece-Part page exists, geometry is skipped outright (`nextgen_engine.py:981-983`). Non-adaptive geometry runs on `pn_pages` only (`:1211-1216`). Adaptive metrics are filtered to `pn_pages` (`:1094`).
- Adaptive trigger (`extraction_engine.py:1805-1836`): **both** `orphan_count >= 5` **and** `orphan_ratio >= 0.30`; `apply_suppressions` (`:1839-1866`) then suppresses any page with fewer than 3 pin candidates. A swallowed `C4` is labelled `COMP`, not an orphan.

### 2.7 Mode gate

`RefDesConfig.extraction_mode` defaults to `"functional"` (`runtime.py:55`). A group is Piece-Part only if the dropdown says so or the label ends in `-PN` (`refdes_extractor_logic.py:285-314`).

### 2.8 Body size cap

Detected bodies must be 20–500 pt on each side with aspect 0.3–3.0 (`geometry_analyzer.py:69-74`).

### 2.9 Test coverage of this layout

None. No fixture uses drawn bodies, pin lines, or a geometry-backed pin map in the harvest.

### 2.10 Incidental behaviours worth knowing

- Off-page refs are dropped only because `is_pin_candidate` rejects the hyphen and the 4-character cap. `12D7` **is** a pin candidate.
- `NC`, `GND`, `5V`, `VCC`, `3.3V` are blacklisted; `X` and `DNP` are not and are pin candidates.
- Identically labelled boxes merge into one output bucket (`nextgen_engine.py:1584-1598`). `DIO-SPARE` relies on this.
- Unboxed RefDes-shaped words become `UNGROUPED` rows (`nextgen_engine.py:1398-1479`; legacy copy at `extraction_engine.py:1198-1206`).
- Token diagnostics are keyed by output token and overwritten (`nextgen_engine.py:1280-1287`); the fold merges groups and pages only (`:1326-1340`); Component Detail is one row per token (`runtime.py:607`); ambiguity notes are per token (`validation_notes.py:142`); `_flag_bom_collision` (`:1363-1395`) writes a log line and an orphan record, not a main-sheet note.
- Legacy runs leave diagnostics empty by design (`refdes_test_logic.py:340-344`).
- With a pinlist loaded and any Piece-Part group, cluster qualification runs inside the harvest regardless of `pinlist_prefers_annotation_mode` (`nextgen_engine.py:1700-1712`), and a rejected or unmatched cluster token `continue`s before the geometry lookup (`:1946-1996`). The membership filter for the non-cluster path is at `:2083-2092`.

### 2.11 Geometry analyzer defects (pre-existing; reproduced)

| # | Defect | Evidence | Effect on this feature |
|---|---|---|---|
| **G1** | Tick parser accepts only `tuple`/`list` endpoints (`geometry_analyzer.py:1067-1070`); PyMuPDF returns `fitz.Point`. `_get_edge_alignment` (`:1108-1128`) needs the tick **midpoint** within 5 pt of the edge. Ticks never receive a label token. | `Point` endpoints → 0 ticks; tuples, 10 pt edge-starting → 0; 8 pt straddling → 3 | No graphical connection evidence has ever existed. |
| **G2** | `_distance_to_body_edge` (`:1455-1476`) returns 0 inside the body, and any short RefDes-shaped word "near" an edge is a pin label — so a body's own short RefDes becomes `PIN_LABEL` whether **inside** or **just outside** the body. Exterior RefDes selection measures from the body **centre** with `max(100, 0.3 × diagonal)` (`:2041-2057`): for a 240 × 380 body that is 134.83, while a label 10 pt above the top-left is 230.21 away (184.17 biased). Interior pin *names* are synthesized into pins (`_nearest_edge`, `:1499-1535`). | `U2` at the centre → `PIN_LABEL`, zero mappings. `U2` 10 pt above → `PIN_LABEL`, and out of radius even if reclassified. Only a RefDes longer than `max_pin_label_length` names a body today. Interior `BUSY` → `U2000-BUSY`. | The body is never named on the user's symbol. |
| **G3** | Body detection uses each drawing's bounding `rect` with size/aspect filters only (`:840-912`). | `draw_rect` → 1 body; four separate lines → 0; open zigzag → 3 false bodies | Whether any body exists depends on how the symbol is drawn. |
| **G4** | Text synthesis has **no ownership safeguards**. | Body `U2000`, right edge x=540: terminals `1`/`2` at x≈562/578 **and the label `R29` at x≈569** → `U2000-1`, `U2000-2`, `U2000-R29`; a genuine `C4` + `0.1uF` 30 pt from the edge → `U2000-C4` | Trusting the pin map as-is converts resistors, their terminals and real capacitors into IC pins. |
| **G5** | Nested rectangles are both kept as bodies: deduplication removes only overlaps with IoU > 0.8 (`:923-965`). | Block outline `(200,100,700,580)` around symbol `(300,150,540,530)` → two bodies | A word exterior to its own symbol can be interior to a surrounding outline; an outline can also take the symbol's interior RefDes. |

---

## 3. Decisions already made (with the user, 2026-09-16)

| # | Decision | Chosen |
|---|---|---|
| D1 | Which modes to fix | **Both.** Piece-Part → `U2-C4`; Functional → `U2`. |
| D2 | Tie-break when a ball label also names a real BOM part | **Body evidence decides**, regardless of BOM. The BOM affects *flagging* only (§4.8). |
| D3 | Legacy engine | Round 0: mirror the fix. **Re-opened** (§7.2). |

Recommended options in §7 are **not** accepted scope until the user selects them; §8 names the scope each choice produces.

Non-goals: exposing `parent_refdes_max_radius` in the UI; a sheet-zone regex beyond the zone-shape exclusion; same-label box merging; Rectangle-plus-Text markup support; changing the default extraction mode; a page-relative body cap before real data requires it; suppressing interior RefDes-shaped pin *names* (`D0`–`D7`) as components (a drawn block outline can legitimately contain real parts).

---

## 4. Design

### 4.1 Approaches considered

1. **Harvest reorder only** — rejected: no geometry on Functional pages, gate blind, pin map unsafe (G4), body unnamed (G2).
2. **Shared, evidence-driven resolver + geometry prerequisites + routing/gate eligibility** (chosen).
3. **Symbol-first pre-classification** — over-scoped; depends on the same prerequisites.

### 4.2 Evidence classes and the resolver ladder

New module `backend/python/refdes_extractor/pin_label_resolution.py`, pure functions, no I/O.

**Definitions**

- *Pin candidate*: `ga.is_pin_candidate(text, max_length)` minus zone-shaped tokens `^\d+[A-Z]+\d*$` (`12D7`); the exclusion lives in the resolver.
- *Ball-like*: a pin candidate that also fullmatches `REFDES_RE` and is not a power-source match (`C4`, `H7`, `R29`, `U2`). *Plain*: a pin candidate that does not (`B7`, `E8`, `BUSY`, `1`, `2`). *Grid-style*: `^[A-Z]{1,2}\d{1,2}$`. *Numeric*: all digits.
- *Pin-analyzed prefix*: `should_analyze_pins(prefix)` is true (`common/refdes_utils.py:173`).
- *Occurrence*: one word at one position on one page, `(page, text, centre)`.
- *Symbol body / container*: a detected body whose rect fully contains another detected body is a **container outline**. Containers never own pins, never make a word "interior", and are ignored by S1. Everything else is a symbol body (§4.7 G5).
- *Exterior to P*: the word's centre is not inside symbol body P by more than 1 pt. **Exteriority is always evaluated against the candidate parent's own body**, never against "any body".
- *Box abuts body*: the group rect overlaps the body rect, or the gap between them is ≤ `box_abut_tolerance` (**10 pt**, engine constant, printed by the probe command). A word inside a box can never be farther from a body than its box, so a box check at the 50 pt token threshold would constrain nothing.
- *Protected component*: a RefDes-shaped word that is established as a component **before any pin evidence is considered**, by either
  1. **body identity** — it is the assigned RefDes of a detected symbol body (§4.7 G2); or
  2. **terminal-pair signature** — its prefix is not pin-analyzed and the same box contains numeric words `1` **and** `2`, each within `PASSIVE_TERMINAL_RADIUS` (40 pt) of it. A ball label never has `1` and `2` flanking it. This is positional text evidence, so it is available in the geometry-free fast pass too.
  A protected component claims its terminal pair (the nearest `1` and `2`); those words are dropped `passive-prefix`, as today. Passives drawn without terminal numbers get no protection from rule 2 — that is the P2 residual and it is always flagged (§4.8).

**Evidence classes on `PinMapping`** — new fields `label_center`, `label_rect`, `evidence ∈ {"stub", "text"}`, `contested: bool`; carried by the subprocess serializer (`nextgen_engine.py:385-420`); old payloads deserialize to `None`/`"text"`/`False`.

- **`stub` (strong).** A *pin stub* is an `'l'` segment perpendicular to a symbol body's edge with one endpoint within `TICK_EDGE_TOLERANCE` of that edge (inside its span) and the other endpoint outside the body, length ≥ `MIN_TICK_LENGTH`, no upper bound. Each stub is associated with at most one label and each label with at most one stub: among exterior `PIN_LABEL` words on that side, within `pin_assignment_threshold` of the edge and within `STUB_LABEL_OFFSET` (10 pt) of the stub line, the word **nearest the body edge** wins. If a second qualifying word competed for the same stub, the mapping is marked `contested`.
- **`text` (weak).** A text-synthesized pin with no associated stub.

**The ladder.** Identical in both modes. Per box: establish protected components first; then pass A (ball-like words), pass B (in-box owner = protected components plus ball-like words pass A left as `component`), pass C (plain words). The first step that decides wins. **Every step that returns a parent enforces two invariants:** the word is exterior to that parent's body when the body is known, and a parent whose prefix is not pin-analyzed yields a `passive-prefix` orphan drop (today's rule at `nextgen_engine.py:2015-2029`), never a pin.

| Step | Rule | Ball-like | Plain | Result / source |
|---|---|---|---|---|
| **S0** | **Interior.** A word interior to a symbol body can never be that body's pin. Ball-like → `component` (it is RefDes text, e.g. `U2` in a whole-IC box). Plain → may still be decided by a step whose parent is a *different* body/RefDes; if none decides → orphan `interior-label`, never `PIN-`. | ✓ | ✓ | — |
| **S1** | `annotation_box_contains_body` for the body this word would attach to → drop (`box-contains-body`). **Only when no pinlist is loaded** — the existing exception is preserved. | ✓ | ✓ | — |
| **S1b** | **Protected component** → `component`, final. Its claimed terminal pair → `passive-prefix` drop, final. | ✓ | claimed numerics | — |
| **S2** | **Strong.** A same-occurrence mapping (`label_center` within 3 pt) with `evidence="stub"`. Never falls through to another occurrence or to nearest-body. `contested` → flag `ambiguous`. | ✓ | ✓ | pin, `geometry` |
| **S3** | **In-box owner.** A pin-analyzed owner claims every remaining plain word. A non-pin-analyzed owner claims only numeric and single-character words (→ `passive-prefix` drop); grid-style words (`B8`) are not claimed. More than one candidate owner → no claim. | ✗ | ✓ | pin of owner, `owner-text` |
| **S4** | **Weak.** A same-occurrence `text` mapping, or resolver-computed body-edge evidence. All of: within `pin_assignment_threshold` of the edge; parent is a symbol body with an assigned RefDes; **box abuts body**. Nearest body wins; > 1 in range → `candidates = n`. Always flags `weak-evidence`. | ✓ | ✓ | pin, `body-edge` |
| **S5** | Group parent (`find_parent_refdes`), hardened: symbol bodies the box abuts first (overlap above gap), then RefDes text within radius from the filtered list (§4.4). **Functional uses the body sub-path only.** | ✗ | ✓ | pin, `parent-refdes` |
| **S6** | RefDes text inside the box (`_find_refdes_in_box`). Piece-Part only. | ✗ | ✓ | pin, `box-text` |
| — | Nothing decided. | → `component` (today) | → `unresolved`: `PIN-<text>` in Piece-Part, ignored in Functional (today) | |

Why this shape:

- **S1b before pass A** closes round-3 finding 1: `R29` with its `1`/`2` is a component before weak evidence is ever consulted, in both modes, even when `R29` and both terminals sit inside the 50 pt band and the box abuts `U2`. An IC `U3` next to `U2` is protected by body identity.
- **Per-candidate exteriority and containers** close round-3 finding 5: `B7` outside `U2` but inside a surrounding block outline is still `U2`'s pin; `BUSY` inside `U2` is not, at any step.
- **Passive-prefix on every parent-returning step** closes round-3 finding 6: with no body evidence, `R29` + `B8` still yields `R29` and a `passive-prefix` orphan for `B8`, exactly as today. With body evidence `B8` is decided earlier (S2/S4) and S5 is never reached.
- **Ball-like words may use only S0–S2 and S4.** S3/S5/S6 are text-proximity evidence; applied to ball-like words they would turn every decoupling cap in an IC's Functional box into `U3-C7`.
- **S4's abut rule**: a genuine `C4` 30 pt from the edge in a box 20 pt from the body does not abut and stays `C4` (P1); if its box abuts and it has no terminal pair it becomes `U2-C4`, always flagged (P2).

### 4.3 Emission per mode

**Piece-Part.** `pin` → `"{parent}-{text}"` with a per-occurrence diagnostic (§4.8). `component` → today's path. `unresolved` → `PIN-<text>`. With a pinlist loaded the membership filter applies to every emitted pin (§4.6).

**Functional.** Same ladder. `pin` → add **`parent`** to Verified/Unverified by BOM membership, with a per-occurrence diagnostic naming the supporting pin. Words claimed at S1b/S3 add nothing. The parent precompute at `nextgen_engine.py:1831-1836` runs for Functional groups (body sub-path only).

**UNGROUPED capture.** An unboxed ball-like word is removed from `UNGROUPED` only with **uncontested strong** (S2) evidence for its own occurrence and only if it is not a protected component. Otherwise it stays where it is today. On drawings with no detectable stubs the ground-row noise remains (recorded residual).

### 4.4 Page-wide parent candidates

`page_refdes_candidates` excludes any ball-like occurrence that is not a protected component, is exterior to and within `pin_assignment_threshold` of a symbol body whose RefDes has a pin-analyzed prefix. Passive-prefix RefDes elsewhere remain candidates, so a resistor box still finds `R29` and still drops its terminals. With no body rects for the page, nothing is excluded.

### 4.5 Routing, eligibility and the gate

**Routing (Increment 3).** The `not pn_pages` early exit (`nextgen_engine.py:981-983`) applies only when geometry is disabled or the document has no groups. **Non-adaptive** geometry runs on **every page that has at least one group**.

**Adaptive gate (Increment 4).** Correctness and cost are kept separate (round-3 finding 2): ambiguous text patterns **rank** work; they never rule geometry out. Only positive evidence that a word is a component removes it from consideration.

- A word is a **suspect** if it is a grid-style pin candidate inside a box and is not a protected component (terminal-pair rule only in the fast pass) nor one of its claimed terminals.
- **Eligible pages** = `pn_pages` ∪ pages with ≥ 1 suspect. So `C4 R29 1 2` is eligible (`R29` protected, `C4` suspect), and so is `C4 D8 F6`.
- **Rank** per page, used only to order work under `adaptive_max_pages`:
  - **High** — boxes containing a suspect that is not RefDes-shaped (`B7`, `E8`, `G7`).
  - **Medium** — boxes containing a RefDes-shaped suspect and no *unattributed* passive-value word. A passive-value word is a `VALUE_UNIT_RE` match whose unit is not `V` or `A` (supply labels are excluded); one within 40 pt of a protected component is attributed to it and ignored. `C4`, `C4 D8 F6`, `C4 R29 1 2 63mW`, and also `U3 C7 C8` are all medium: text cannot tell them apart, so they tie and the cap decides.
  - **Low** — boxes whose only suspects sit with their own unattributed passive-value text (`C12 0.1uF`).
- **Trigger:** pages with any high or medium box are flagged regardless of the orphan thresholds and are exempt from `min_pins_for_geometry`. Low pages stay eligible through the existing orphan trigger (they count `BALL_LIKE_COMP` orphans) but are not force-flagged.
- **Order under the cap:** high count, then medium count, then the existing orphan score.
- **Warning:** when the cap skips a high or medium page, or a page whose only issue is unresolved plain pins, one counted warning names the pages and the option. Skipped low pages get an info log line, not a counted warning.
- `geometry_analysis_enabled=False`: no behaviour change; one log line. Degraded pages keep today's output and warning. User guidance (docs): for pin-partitioned documents, turning adaptive geometry off guarantees every group page is analysed.

### 4.6 Pinlist paths (decision §7.3)

- **Geometry-enabled pinlist path** (`pinlist_prefers_annotation_mode=False`): in scope. S0 and S1b–S4 run **before** the cluster branch; **S1 is skipped because a pinlist is loaded**, preserving today's whole-component behaviour (a Piece-Part box around the `U2` body emits `U2` plus the pins the pinlist lists). A decided `pin` takes precedence over cluster rejection; every emitted pin then passes the **membership filter** (`nextgen_engine.py:2083-2092`): absent from the pinlist → `pinlist-filtered`. With no body evidence the existing cluster logic is unchanged.
- **Annotation-first pinlist path** (default; geometry skipped): deferred, with one counted warning naming the working workaround (turn off annotation-first). A follow-up spec covers singleton policy, passive-evidence self-exclusion, and Functional support.

### 4.7 Geometry prerequisites (Increment 0)

- **G1** Accept any endpoint with `len >= 2`. Pin-stub detection, exclusive stub↔label association, `contested` marking (§4.2).
- **G2** Body RefDes selection runs **before** pin-label classification, per symbol body:
  (a) **Interior:** a RefDes-shaped word interior to the body and **not interior to a nested body** (the innermost body owns an interior word; a container does not take its symbol's RefDes). Among several, prefer a pin-analyzed prefix, then nearest the centre.
  (b) **Exterior, measured from the outline:** a RefDes-shaped word whose gap to the body's outline is ≤ `REFDES_OUTLINE_MAX_GAP` (**30 pt**), that is not part of an aligned pin run (≥ 3 pin candidates on the same side whose edge distances agree within 3 pt), is not a terminal-pair protected passive, and is not closer to another body's outline. Prefer a pin-analyzed prefix, then the smallest gap, then the existing top-left bias.
  (c) **Legacy fallback:** the existing centre-distance rule, unchanged, so small-body behaviour does not regress.
  The chosen word is `REFDES`, never `PIN_LABEL`. Each word names at most one body. Interior non-RefDes candidates are not pins. Pins are synthesized for exterior words only. `_is_near_body_edge` gains `outside_only` for the classifier.
- **G3** A drawing is a body only if its items describe a rectangle: a `'re'` item, or a closed sequence of four orthogonal `'l'` items. Four separate drawings are not assembled here (§7.4).
- **G4** Synthesis keeps producing `text` mappings; the safeguards live in the ladder, where the box, its owner and the protected components are known.
- **G5** Container outlines are identified after detection (rect fully contains another body). They are serialized with `role="container"` in the body payload so the harvest can ignore them for ownership, S0 and S1; `body_rects` never holds two entries for one RefDes on a page.

### 4.8 Provenance, flags and notes

`_record_token_diag` keeps an `occurrences` list per output token: `{group, page, pin_text, source, evidence, confidence, candidates, flags}`, appended, never overwritten. Component Detail writes one row per `(token, group)` with `Pins`, `Sources` and `Flags`. Notes are computed per group from that group's occurrences.

| Situation | Component Detail flag | Validation Note | Counted |
|---|---|---|---|
| Any ball-like word read as a pin, any evidence | `refdes-shaped` | — | no |
| … and the word also names a BOM part | + `bom-collision` | per group, lists the balls | once per group |
| … and **no BOM is loaded** (strong or weak) | + `unconfirmed` | per group: "pin reading unconfirmed (no BOM): C4, D8" | **once per run** |
| … and the BOM is loaded and omits the word | `refdes-shaped` only | none — the BOM corroborates the reading | no |
| Weak evidence, any word | + `weak-evidence` | none on its own | no |
| Contested stub, or > 1 body in range | + `ambiguous` | existing ambiguity note, per group | once per group |

So a RefDes-shaped pin reading is visible in every BOM situation (round-3 finding 7): a contested stub raises a counted ambiguity note regardless of the BOM; with no BOM the group carries a note for strong evidence too; with a BOM that omits the word, the `refdes-shaped` flag in Component Detail is the diagnostic, and that narrow case (an uncontested stub carrying a genuine, BOM-missing passive's label and no ball label) is a recorded residual. `ORPHAN_BOM_COLLISION` records are still written. A Functional parent appearing in several groups keeps its cross-group duplicate note, annotated "via pin C4".

### 4.9 Legacy engine (decision §7.2)

A harvest mirror cannot satisfy §1.3 (`refdes_extractor_logic.py:1096-1104`, `:1136-1140`, `:1417-1421`; `extraction_engine.py:1198-1206`; diagnostics empty). Options: **(a)** full parity; **(b)** warning only — recommended; **(c)** reduced parity without diagnostics. Under (b) the counted warning fires for **both** a forced legacy run (`refdes_test_logic.py:357-361`) and an Auto fallback (`:427-431`).

### 4.10 Docs

Component Detail vocabulary gains sources `body-edge`, `owner-text`; flags `refdes-shaped`, `weak-evidence`, `unconfirmed`, `bom-collision`, `ambiguous`; orphan disposition `interior-label` (banner `runtime.py:578-585`; pinned vocabulary tests `test_nextgen_engine.py:99-127`, `test_validation_notes.py:189`). `docs/USER_GUIDE.md` §5 and `HelpGuide.tsx`: partition convention, both modes' outputs, geometry requirement, the adaptive-off recommendation, supported annotation form, the flags. Fix `docs/TOOLS.md:505-506`. `docs/DECISIONS.md`, `CHANGELOG.md`, test counts in five places.

---

## 5. Implementation plan

Workflow: each increment is **implement (TDD) → spec-compliance review → adversarial QA with probe tests → fix → re-verify** (§6.1). One commit per increment on `main`; **every increment must be green on its own**; push after the last. Backend tests: `.venv\Scripts\python.exe -m pytest backend/tests -v`.

### Increment 0 — Geometry prerequisites, fixtures, real-PDF probe

- **Fixture builders** `backend/tests/refdes_fixtures.py`: `build_bga_sheet_pdf(path, *, body=…, pin_lines="long"|"tick_edge"|"tick_straddle"|"none", u2_pos="center"|"above"|"long_name", container=False, …)`. Page 1224 × 792; body **exactly 240 × 380**; `U2` + `AD4858` at the centre; interior names; ball labels just above each pin line incl. collision letters and an unboxed ground row; underscore nets; off-page refs; `3.3V`/`5V`; resistor groups with `1`/`2` and values, including **a tight variant with `R29` and both terminals inside the 50 pt band and the box abutting the body**; mixed `B8`+`R29` and `C4`+`R29` boxes; a `C4 D8 F6` box; a genuine `C77`; genuine far and near `C4` variants (box 20 pt away; box abutting); a second IC `U3` with its own body within 50 pt of `U2`; `container=True` draws a block outline around the **whole `U2` symbol and its exterior pins**; Text Box annotations per §1.2(a); knobs to push a box edge into the body, to box only `BUSY`, to draw a whole-component box, and to rotate bottom-row labels.
- **G1–G5 + mapping fields**, each test-first. In particular: `u2_pos="above"` on the **real 240 × 380 body** names it `U2` via the outline gap (it fails today's centre radius); with `container=True` the symbol is `U2`, the outline is a container with no RefDes of its own, `body_rects` has one `U2`, and the serialized payload carries the role; `R29` with a terminal pair is never chosen as a body RefDes.
- **Fixture validity test:** `U2-C4`, `U2-B7`, `U2-E8` mappings with correct `label_center`; `evidence="stub"` on `pin_lines="long"`, `"text"` on `"none"`; the tight resistor's `R29`, `1`, `2` and the near genuine `C4` appear **only** as `text` mappings (G4 must be visible to the ladder tests, not hidden by the fixture).
- **Probe command** `python backend/python/sidecar_main.py --probe-geometry <pdf> --page N`: annotations; drawing item types; bodies with role and assigned RefDes; stubs with associated labels and contested marks; `PIN_LABEL` words; per-box gap to the nearest symbol body; protected components; per-box suspects and rank.
- **Characterisation tests** assert the **wanted** §1.3 output under `xfail(strict=True)`; later increments remove the markers they satisfy.

**Adversarial QA:** fixture faithfulness; P19–P22, P35, P44, P47, P51.

### Increment 1 — Resolver module (pure)

`pin_label_resolution.py`: predicates, `protected_components`, `in_box_owner`, `box_abuts_body`, `resolve_box(…)`. Unit tests use **geometry-shaped mapping inputs** (including `text` mappings on `R29`, `1`, `2`): S0 per-candidate exteriority with a container present; S1 with and without a pinlist; S1b by body identity and by terminal pair (pair present / only `1` / beyond 40 pt / pin-analyzed prefix); S2 occurrence identity and `contested`; S3 claim rules; S4 abut at 9.9/10.1 pt; **passive-prefix on S3, S5 and S6**; ball-like never reaches S3/S5/S6; zone shape; flags.

**Adversarial QA:** boundaries, degenerate rects, missing fields, `max_pin_label_length` 2 and 8.

### Increment 2 — NextGen Piece-Part wiring

Ladder in the Piece-Part branch; §4.4 filter; hardened S5; occurrence-aware UNGROUPED; per-occurrence diagnostics, flags, notes. End-to-end on the fixture, **adaptive off**, on both `pin_lines="long"` and `"none"`: every Piece-Part row of §1.3, including the tight resistor, both mixed-box spellings, `C4 D8 F6`, `U3` next to `U2`, the **no-body `R29`+`B8` regression** (geometry disabled → `R29` plus a `passive-prefix` orphan, byte-identical to today), and the whole-component box without a pinlist.

**Adversarial QA:** P1–P4, P8, P10–P14, P23–P27, P36–P40, P46a–c, P48, P50.

### Increment 3 — Routing + NextGen Functional wiring

Early-exit change and non-adaptive page set; Functional ladder and parent precompute. End-to-end through the **public entry**, Functional, **adaptive off**, on a Functional-only document: every Functional row of §1.3.

**Adversarial QA:** P15, P28–P30, P41.

### Increment 4 — Adaptive gate

Suspects, ranks, trigger, exemption, ordering, warnings, `BALL_LIKE_COMP`. **Public-entry adaptive tests**, each as a Functional-only page and as a Piece-Part page: single `C4` box; single `B7` box; `H7 G7`; `H7 BUSY`; **`C4 R29 1 2 63mW`**; **`C4 D8 F6`**; `U3 C7 C8` pages tie at medium and do not outrank a high page under `adaptive_max_pages=1`; a low-only page is not force-flagged; the cap warning names skipped high/medium pages and unresolved-plain-pin pages.

**Adversarial QA:** P6, P7, P9, P16, P31, P32, P42.

### Increment 5 — Pinlist (per decision §7.3)

Recommended scope: §4.6. Tests: `B7` and `C4` single-pin boxes with the entry present vs absent and a nearby `R29`; **a geometry-enabled whole-component Piece-Part box with one included and one excluded pin** (included emitted, excluded `pinlist-filtered`, neither dropped as `box-contains-body`); annotation-first on → warning and today's output.

### Increment 6 — Legacy (per decision §7.2)

Recommended scope: §4.9(b), tested for a forced legacy run and an Auto fallback, both modes; output equals today's legacy output.

### Increment 7 — Docs and counts

§4.10; counts in five places; `KNOWN_RESIDUALS.md` entries (§8).

### Final verification

Full backend suite, `npm test`, `npm run typecheck`, `npm run typecheck:tests`, sidecar `--self-test`, `code-review` skill over the whole diff, then push.

---

## 6. Adversarial QA / QC protocol

### 6.1 Protocol

Per increment, after the implementer reports green: (1) a fresh **spec-compliance reviewer** checks the diff against §4; (2) a fresh **adversarial QA agent**, given this document, the fixture builder and the increment's *claim*, writes probe tests first and runs them; (3) the implementer fixes, QA re-runs, the reviewer re-checks touched lines; (4) unfixed findings go to `docs/reviews/KNOWN_RESIDUALS.md` with rationale. Every finding is verified against the code before it is reported.

### 6.2 Probe catalogue

| # | Probe | Expected |
|---|---|---|
| P1 | Genuine `C4` 30 pt from the `U2` edge, box 20 pt from the body, `0.1uF` nearby, weak mapping present | Stays `C4` (box does not abut) |
| P2 | Same, but the box abuts the body and there are no terminal numbers | `U2-C4` with `refdes-shaped` + `weak-evidence` always; `bom-collision` or `unconfirmed` per §4.8 |
| P3 | Two ICs with facing edges 60 pt apart; a pin box between them | Nearest body; `candidates=2`; ambiguity note |
| P4 | Ball label that is also a BOM RefDes | `U2-C4`; per-group collision note; one warning for the group; Orphan Pins `bom-collision` row |
| P5 | Body 520 pt tall | No body → today's output; probe command reports it |
| P6 | `adaptive_max_pages` below the number of high/medium pages | One counted warning naming skipped pages |
| P7 | Geometry batch timeout on the fixture page | Degraded page keeps today's output and warning |
| P8 | PROV-marked ball label | `PROVISIONAL` gets `U2-C4` / `U2` |
| P9 | Cancellation mid-resolve and between fast pass and geometry | `CancellationError`; no partial output |
| P10 | `R29` box far from any IC | `R29`; terminals dropped `passive-prefix` |
| P11 | Zone text `12D7` in a pin box | Excluded |
| P12 | Two-letter row ball `AR3` | Same path as `C4` |
| P13 | Word exactly at `pin_assignment_threshold`; box gap exactly at `box_abut_tolerance`; RefDes gap exactly at `REFDES_OUTLINE_MAX_GAP` | Inclusive |
| P14 | Same ball label on two pages | Per-occurrence; both pages recorded |
| P15 | Functional box around the whole `U2` body plus ball labels | One `U2`; pins dropped at S1 |
| P16 | Page with one swallowed ball label and nothing else | Medium → flagged, exempt from min-pins |
| P17 | Forced legacy on the fixture | Per §7.2 |
| P18 | Rectangle + separate Text annotation | Group with the label's rect; documented unsupported |
| P19 | Body as four separate drawings | No body; probe command says so |
| P20 | Open zigzag | No false body |
| P21 | `Point` endpoints; long pin lines | Stubs detected and labelled |
| P22 | `U2` inside the body; interior `PD`/`REFIO`/`BUSY` | `U2` names the body; no `U2-U2`, no interior pins |
| P23 | `U2` ball `C4` and a genuine far `C4`, boxed and unboxed | Ball → `U2-C4`; genuine stays `C4` |
| P24 | `U2-C4` and `U3-C4` mappings; word at U3's edge | `U3-C4`; `candidates` 1 |
| P25 | Old payload without the new mapping fields | S2 unavailable; S4 still works |
| P26 | One box with two or three `U2` pins: `H7 G7`, `H7 C4`, `C4 D8 F6` | Piece-Part all pins; Functional `U2` once |
| P27 | One box with pins of `U2` and `U3` | Both pins / both parents |
| P28 | Functional `B7` box, `pin_lines="none"` | `U2` via S4 with `weak-evidence` |
| P29 | Functional `U3 C7 C8 1 2 3` | `U3`, `C7`, `C8`; numerics owned by `U3` |
| P30 | Two `U2` partitions with different sources/candidates | Provenance stays local to each group |
| P31 | `U3 C7 C8` (medium) and `C12 0.1uF` (low) pages before a high page, cap 1 | High page chosen |
| P32 | Page with only unresolved plain pins, under the cap | Named in the cap warning |
| P33 | Repeated `DIO-SPARE` boxes | Complete NC set aggregated |
| P34 | Auto fallback after an induced NextGen failure | Warning present |
| P35 | Rotated bottom-row labels; label 1 pt inside the outline | Resolve; tolerance holds |
| P36 | **Tight resistor**: `R29` **and** both terminals inside the 50 pt band, box abutting `U2`, geometry-backed map containing `U2-R29`, `U2-1`, `U2-2` `text` mappings | `R29` only, both modes; `R29` protected at S1b; terminals `passive-prefix` |
| P37 | Same wire carries ball `B8` then resistor terminal `1` | Stub associates with `B8` only |
| P38 | Mixed box pin + `R29 1 2`, weak evidence only, both `B8` and `C4` spellings | `U2-B8` / `U2-C4` and `R29`; Functional `U2`, `R29` |
| P39 | Box containing `B7` and interior `BUSY` | `U2-B7` only; `BUSY` → `interior-label` |
| P40 | Box containing only interior `BUSY`, overlapping the body | Nothing emitted |
| P41 | Functional-only document, adaptive off, public entry | Geometry runs; Functional rows of §1.3 |
| P42 | Adaptive, public entry, Functional-only and Piece-Part: `H7 G7`, `H7 BUSY`, `C4 B7`, `C4 R29 1 2 63mW`, `C4 D8 F6` | All flagged; none depends on pin spelling or count |
| P43 | Pinlist + geometry, single-pin boxes | Present → emitted; absent → `pinlist-filtered` |
| P44 | `U2` 10 pt above the **240 × 380** body with top-edge pins present | Body named `U2` via the outline gap |
| P45 | `X` or `DNP` inside a pin box | QA reports whether either needs blacklisting |
| P46a | Genuine passive label and a ball label compete for one stub | `contested` → `ambiguous` flag and counted note, any BOM state |
| P46b | Uncontested stub carrying a RefDes-shaped label, no BOM | `unconfirmed` note on the group |
| P46c | Same, BOM loaded and omits the word | `refdes-shaped` in Component Detail only; recorded residual — QA confirms the flag is present, not merely documented |
| P47 | Block outline around the **whole `U2` symbol and its exterior pins**, plus real parts inside the outline | `U2` pins resolve; outline is a container with no RefDes; interior real parts stay components; one `U2` in `body_rects`; serialized role checked |
| P48 | `R29` + `B8` box with no body evidence | `R29`; `B8` `passive-prefix` orphan; identical to today |
| P49 | Whole-component Piece-Part box, geometry on: no pinlist / pinlist with one included and one excluded pin | No pinlist → `U2` only. Pinlist → `U2`, included pin; excluded `pinlist-filtered`; none `box-contains-body` |
| P50 | IC `U3` with its own body within 50 pt of `U2`, boxed, box abutting `U2` | `U3` (protected by body identity) |
| P51 | Two capacitors `C7`, `C8` without terminal numbers beside an IC edge, box abutting | Both become flagged weak pins (P2 residual at scale); QA reports the note wording and whether the count is tolerable |

---

## 7. Decisions needed from the user

1. **Real-PDF probe.** Run the Increment 0 probe on the page in the image and paste the output. Increments 0–4 can proceed on assumptions meanwhile; support for the target document stays conditional until then.
2. **Legacy engine (re-opens D3).** (a) full parity, (b) warning only — recommended, (c) reduced parity.
3. **Pinlist.** Recommended: geometry-enabled path in scope, annotation-first deferred with the warning.
4. **Four-line body assembly.** Only if the probe shows separate-line bodies.

---

## 8. Done criteria

- **Engine scope is stated explicitly once §7.2/§7.3 are chosen.** Under the recommended options: *NextGen engine; no pinlist, or pinlist with annotation-first off; legacy and annotation-first pinlist are warning-only and excluded from the §1.3 oracle.* Deferral is a scope reduction, not closure; both are recorded in `KNOWN_RESIDUALS.md` with their original requirement.
- The fixture in both modes, adaptive on and off, `pin_lines="long"` and `"none"`, yields exactly the "Wanted" columns of §1.3.
- G1–G5 tests pass; the probe command runs on the fixture and on a PDF with no body.
- No existing test changes its assertion except those named here (vocabulary/legend tests, docs counts, characterisation xfails removed as they flip).
- All P-probes pass or are recorded residuals. P2, P46c and P51 are recorded as **visible** residuals with their output diagnostic named.
- Full backend + frontend suites green; `typecheck` and `typecheck:tests` clean; counts synced; docs updated; DECISIONS entry.
- `KNOWN_RESIDUALS.md` gains: the real-data checklist item; ground-row UNGROUPED noise on stub-less drawings; four-separate-line bodies; interior RefDes-shaped pin names as components; passives without terminal numbers abutting an IC.

---

## 9. Review dispositions

### Round 1 (`docs/reviews/2026-09-16-refdes-pin-label-plan-review.md`)

Correction carried from revision 3: the round-1 paste was truncated; **round-1 finding 1 reported the centred-`U2` defect.**

| # | Finding | Verified | Disposition |
|---|---|---|---|
| 1 | Centred `U2` classifies as a pin; body unnamed | Yes, reproduced; widened | G2, §4.7 |
| 2 | Tier 1 is text-synthesized and bypasses safeguards | Yes, reproduced | Evidence classes; safeguards in the ladder |
| 3 | No occurrence identity | Yes | `label_center`; same-occurrence only |
| 4 | Gate needs an explicit trigger and min-pin exemption | Yes | §4.5 |
| 5 | Pinlist blockers; `has_passive_evidence_nearby` unfit | Yes | Guard withdrawn; §4.6 |
| 6 | Legacy parity is orchestration + diagnostics | Yes | §4.9 |
| 7 | Functional path inconsistent | Yes | One ladder for both modes |
| 8 | Provenance overwritten per token | Yes | §4.8 |
| 9 | Body/tick representation | Yes, reproduced | G1, G3, fixtures, probe command |

### Round 2 (`docs/reviews/2026-09-16-refdes-pin-label-plan-review-r2.md`)

| # | Finding | Verified | Disposition |
|---|---|---|---|
| 1 | Same-occurrence geometry bypasses resistor ownership | Yes, reproduced | Weak evidence meets ownership first; completed by round-3 #1 |
| 2 | Interior names return through later fallbacks | Yes, reproduced | S0; refined by round-3 #5 |
| 3 | Box-adjacency at the token threshold is vacuous; residual can be silent | Yes | `box_abuts_body`; always-flagged weak evidence |
| 4 | Text-only owner veto | Yes | Owner removed from the fast pass; completed by round-3 #2 |
| 5 | Annotation-first off is not a working path | Yes | Precedence + membership filter |
| 6 | Increment 3 depended on Increment 4 | Yes | Routing moved into Increment 3 |

### Round 3 (pasted 2026-09-19)

| # | Finding | Verified | Disposition |
|---|---|---|---|
| 1 | Pass A can consume `R29` before it becomes an owner | **Yes, reproduced**: `U2000-R29`, `U2000-1`, `U2000-2` with `R29` at x≈569 beside edge x=540 | S1b protected components (body identity; terminal-pair signature) established before any pin evidence; P36 now places the label inside the band; both modes |
| 2 | Heuristic still excludes `C4 R29 1 2` and `C4 D8 F6` | **Yes**, from the revision-3 rules | Suspects rank, never exclude; only protected components are removed; value text attributed to a protected component is ignored; adaptive public-entry tests for both patterns, Functional-only and Piece-Part (§4.5, P42) |
| 3 | Universal S1 removes the whole-component pinlist behaviour | **Yes**: `if not normalized_pinlist and …` at `nextgen_engine.py:2039`, `:2057` | S1 applies only without a pinlist; §1.3 row; included/excluded-pin test (Inc 5, P49) |
| 4 | Exterior `U2` is outside the centre-based radius | **Yes, computed**: radius 134.83 vs 230.21 (184.17 biased) | G2(b) measures from the outline (`REFDES_OUTLINE_MAX_GAP` 30 pt) with one-body-per-word, aligned-run and protected-passive guards; centre rule kept as fallback; P44 uses the real 240 × 380 body |
| 5 | Global interior exclusion vs a surrounding block | **Yes, reproduced**: nested rectangles are both bodies | Per-candidate exteriority; container outlines never own pins or make words interior; innermost body owns an interior RefDes; serialized role; P47 extended |
| 6 | S5/S6 omit the passive-prefix rejection | **Yes** (`nextgen_engine.py:2015-2029`) | Invariant on every parent-returning step; no-body `R29`+`B8` regression (Inc 2, P48) |
| 7 | P46 diagnostic missing for strong evidence without a BOM collision | **Yes**, from the revision-3 table | `contested` stubs → counted ambiguity; `unconfirmed` note for strong evidence with no BOM; `refdes-shaped` flag always; P46a–c with the BOM-omits variant recorded as a residual whose diagnostic is the flag |

---

## Appendix A — Glossary

- **Group / partition box** — a PDF annotation whose rect defines a failure-mode group; label from `/Contents`.
- **Ball-like / plain / grid-style / numeric / suspect** — word classes defined in §4.2 and §4.5.
- **Occurrence** — one word at one position on one page.
- **Symbol body** — a detected rectangular outline (20–500 pt, aspect 0.3–3.0) that contains no other body. **Container outline** — a body that contains another body; never owns pins.
- **Pin stub** — a line leaving a symbol body's edge perpendicularly. **Evidence** — `stub` (exclusively associated with this label; possibly `contested`) or `text`.
- **Protected component** — a body's assigned RefDes, or a passive-prefix RefDes with a `1`/`2` terminal pair in its box.
- **In-box owner** — a protected component, or a ball-like word left as a component after pass A, when unique.
- **Box abuts body** — rect overlap, or gap ≤ `box_abut_tolerance` (10 pt).
- **`pin_assignment_threshold`** — default 50 pt. **`refdes_search_radius`** — default 100 pt. **`REFDES_OUTLINE_MAX_GAP`** — 30 pt. **`PASSIVE_TERMINAL_RADIUS`** — 40 pt. **`STUB_LABEL_OFFSET`** — 10 pt.

## Appendix B — Key locations (HEAD `a23fad1`)

| What | Where |
|---|---|
| Piece-Part / Functional token loops | `refdes_test/nextgen_engine.py:1904-2081` / `:1867-1901` |
| `find_parent_refdes`; Functional skip; passive-prefix drop | `nextgen_engine.py:1757-1829`; `:1831-1836`; `:2015-2029` |
| Whole-body suppression with the pinlist exception | `nextgen_engine.py:2039-2046`, `:2057-2064` |
| Pin lookup; singleton acceptance | `nextgen_engine.py:1609-1611`; `:2003-2005` |
| Page RefDes candidates | `nextgen_engine.py:1645-1653` |
| UNGROUPED (NextGen / legacy) | `nextgen_engine.py:1398-1479` / `extraction_engine.py:1198-1206` |
| Routing: early exit; non-adaptive pages; adaptive filter | `nextgen_engine.py:981-983`; `:1211-1216`; `:1094` |
| Pinlist: qualification gate; cluster branch; membership filter | `nextgen_engine.py:1700-1712`; `:1946-1996`; `:2083-2092` |
| Token diagnostics; fold; orphan vocabulary; BOM collision | `nextgen_engine.py:1280-1287`; `:1326-1340`; `:1289-1300`; `:1363-1395` |
| Pin-map (de)serialization | `nextgen_engine.py:385-420` |
| Gate config, trigger, suppression, metrics | `extraction_engine.py:110-145`, `:1805-1836`, `:1839-1866`, `:1752-1797` |
| `_disambiguate_pin_mapping`; legacy token loop | `extraction_engine.py:1680-1720`; `:1440-1500` |
| Legacy orchestration; diagnostics; forced/fallback branches | `refdes_extractor_logic.py:1096-1104`, `:1136-1140`, `:1417-1421`; `refdes_test_logic.py:340-344`, `:357-361`, `:427-431` |
| Geometry: `PinMapping`; bodies; dedup; ticks; alignment; tolerance | `geometry_analyzer.py:374-381`; `:840-912`; `:923-965`; `:1012-1092`; `:1108-1128`; `:81` |
| Geometry: distances; classifier; text pins; RefDes-to-body; mappings | `geometry_analyzer.py:1455-1476`, `:1499-1535`; `:1537-1632`; `:1733-1815`; `:1993-2066`; `:2100-2158` |
| Group detection; mode suffix; config; prefixes | `group_detection.py:257-380`; `refdes_extractor_logic.py:285-314`; `runtime.py:52-78`; `common/refdes_utils.py:32-97`, `:173` |
| Pinlist parenting | `pinlist_parenting.py` (`:68-73`, `:78-82`, `:549-593`, `:838-856`, `:949-953`) |

## Appendix C — Probe scripts (scratch, not committed; Increment 0 turns them into fixtures and tests)

Run from `backend/python` with the project venv.

1. `isinstance(fitz.Point(1,2), (tuple, list))` → `False`.
2. **Representation probe:** 240 × 380 body as `draw_rect` / four `draw_line` / open zigzag; 10 pt ticks with `Point` endpoints (variant: 8 pt straddling); `C4 A7 B7` outside, `PD`/`REFIO` inside, `U2` at the centre, a far genuine `C4`. Results: §2.11 G1–G3.
3. **Ownership probe (round 2):** `U2` 10 pt above the outline → `PIN_LABEL`, body unnamed. With `U2000` at the centre: `B8`; `1`/`2` at x≈564/580 with `R29` at x≈612; genuine `C4` + `0.1uF` 30 pt out; interior `BUSY` → `U2000-B8, -1, -2, -C4, -BUSY`.
4. **Predicate probe:** `is_pin_candidate` / `REFDES_RE` / `should_analyze_pins` on `BUSY PD CNV VIO REFIO H7 G7 C4 B7 U3 C7 1 2 12D7`; `_is_blacklisted` on `NC GND 5V 3.3V VCC X DNP`.
5. **Round-3 probe:** `R29` at x≈569 with `1`/`2` at x≈562/578 beside edge x=540 → `U2000-1, U2000-2, U2000-R29`. Dynamic radius for the 240 × 380 body = 134.83; distance from the centre to a label at (306,140) = 230.21, biased 184.17. Nested rects `(200,100,700,580)` and `(300,150,540,530)` → two bodies.
