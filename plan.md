# P006 — Reel #3 Advanced Caption Animation + Transitions Speedrun

- PLAN ID: `P006_REEL3_ADVANCED_CAPTION_ANIMATION_TRANSITIONS_SPEEDRUN`
- STATUS: **READY_FOR_CODEX**
- MODE: **FEATURE / PRODUCTION**
- DEADLINE: **SHIP THIS WEEK**
- ACTIVE REEL: **Reel #3 — DZatr0EJt4B**
- CURRENT TARGET: `VIDEO_CLONER_P001_DZatr0EJt4B_20261007_4CE37F9BC61B`
- TARGET UID: `4aaa91c0-c434-4439-a15a-92ce86e80256`

## What Is Already Done

Do NOT rebuild basic captions.

Reel #3 already has:
- completed offline analysis/planning artifacts;
- generated caption style + caption grammar;
- existing imported/reviewable Resolve target timeline;
- basic Text+ caption application already in place;
- P002 structural validation of 112/112 overlays.

The next production step is **advanced caption animation**, then **transitions/VFX**.

Reel #2 is reference/reuse evidence only. It is NOT the active production target.

## T001 — Reel #3 Caption Animation Production Plan + Generic Adapter — AUTHORIZED

Goal:
Use Reel #3's existing caption analysis/grammar and existing target captions to prepare the actual advanced animation payload for Reel #3.

Reuse:
- `scripts/davinci/caption_animation_step_3C.py`
- `resolve_workspace/resolve_apply_caption_animation_step_3C.py`
- `tests/test_step4b_resolve_caption_animation_adapter.py`
- existing caption motion/animation logic

Important:
- the old Resolve Step 3C script is hardcoded to Reel #1 (`DZsqH7auhjt`); genericize/adapt it minimally for command-bound Reel #3 inputs rather than cloning/rebuilding it;
- preserve the existing Reel #3 captions exactly;
- do not regenerate captions;
- do not change caption text, timing, font, size, or position except where animation itself requires animated Size/Center values;
- animate only source-supported Reel #3 events;
- static/ambiguous captions remain untouched.

Required Reel #3 animation families:
- scale;
- slide;
- scale_pop;
- any other family already supported by existing generic production code and actually evidenced in Reel #3.

Output:
- Reel #3 animation plan/payload;
- counts by animation family;
- exact affected caption names/cue IDs;
- focused tests;
- ready-to-apply command/artifact for the existing Reel #3 target.

STOP before live Resolve mutation.

## T002 — Apply Reel #3 Caption Animations + Visual Review — NEXT

After T001 PASS:
apply the prepared animations once to the EXISTING Reel #3 target timeline, save once if required, then human visual review.

No new timeline.
No Reel #2.
No basic-caption regeneration.

## T003 — Reel #3 Transitions / VFX — NEXT AFTER ANIMATION REVIEW

Use Reel #3's existing transition + motion analysis.

Prioritize actual source-backed:
1. executable transitions already supported;
2. speed ramps;
3. zooms;
4. whip/slide/blur/crossfade candidates;
5. animation combos.

Implement only the highest-value real missing family per visual review.

## T004 — Mandatory OSS Research / Reuse Expansion Layer — AFTER BASIC COMPONENT BASELINE

STATUS: **MANDATORY MILESTONE / NOT YET AUTHORIZED**

Trigger only after Reel #3 has a working baseline for:
- captions + advanced animation;
- cuts;
- transitions;
- core motion/VFX reproduction.

Then execute the backlog research layer from `PROJECT_TRACKER.xlsx`:
- research proven OSS/existing projects that already solve remaining editing/automation problems;
- inspect at least 5 materially relevant options when available;
- rank `REUSE / ADAPT / COMBINE / BUILD / IGNORE`;
- evaluate license, maintenance, integration cost, editor/render compatibility, and automation value;
- reuse/adapt proven mechanisms before custom-building equivalents;
- use this layer to expand Video Cloner into the wider content-automation ecosystem.

Do NOT pull T004 forward and derail the current Reel #3 basic-component work.

## Guardrails

- Human commands + Win Condition take precedence; never silently pivot reel/phase/target.
- Follow the current Plan and tracker sequencing; if they conflict with an explicit human command, STOP and surface it.
- Reel #3 only.
- Reel #2 is reference data only.
- No Git/persistence work.
- No basic caption rebuild.
- No new caption architecture.
- No report-only loop.
- No speculative motion.
- Every task must improve the existing Reel #3 target or prepare a directly applicable artifact for it.
