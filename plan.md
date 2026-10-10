# plan.md — S007 OSS Caption-Animation Overdrive

- STATUS: ACTIVE
- DATE: 2026-10-10
- ACTIVE UNIT: OSS-002
- PRODUCT MODE: SPEEDRUN
- PRIORITY: visible production fidelity, not detector-framework perfection

## Outcome

Replace the frozen custom caption-animation detection route with the strongest proven OSS mechanisms we can reuse/adapt quickly, while keeping the already-proven editable Resolve carrier.

The next visible milestone is:

> high-coverage, compound caption animations on Reel #3 that are editable in Resolve and pass one batch human visual review.

## Frozen Evidence — DONE

- OSS-001 nested Text+ carrier: PASS.
- `sub_008` live editable animation application: PASS.
- Existing Step 3C custom plan: 16 selected captions (10 scale / 6 slide / 0 scale_pop).
- Human batch review: REJECTED for production fidelity/coverage.
- Root limitation: systematic misses plus representation mismatch; source animations frequently combine motion and size change.
- Decision: preserve custom detector artifacts, but do not tune/re-canary them.

## Step 1 — OSS Capability Spike — ACTIVE

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

## Step 2 — Same-Evidence Benchmark

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

## Step 3 — Resolve Adaptation

Keep the OSS-001 carrier frozen.

Map the winning OSS animation representation into editable Resolve Text+/Fusion channels.

Rules:

- no new carrier;
- no global identity theorem;
- no per-caption micro-canaries;
- one bounded representative application, then batch;
- preserve original captions reversibly until batch verification;
- application must support independent transform channels required by the source.

## Step 4 — Batch Human Review

Apply the OSS-backed caption animation layer across Reel #3 and review as one batch.

Review:

- coverage;
- missed animations;
- false positives;
- compound transform fidelity;
- timing;
- direction;
- magnitude;
- obvious visual mismatch.

If usable: close OSS-002 immediately.

If not usable: compare the second proven route/composition. Do not return to the frozen custom detector.

## Step 5 — OSS-003 Transitions

Immediately after OSS-002 acceptance:

- reuse/adapt the strongest proven transition mechanism from the existing research queue;
- prioritize source-visible transitions;
- batch review;
- no unrelated refactors.

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
