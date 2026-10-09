# P005 — PH2 Advanced TextPlus Caption Fidelity — SPEEDRUN

- PLAN ID: `P005_PH2_ADVANCED_TEXTPLUS_CAPTION_FIDELITY`
- STATUS: **READY_FOR_CODEX**
- PHASE: **PH2 — FEATURE / PRODUCTION**
- MODE: **SPEEDRUN — SHIP BY END OF WEEK**
- BASELINE: accepted repository state containing P004 T001 + retained Reel #2 caption authorities
- PREDECESSOR: `P004_RESOLVE_REPOSITORY_IDENTITY_AND_PERSISTENCE_UNBLOCK` — **SUPERSEDED / PRE-SHIP DEFERRED**
- WORKER GATE: **T001 AUTHORIZED NOW**

## Win Condition

Produce a **real, deterministic, reviewable caption production package** from the retained Reel #2 caption baseline using the canonical Video Cloner caption pipeline — not a new caption system.

T001 PASS requires a real Reel #2 offline output package (FCPXML + report/evidence) in which the existing canonical caption path demonstrably reuses accepted semantic text, lifecycle, static style/position, font authority and accepted motion where evidence exists, with no dropped/duplicated caption coverage and no unrelated regression.

The fastest acceptable route wins. If the existing path already produces the package correctly, **do not modify code**.

## Why Now / Current Bottleneck

The project tracker already marks PH2 as **Retain / Reuse / Improve** and explicitly says the Reel #2 caption lifecycle/GOLD baseline exists and must not be rebuilt.

The repository already contains:

- retained Reel #2 GOLD identity/hash evidence;
- `config/DcJRJtUKScu.accepted_caption_motion.json`;
- `config/DcJRJtUKScu.accepted_human_static_style_adjudication.json`;
- `config/DcJRJtUKScu.accepted_lifecycle_end_correction.json`;
- display/position recovery authorities;
- Step 3C animation and Step 3D lifecycle mechanisms;
- font inference;
- canonical `video_cloner/captions/{textplus,lifecycle,fcpxml}.py`;
- caption grammar and extensive focused tests.

Therefore the bottleneck is **production caption fidelity**, not Git/persistence plumbing.

## Speedrun Rules

1. **REUSE > ADAPT > SMALL FIX. Never rebuild captions.**
2. No OSS scan, architecture redesign, Git identity work, persistence work, cleanup, refactor or generic framework work before the caption preview exists.
3. No source change unless a concrete observed gap blocks the T001 production package or an accepted caption authority from being applied.
4. Any code change must be the smallest canonical fix and remain generic — no production logic branching on Reel ID, literal caption text, or human-choice IDs.
5. Unknown visual properties remain unknown; do not invent fidelity.
6. Existing working caption behavior/regression must remain green.

## T001 — Build the Caption Production Preview Package — AUTHORIZED

### Action

Run the existing canonical caption pipeline on the real retained Reel #2 evidence and generate a production-ready offline caption/FCPXML package suitable for the next live visual preview.

First inspect/reuse, in this order:

- `video_cloner/captions/textplus.py`
- `video_cloner/captions/lifecycle.py`
- `video_cloner/captions/fcpxml.py`
- `video_cloner/caption_grammar.py`
- existing canonical Resolve/FCPXML compiler surfaces
- retained `DcJRJtUKScu` accepted config authorities
- existing Step 3C/3D mechanisms only where already consumed by the canonical path

Do not create a parallel caption engine.

### Fidelity that must be represented when source authority exists

- semantic/display text authority;
- exact caption source coverage and ordering;
- lifecycle/timing, including accepted lifecycle corrections;
- font family/style/weight authority;
- size and position/anchor;
- fill / gradient / opacity where accepted;
- stroke/shadow where supported by retained authority;
- multiline/layout behavior when existing authority supplies it;
- accepted scale/slide/motion keyframes where explicitly supported;
- static captions remain static when motion evidence is absent/ambiguous.

### Allowed implementation surface if — and only if — a real gap is found

Prefer no edits. If required, edits are limited to the smallest relevant canonical caption/compiler files and directly corresponding tests:

- `video_cloner/captions/textplus.py`
- `video_cloner/captions/lifecycle.py`
- `video_cloner/captions/fcpxml.py`
- `video_cloner/caption_grammar.py`
- `video_cloner/resolve/fcpxml.py` only if the observed gap is in canonical title/FCPXML emission
- directly relevant caption tests only

If fixing the observed gap requires broader architecture/public API/dependency changes: STOP and report the exact blocker. Do not broaden scope.

### Required production evidence

Produce one T001 report plus the actual generated caption/FCPXML artifact(s). The report must state:

- exact real input authorities used;
- output paths/hashes;
- caption/source coverage counts;
- lifecycle authority counts;
- style/font authority counts;
- animated vs static caption counts;
- unresolved properties honestly retained as unresolved;
- focused tests/regression run;
- code files changed, if any;
- whether the package is ready for one Resolve visual preview.

### Acceptance

T001 is accepted when:

- a real Reel #2 caption package is generated successfully;
- semantic source coverage is exact — no dropped, duplicated or reordered source cues;
- generated timing/lane structure validates;
- retained accepted static style/font/position authorities are consumed where applicable;
- accepted motion/lifecycle authorities are consumed where applicable;
- ambiguity fails closed rather than fabricating style/motion;
- relevant tests pass;
- no Git/persistence/PH1 plumbing work is performed.

Then STOP for a **visual-production gate**, not another architecture review.

## T002 — One Resolve Caption Preview + Human Review — NOT YET AUTHORIZED

Import/apply the T001 caption package once through the existing safe mechanism and obtain human APPROVE/REJECT on caption fidelity. Review only visually material dimensions: font, weight, size, stroke, opacity/fill, position, multiline layout, lifecycle timing and motion/easing.

## T003 — One Bounded Fidelity Repair — CONDITIONAL

Only if T002 is REJECT: fix the highest-value visible caption deltas in one bounded iteration, regenerate, and re-review. No endless per-caption patch loop.

If T002 is APPROVE, skip T003 and freeze PH2 caption baseline.

## PRE-SHIP DEFERRED — NOT CURRENT WORK

Before final product release, we still owe:

- P004 save/reopen persistence proof;
- repository identity live proof;
- same-target second-run/idempotency acceptance;
- final full-target human acceptance / ship certification.

These do **not** block caption production now.

## STOP / KILL RULES

- Do not reopen P004 while working P005.
- Do not create a new caption subsystem.
- Do not research tools/libraries unless direct evidence proves the retained stack cannot achieve the required caption result.
- Do not spend a task on Git hygiene/tracker synchronization/process cleanup.
- If a task does not make the visible caption output better or directly enable its production preview, it is not on the Critical Path.
