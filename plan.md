# plan.md — S007 OSS-004 Core Motion/VFX Speedrun

- STATUS: ACTIVE
- DATE: 2026-10-11
- ACTIVE UNIT: OSS-004
- PRODUCT MODE: SPEEDRUN
- PRIORITY: visible production fidelity, not detector-framework perfection

## Outcome

Turn the existing Reel #3 transition evidence into editor-independent recipes and prove a small editable Resolve batch without reopening cuts or captions.

The next visible milestone is:

> high-coverage, compound caption animations on Reel #3 that are editable in Resolve and pass one batch human visual review.

## Frozen Evidence — DONE

- OSS-001 nested Text+ carrier: PASS.
- `sub_008` live editable animation application: PASS.
- Existing Step 3C custom plan: 16 selected captions (10 scale / 6 slide / 0 scale_pop).
- Human batch review: REJECTED for production fidelity/coverage.
- Root limitation: systematic misses plus representation mismatch; source animations frequently combine motion and size change.
- Decision: preserve custom detector artifacts, but do not tune/re-canary them.

## Step 1 — OSS Capability Spike — DONE

Use existing vetted research before any new broad research.

Primary pool:

1. `heygen-com/hyperframes@46f6cb356785bed79e1ce7b79d7e7accc697786a` — Apache-2.
2. `kurbaitaev/ghost-editor@9f197e4e65691d190ba63efa6c061d9c43f02cf6` — MIT.
3. video-style-kit / EditDNA patterns already recorded in the research file.
4. Remotion only if its commercial/custom license is explicitly acceptable for the required component.

For each serious candidate, inspect actual code paths and answer only:

- Does it detect/derive animation from reference evidence, or only render supplied animation?
- What reusable representation does it expose: transform curves, keyframes, recipes, caption identities, motion primitives?
- Can it express compound transforms (translation + scale at minimum)?
- Can we reuse/adapt it quickly and legally?
- How does it map into our proven Resolve carrier?

Do not equate popularity with capability.

Result: HyperFrames is representation/render infrastructure; ghost-editor is LLM-assisted analysis plus recipe rendering. Neither directly derives deterministic reference-video transform curves.

## Step 2 — Same-Evidence Benchmark — DONE

Benchmark no more than the two strongest compatible routes/compositions on Reel #3.

Use:

- the same source timestamps/frames;
- captions where custom detection missed obvious motion;
- examples with combined movement + size change;
- human visual evidence as ground truth.

Score:

- coverage / missed animations;
- classification/recipe correctness;
- translation direction and amplitude;
- scale timing/amplitude;
- compound motion support;
- integration cost;
- license/runtime risk.

Select `REUSE / ADAPT / COMBINE / REPLACE`.

Stop research when more information is unlikely to change the winner.

Result: OpenCV LK affine `57.4/100` (2/5 cases) versus multi-scale edge-template tracking `89.8/100` (5/5). Decision: **COMBINE** the template extractor, independent normalized channels, and OSS-001 carrier.

## Step 3 — Resolve Adaptation — READY

Keep the OSS-001 carrier frozen.

Map the winning OSS animation representation into editable Resolve Text+/Fusion channels.

Rules:

- no new carrier;
- no global identity theorem;
- no per-caption micro-canaries;
- one bounded representative application, then batch;
- preserve original captions reversibly until batch verification;
- application must support independent transform channels required by the source.

Implemented and focused-tested for position, scale, simultaneous position+scale, bounded placement, exact rollback, and accepted `sub_008` preservation. One four-caption production command is pending; Codex does not execute it.

## Step 4 — Representative Human Review — DONE

Human accepted the four-caption OSS-backed batch as materially closer to source. Motion extraction is closed to further route benchmarking.

Review:

- coverage;
- missed animations;
- false positives;
- compound transform fidelity;
- timing;
- direction;
- magnitude;
- obvious visual mismatch.

## Step 5 — Full Reel #3 Motion Rollout — DONE

- Authority: 112 captions; 56 meaningful-motion; 56 static/no-motion; 32 explicit extraction failures.
- Preserve accepted `sub_008` plus representatives `sub_009`, `sub_012`, `sub_015`, `sub_026`.
- Supersede 11 rejected Step 3C replacements with OSS motion; remove 4 rejected static replacements and re-enable originals.
- Expected final state: 56 authoritative V3 replacements, no duplicate ordinal, no rejected Step 3C item, one save after complete verification.
- Live run `20261010T105509634Z_5d7d0cc58b344d24a62f0fee7795f9e0` persisted the 56/56 reconciliation and passed save verification.
- Human review: detected motion is substantially closer to source; remaining coverage gap is concentrated in localization.

## Step 6 — OSS-002B Localization Coverage Recovery — STOPPED / NO WINNER

- Audited only PaddleOCR `3.3.2` and EasyOCR `1.7.2`, both Apache-2.0.
- Same-evidence benchmark: 12 real failed captions / 36 anchor frames.
- Candidate text detection: PaddleOCR 35/36 anchors; EasyOCR 33/36.
- Correct expected-caption selection: 0/12 for both; downstream tracker recovery: 0/12 for both.
- Root cause: the expected V2 token is generally not the baked text visible at the same frame, so OCR cannot supply the missing cross-authority association.
- Decision: adopt neither; keep the primary localization and accepted tracker unchanged; do not run all 32 or publish a Resolve batch.
- Evidence: `data/DZatr0EJt4B/analysis/DZatr0EJt4B_oss002b_text_localization_benchmark.json`.

## Step 7 — OSS-002C Final Recovered-Motion Delta — DONE / FROZEN

- Tiny BUILD authorized and complete: bounded token/phrase lattice plus timing, spatial, style, and persistence scoring over existing PaddleOCR/EasyOCR detections.
- Same 12-case gate passed for both backends at 11 correct / 0 accepted false / 1 ambiguous; PaddleOCR selected on tracker-confidence/runtime tie-break.
- Full 32 pass recovered 26 associations: 13 meaningful motion under unchanged thresholds, 13 static, 5 ambiguous, 1 visually rejected logo, and 18 lifecycle composition proposals.
- Seven-caption run `20261011T075523823Z_9505c20c898e475abcd84880e4420ffb` completed and persisted ordinals `5, 37, 54, 75, 80, 101, 107`; human review accepts the result as approximate but useful.
- Canonical meaningful-motion reconciliation: 13 total = seven accepted live representatives + six missing ordinals `53, 78, 79, 87, 88, 108`. Recovered-static 13 and unsupported six remain original/static.
- Run `20261011T091036387Z_d111541339de4973b185c41e30bebedb` completed and persisted the final six replacements while preserving the existing 63.
- Human decision: OSS-002 is MVP accepted, production-ready, and frozen. Defer lifecycle/persistence and all caption polishing.

## Step 8 — OSS-003 Transitions — MVP ACCEPTED / FROZEN

- Human review and independent DRT inspection accepted exactly three native 11-frame Blur Dissolves at boundaries `80`, `286`, and `376` in `VIDEO_CLONER_DZatr0EJt4B_MVP_V1__OSS003_TRANSITIONS_V1`.
- Reject the clip-level Fusion approximation: it produced no native transition object. Preserve that result as a warning and do not tune it again.
- Reuse pinned Resolve MCP DRT insertion plus the Resolve-authored Blur Dissolve donor to create exactly three native transitions at `80`, `286`, and `376`, each duration `11`, in final derivative `VIDEO_CLONER_DZatr0EJt4B_MVP_V1__OSS003_TRANSITIONS_V1`.
- Preserve production, V1 cuts, V2/V3 captions, and A1 by compact count/hash verification. Experimental `VC_OSS003_` Fusion effects remain non-blocking debt; no delete/bypass loop is authorized.
- Classify slides `211` / `629` and whip `461` as motion/VFX deferred to OSS-004.
- OSS-003 is production-ready and frozen. Do not reopen transition research, donor work, Fusion transition simulation, or blur tuning.

## Step 9 — OSS-004 Core Motion / VFX — ACTIVE

- Baseline: accepted OSS-003 derivative UID `75c9bc1b-ef1b-4463-9d7f-0ccb4b41e2b1`.
- Use existing canonical evidence only. Mandatory representative targets are `211`, `461`, and `629`; add at most two strong shot-level scale/compound-motion examples.
- Normalize source-backed position/scale/blur channels separately from Resolve graph details. Apply through minimal clip-local Fusion graphs and keyframe only inside live local comp ranges.
- Preserve cuts, A1, V2/V3 captions, three native Blur Dissolves, media timing, and timeline duration. Speed/retiming remains deferred to OSS-005.
- Five review targets: shot 1 pull-out; boundary 211 incoming slide; shot 4 push-in/right-down reframe; boundary 461 paired whip; boundary 629 incoming slide. The paired whip owns two clip-local comps, so six owned comps are expected.
- Published derivative command `20261011T144031710Z_fb34ba5ed4974dadaaf2dd39c296aa62` for `VIDEO_CLONER_DZatr0EJt4B_MVP_V1__OSS004_MOTION_VFX_V1`; stop for human batch review.

Then proceed to OSS-004 motion/VFX and OSS-005 speed ramps.

## Build Gate

Greenfield detector work is forbidden unless:

1. the strongest two compatible proven OSS routes have been tested on the same evidence;
2. both fail a named product requirement;
3. the missing mechanism cannot be obtained by combining existing components.

Even then, build only the missing mechanism.

## Future Input Adapter Track — QUEUED

After the current Reel #3 visual baseline is usable, add source adapters for:

- reference videos / frame windows;
- CSS/JS/GSAP;
- pure code;
- GIF / frame sequence;
- short partial-animation MP4/GIF;
- Resolve templates/timelines/project artifacts.

Normalize these to a common animation recipe, then apply through editor adapters. This is intentionally not on the current critical path.
