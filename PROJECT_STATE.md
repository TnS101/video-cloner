# PROJECT_STATE.md — Video Cloner Volatile Truth

- LAST UPDATED: 2026-10-10
- ACTIVE STAGE: `S007_OSS_FIRST_PROVEN_CODE_INTEGRATION`
- ACTIVE UNIT: `OSS-002B_LOCALIZATION_COVERAGE_RECOVERY`
- STATUS: `BOUNDED_BENCHMARK_STOPPED / NO_OSS_WINNER`

## Human Directives

- REAL OBJECTIVE: ship a usable Video Cloner by end of week.
- ACTIVE PRODUCTION REEL: `DZatr0EJt4B` (Reel #3).
- ACTIVE RESOLVE PROJECT: `VIDEO_CLONER_REEL3_FREE2104`.
- ACTIVE TIMELINE: `VIDEO_CLONER_DZatr0EJt4B_MVP_V1`.
- ACTIVE TIMELINE UID: `a89f3e7c-50d9-4969-b2b6-b01548b66879`.
- RESOLVE: Free `21.0.4.5` on Windows.
- BASELINE AUTHORITY: `data/DZatr0EJt4B/davinci/DZatr0EJt4B_mvp_timeline.fcpxml`.
- CUTS/AUDIO + 112 Basic Title captions are accepted baseline. Do not reopen cuts unless evidence shows a real failure.
- HARD DEVELOPMENT LAW: `REUSE > ADAPT > COMBINE > BUILD`.
- HARD 2026-10-10 DIRECTIVE: the current custom caption-animation detection/analysis route is **FROZEN / REJECTED FOR PRODUCTION**. Preserve it as evidence; do not tune it further.
- The proven Resolve Text+ carrier remains accepted and must not be conflated with the rejected detector.

## Win Condition

Analyze a reference video and reproduce the editor's core visible behavior into an editable clone:

1. captions + caption animations;
2. cuts;
3. transitions;
4. core motion / VFX;
5. speed/retiming where present;
6. reusable style/animation authority that can generalize beyond one Reel.

The near-term win is not perfect reconstruction. It is a visibly credible, editable clone built with the fastest proven mechanisms.

## Current Position

### Proven / keep

- Reel #3 baseline is live in the official Resolve environment.
- Canonical Reel #3 analysis artifacts survived cleanup; manifest integrity audit previously returned 23/23 exact hashes.
- `OSS-001` carrier is **PASS / INTEGRATED** using:
  `samuelgursky/davinci-resolve-mcp@94c7a885d53f13be78522ce96561a9e9e21d64c5` (MIT).
- Proven carrier primitive:
  native Text+ -> owned source timeline -> source MediaPoolItem -> exact `AppendToTimeline` placement -> placed MediaPoolItem -> `GetTimeline()` -> inner editable Text+.
- Live run `20261010T070036510Z_01093b6b3bcb4cc996a8844ee181fe34` proved that an existing animation-plan entry can be turned into persisted editable Resolve motion. `sub_008 = "this"` visibly slides and was human-accepted as fidelity-approximate.
- This proves the **application/execution layer works**.

### Human-rejected / freeze

The existing custom caption-animation detector / Step 3C plan is frozen for production.

Human batch review established:

- it selected only 16 caption animations out of a source containing visibly many more;
- many real animations are missed;
- the simple `scale` / `slide` taxonomy does not represent common combined behavior such as translation + scale;
- the applied batch is not close enough to 1:1 to justify further tuning;
- execution success on `sub_008` isolates the bottleneck upstream: **coverage + representation + animation understanding**, not the Resolve carrier.

Existing custom artifacts remain useful as regression evidence and historical ground truth, but receive no more production tuning.

## Main Constraint

Find the fastest proven OSS route that materially improves:

- animation coverage;
- composable motion representation;
- fidelity to reference;
- editable application in Resolve.

Do not spend another loop improving the rejected heuristic detector.

## Accepted Production State — OSS-002 Full Motion Rollout

- Source audit proved HyperFrames supplies a seekable independent-channel animation representation/runtime, not reference-video motion detection.
- Source audit proved ghost-editor uses Gemini-authored edit analysis plus GSAP recipes, not deterministic transform extraction.
- Bounded Reel #3 benchmark: OpenCV sparse LK affine `57.4/100` (2/5 cases); OpenCV multi-scale edge-template tracking `89.8/100` (5/5 cases).
- Human accepted **COMBINE**: OpenCV template-derived position/scale curves + HyperFrames-inspired independent seekable channels + frozen OSS-001 Resolve carrier. Do not benchmark another motion route.
- Full Reel #3 extraction accounts for all 112 caption ordinals: 56 meaningful-motion, 56 static/no-motion, and 32 explicit localization-evidence failures included in the static count rather than guessed.
- Reconciliation authority preserves accepted `sub_008` and the four accepted OSS representatives; supersedes 11 rejected Step 3C items with OSS motion; removes 4 rejected static Step 3C items and re-enables their originals.
- Live run `20261010T105509634Z_5d7d0cc58b344d24a62f0fee7795f9e0` persisted 56 authoritative nested replacements on V3, 56 original/static captions, no rejected Step 3C replacement, and passed `SaveProject` verification.
- Human review accepted the detected motion as substantially closer to the reference; localization coverage remains the dominant gap.

## Current Result — OSS-002B Localization Coverage Recovery

- PaddleOCR `3.3.2` and EasyOCR `1.7.2` were source-audited under Apache-2.0 and benchmarked on the same 12 real Reel #3 failures / 36 anchor frames.
- They found candidate text on 35/36 and 33/36 anchors respectively, but each selected the expected V2 caption text correctly on `0/12` cases and therefore recovered `0/12` tracker seeds.
- The failure is an authority-association mismatch: visible baked text at those frames differs from the expected V2 caption token. Examples include `with -> to share/Everything`, `scene -> biggest/THESE`, and `you -> it's`.
- Both routes failed closed with zero accepted false localizations. No fallback was integrated, no 32-caption pass was run, and no Resolve command was published.
- Evidence: `data/DZatr0EJt4B/analysis/DZatr0EJt4B_oss002b_text_localization_benchmark.json`.

## Queued Gap — OSS-002C Caption Lifecycle / Persistence

- Status: `QUEUED`; not started.
- Source captions often retain earlier words and build multi-word/stacked compositions while the current generated authority remains word-by-word.
- The next human decision is whether the now-proven missing association mechanism justifies a tiny BUILD task; do not silently continue OCR or start lifecycle/persistence.

### OSS-002 done when

- caption-animation coverage is materially higher than the frozen 16-caption plan;
- compound motion can be represented at minimum as independent translation + scale channels where the source requires it;
- the result is applied as editable Resolve output through the proven carrier;
- one batch human review says fidelity is usable enough to move on.

## Kill / Anti-loop Rules

- The custom Step 3C detector is already killed for production: **NO MORE TUNING**.
- Maximum two serious compatible OSS routes may be benchmarked before selecting a winner/composition.
- Do not create a greenfield detector until proven compatible OSS routes fail a named product requirement.
- A mock/test PASS does not outrank live render/readback/human visual evidence.
- Human systematic visual rejection is a valid kill signal.
- Process/safety machinery must not become the product.

## Critical Path

`OSS-002 full accepted-motion rollout` (PASS / persisted)
-> `OSS-002B` text-localization fallback benchmark (STOPPED / no winner)
-> human decision on the missing association mechanism
-> `OSS-002C` bounded lifecycle/persistence spike
-> `OSS-003 transitions`
-> `OSS-004 core motion/VFX`
-> `OSS-005 speed ramps`
-> integrated Reel #3 review
-> generalization test.

## Future Animation Exemplar Inputs — Queued, Not Current Side Quest

The stable architecture must later accept multiple animation exemplars through adapters, including:

- reference-video frames/clips;
- CSS / JS / GSAP animations;
- pure-code animation definitions;
- GIFs / frame sequences;
- short MP4/GIF samples of partial captions, VFX or transitions;
- DaVinci templates, timelines, DRT/DRP-style project artifacts where technically/licensing-wise usable.

These sources should normalize into a common animation recipe/representation and then flow through editor-specific application adapters. Do not implement this multi-input layer before the current OSS-002/003/004 speedrun path produces the usable Reel #3 clone.
