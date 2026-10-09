# P005 — Production Vertical Slice Speedrun

- PLAN ID: `P005_PRODUCTION_VERTICAL_SLICE_SPEEDRUN`
- STATUS: **READY_FOR_CODEX**
- MODE: **FEATURE / PRODUCTION ONLY**
- DEADLINE: **SHIP THIS WEEK**
- CURRENT AUTHORIZATION: **T001 ONLY**

## Win Condition

Produce one **real editable Reel #2 output package** that combines the strongest working production path for:

1. cuts / shot structure;
2. executable transitions already supported;
3. captions with the highest deterministic fidelity currently recoverable;
4. motion/VFX detection manifest for ramps, zooms, whips/slides and caption animation combos.

The artifact wins. Reports exist only to explain what the artifact contains.

## Existing Leverage — Reuse, Do Not Rebuild

- cuts: `video_cloner/analysis/cuts.py`
- transitions: `video_cloner/analysis/transitions.py`
- transition execution/policy + flash path
- motion analysis: `video_cloner/analysis/motion.py`
- caption stack: `video_cloner/captions/*`
- retained Reel #2 caption authorities and grammar
- existing Step 3C/3D caption motion/lifecycle mechanisms
- existing focused tests for captions, transitions, speed-ramp/zoom authority and flash

Known reality:
- hard cuts already work;
- flash transition has an executable authority path;
- whip/slide detection exists but current MVP policy demotes it;
- speed-ramp/zoom candidates exist but current planner intentionally keeps heuristic-only candidates non-actionable;
- caption T001 failed because the legacy style file has 0 visual IDs while retained grammar/authorities contain identity-bound evidence.

## Speedrun Rule

The caption identity mismatch is a **bounded sub-fix**, not a new project.

Do not block the whole production slice because one optional identity-bound authority cannot resolve.

For the preview package:
- apply every authority that can be deterministically authenticated;
- preserve core semantic/timing coverage;
- mark unresolved identity-bound fidelity explicitly;
- skip only the unresolved rows;
- never invent mappings.

A missing optional style/motion authority may reduce fidelity, but it must not prevent generating the baseline production artifact if the core caption package can remain structurally valid.

## T001 — Integrated Production Slice — AUTHORIZED

### Goal

Generate the real Reel #2 editable package plus a machine-readable production manifest showing:

- cut/shot count;
- executed transition families/counts;
- detected-but-not-executed transition candidates;
- caption source coverage;
- applied vs unresolved caption style/lifecycle/motion authority;
- speed-ramp candidates;
- zoom candidates;
- other detected motion/VFX candidates;
- caption animation families/combos present in source evidence.

### Caption blocker handling

First try the smallest deterministic bridge between retained Reel #2 grammar/accepted authorities and the legacy style input.

Allowed join evidence must be explicit, e.g. shared cue/event IDs, retained visual identity fields, exact source-evidence references, or exact canonical windows already present in retained artifacts.

Forbidden:
- fuzzy text matching;
- approximate timing guesses;
- Reel-ID-specific production branches;
- hardcoded caption literals;
- fabricated identity reconstruction.

If some accepted rows still cannot bind, continue the preview with those rows marked `UNRESOLVED_NOT_APPLIED` rather than failing the entire package, provided semantic coverage/timing remain valid.

### Cuts / transitions / VFX

Run the existing real Reel #2 analysis/planning path.

- preserve hard cuts;
- execute supported high-confidence transition authority already implemented;
- retain unsupported whip/slide as candidates unless a small existing generic path already promotes them safely;
- emit speed-ramp/zoom candidates from existing analysis;
- do NOT invent retime/zoom execution from heuristics alone;
- identify actual source-backed high-value effect families present in Reel #2 for the NEXT bounded implementation step.

The task is not to implement every VFX family. It is to produce the first integrated artifact and expose the actual highest-value missing executable family.

### Allowed code changes

Only if needed to produce the artifact:

- smallest relevant canonical caption files;
- smallest relevant planning/compile/transition adapter files;
- directly corresponding tests.

No dependencies, no architecture rewrite, no Git/persistence work, no cleanup/refactor mission.

### PASS

T001 passes when:

- one real editable output package is generated;
- caption semantic source coverage is exact;
- caption lifecycle/lane structure validates;
- resolvable caption authorities are applied;
- unresolved identity-bound rows are listed, not guessed;
- cut structure is present;
- supported transitions are compiled;
- detected motion/VFX candidates are summarized;
- relevant focused tests pass;
- output is ready for one Resolve visual review.

Then STOP.

## T002 — One Real Resolve Visual Review — NOT YET AUTHORIZED

One import/render/review of the integrated slice.

Review:
- cuts/pacing;
- transitions;
- captions: font/weight/size/position/stroke/fill/opacity/timing/motion;
- whether detected ramps/zooms/whips/slides matter visually enough to implement next.

## T003 — Highest-ROI Production Repair — CONDITIONAL

Only one bounded repair after visual evidence.

Choose the single biggest visible gap:
- caption identity/fidelity;
- ramp execution;
- zoom execution;
- whip/slide execution;
- animation combo handling;
- another source-backed effect actually visible in the reel.

No roadmap loop.

## PRE-SHIP

Persistence/idempotency/final certification remain release gates but are not current production work.
