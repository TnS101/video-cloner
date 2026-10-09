# plan.md — S006 Reel #3 Core Style Reproduction

- STAGE ID: `S006_REEL3_CORE_STYLE_REPRODUCTION`
- STAGE NAME: Reel #3 advanced captions + transitions + core motion/VFX
- STATUS: `READY`
- MODE: `PRODUCTION`
- ACTIVE REEL: `DZatr0EJt4B`
- ACTIVE TARGET: `VIDEO_CLONER_P001_DZatr0EJt4B_20261007_4CE37F9BC61B`
- TARGET UID: `4aaa91c0-c434-4439-a15a-92ce86e80256`
- DEFAULT RISK: `R1`
- DEFAULT REPAIR BUDGET: 3 focused repair cycles per step

> This is one meaningful production stage. Do not create a new Plan/session after each test failure, visual correction, or local repair.

## 1. Human-Set Outcome

Reel #3 should have a credible baseline reproduction of the editor's core style:

- existing basic captions preserved;
- source-supported advanced caption animation applied;
- cuts preserved;
- supported transitions applied;
- at least the highest-value source-backed core motion/VFX behavior applied;
- integrated result ready for human judgment.

After this baseline, the next stage is the human-mandated OSS research/reuse expansion layer.

## 2. Production Value

- WIN CONDITION CONTRIBUTION: converts existing analysis/Resolve infrastructure into source-visible editing behavior.
- CURRENT BOTTLENECK: advanced caption animation on Reel #3.
- WHY NOW: basic captions and cuts already exist; animation is the closest missing visible style layer.
- KILL TEST: if a proposed task does not improve Reel #3 visible fidelity or directly enable the next visual preview, it is not on this stage's Critical Path.

## 3. Accepted Baseline / Preserve

Preserve:

- active Reel #3 only;
- existing target timeline + UID;
- 112/112 existing Text+ overlay baseline;
- caption Rich Text, timing, font, static style and unaffected position;
- existing cuts/shot structure unless direct regression evidence appears;
- canonical public pipeline/CLI;
- Resolve queue/bridge boundary;
- protected historical/GOLD fixtures.

Do not regenerate basic captions.

## 4. IN Scope

- generic command-bound Reel #3 caption animation plan/application;
- persistent Text+ animation mechanisms already proven by project history;
- human visual review and bounded fidelity repair;
- existing transition detection/authority/application on Reel #3;
- highest-value source-backed core motion/VFX family for Reel #3;
- focused tests/reproduction directly needed for those outputs.

## 5. OUT of Scope

- Reel #2 production;
- basic caption rebuild;
- persistence/Git certification until pre-ship;
- generic architecture rewrite;
- broad refactor/cleanup;
- speculative VFX not evidenced in Reel #3;
- broader ecosystem/OSS expansion before this basic style baseline is working.

## 6. Worker Autonomy

Codex MAY:

- choose normal implementation details;
- inspect Reel #3 data/evidence;
- modify directly relevant caption/transition/motion application code and focused tests;
- perform up to 3 focused repair cycles per step;
- fix directly blocking adjacent defects inside this stage boundary;
- continue to the next R1 step without a new Browser/Codex session.

Codex MUST escalate for:

- active Reel/target/objective change;
- architecture boundary change;
- material new dependency;
- destructive/live Resolve action requiring human approval;
- conflicting unowned tracked changes overlapping needed files;
- exhausted repair budget.

## 7. Stage Steps

| Step | Risk | Production Result | Done When | Human Gate | Status |
|---|---|---|---|---|---|
| 1 | R1 | Generic Reel #3 advanced caption-animation payload + adapter | legacy Reel #1 hardcoding/count assumptions removed from execution path; source-supported Reel #3 animations prepared; focused tests pass | NO | ACTIVE |
| 2 | R2 | Apply animations once to existing Reel #3 target | existing target receives only authorized animation mutations; human watches and returns visible deltas | YES | TODO |
| 3 | R1/R2 | Reel #3 transitions | supported source-backed transitions are applied via existing mechanism and visually reviewed | YES | TODO |
| 4 | R1/R2 | Core motion/VFX | highest-value real Reel #3 effect family (e.g. ramp/zoom/whip/other evidence-backed winner) is executable and reviewed | YES | TODO |
| 5 | R2 | Integrated Reel #3 visual acceptance | human confirms the basic components behave credibly enough to freeze this baseline | YES | TODO |

Cuts are already baseline behavior; do not create a separate cut-rebuild step unless a regression is observed.

## 8. Caption Animation Step 1 — immediate work

Reuse existing mechanisms, especially:

- `scripts/davinci/caption_animation_step_3C.py`
- `resolve_workspace/resolve_apply_caption_animation_step_3C.py`
- `tests/test_step4b_resolve_caption_animation_adapter.py`
- existing Reel #3 analysis/grammar/motion artifacts.

Required behavior:

- remove Reel #1-specific execution assumptions such as fixed `DZsqH7auhjt` / fixed 116-caption contract;
- bind video ID, target timeline, target UID, animation plan and expected caption identity/count through generic runtime/command inputs;
- accept the existing Reel #3 112-overlay baseline;
- preserve caption text/timing/static style;
- animate only source-supported events;
- static/ambiguous captions remain untouched;
- reuse persistent Fusion mechanisms (e.g. Size -> BezierSpline, Center -> Path) where already proven;
- prepare one directly applicable artifact/command for Step 2;
- do not perform the live Resolve mutation during Step 1.

## 9. Verification

Use the smallest evidence that proves behavior:

1. focused tests for the changed caption/transition/motion path;
2. real Reel #3 artifact/payload generation;
3. affected regression for protected caption/static behavior;
4. live Resolve readback only at R2 steps;
5. human visual review for perceptual acceptance.

Do not substitute broad green suites for broken real output.

## 10. Reporting

- R1 work: short Codex result only.
- R2 live steps: durable report/evidence if useful.
- Stage close: update `PROJECT_STATE.md` + tracker once and checkpoint Git.

Do not create a report-only success.

## 11. True Block Conditions

Block only for:

- missing required Reel #3 input/evidence;
- architecture/material dependency decision;
- conflicting overlapping unowned tracked work;
- unavailable external permission/credential;
- unsafe irreversible action;
- no safe path after repair budget.

Do not block on harmless untracked report directories, Excel lock files, stale session labels, mid-stage tracker lag or optional tools.

## 12. Stage Exit

Stage COMPLETE when:

- Reel #3 advanced caption animation is visibly present where source-supported;
- existing captions/cuts remain acceptable;
- source-backed transitions are visibly represented where supported;
- at least the highest-value core motion/VFX gap is executed;
- integrated human review accepts the basic style baseline.

NEXT STAGE (mandatory): targeted OSS research/reuse expansion from the project tracker before broader content-automation functionality.
