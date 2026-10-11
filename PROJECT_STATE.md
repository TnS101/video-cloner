# PROJECT_STATE.md — Video Cloner Volatile Truth

- LAST UPDATED: 2026-10-11
- ACTIVE STAGE: `S007_OSS_FIRST_PROVEN_CODE_INTEGRATION`
- ACTIVE UNIT: `OSS-004_CORE_MOTION_VFX`
- STATUS: `LIVE_COMMAND_PENDING_HUMAN_REVIEW`

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

## Accepted Caption State — OSS-002 / OSS-002C Frozen

- One bounded BUILD now associates nearby V2 tokens with OCR phrase/region evidence using text, timing, spatial continuity, style geometry, and temporal persistence; it does not change OCR or motion extraction.
- Same 12-case gate: PaddleOCR and EasyOCR each produced `11/12` correct associations, `0` accepted false associations, `1` fail-closed ambiguity, and `11` successful seeds into the accepted OpenCV template tracker.
- PaddleOCR is selected because the tie produced slightly higher downstream tracker confidence and lower recorded runtime.
- Full 32-failure pass: `26` accepted recoveries, `5` ambiguities, `1` visually rejected non-caption logo, `13` new meaningful-motion captions, `13` recovered-static captions, and `18` conservative lifecycle composition proposals.
- The accepted 56-recipe authority is unchanged by exact SHA-256. Run `20261011T075523823Z_9505c20c898e475abcd84880e4420ffb` completed and persisted seven replacements for ordinals `5, 37, 54, 75, 80, 101, 107`; the human accepted them as approximate but useful motion.
- Canonical reconciliation is exact: 13 meaningful-motion captions = seven accepted live representatives + six missing targets (`53, 78, 79, 87, 88, 108`). The 13 recovered-static and six unsupported captions remain original/static.
- Run `20261011T091036387Z_d111541339de4973b185c41e30bebedb` completed and persisted the final six replacements. The resulting 69 editable V3 replacements plus 43 visible V2 static fallbacks are human-accepted for the MVP.
- OSS-002 is **MVP ACCEPTED / PRODUCTION-READY / FROZEN**. Lifecycle/persistence, detector tuning, association tuning, OCR research, and caption-motion polishing are deferred.
- Evidence: `data/DZatr0EJt4B/analysis/DZatr0EJt4B_oss002c_cross_authority_benchmark.json` and `data/DZatr0EJt4B/analysis/DZatr0EJt4B_oss002c_cross_authority_recovery.json`.

## Accepted Transition State — OSS-003 Frozen

- Existing canonical evidence contains six stylized candidates. Three blur transitions at frames `80`, `286`, and `376` are executable 11-frame source-backed handoffs.
- Whip `461` and slide candidates `211` / `629` are clip motion/VFX deferred to OSS-004; no new transition-family research is authorized here.
- **Warning:** the clip-level Fusion representation is rejected for OSS-003. Post-run DRT `5568d13189143e82b8f48cc3cc288ae3b7d9b1ce97a9ecbe044732ccce6ce59e` contains zero `Sm2TiTransition` elements; the sparkle icons are clip effects, not transition items. Do not repair or tune that route again.
- Live run `20261011T130946582Z_0d071b6f8542403d8a51b0ac8d669580` plus human review proves pinned Resolve MCP DRT insertion with a Resolve-authored native `Blur Dissolve` donor on Resolve `21.0.4.5`.
- Final derivative `VIDEO_CLONER_DZatr0EJt4B_MVP_V1__OSS003_TRANSITIONS_V1`, UID `75c9bc1b-ef1b-4463-9d7f-0ccb4b41e2b1`, contains exactly three native 11-frame Blur Dissolves at `75..85`, `281..291`, and `371..381`; production remains untouched.
- Human review and independent post-run DRT inspection accepted all three. OSS-003 is **MVP ACCEPTED / PRODUCTION-READY / FROZEN**. Experimental `VC_OSS003_` Fusion effects remain non-blocking historical debt and are not transition authority.

## Active Result — OSS-004 Core Motion / VFX

- Build on the accepted OSS-003 derivative, never the older production timeline.
- Mandatory representative targets: slide-like clip motion at `211`, whip-like paired clip motion at `461`, and slide-like clip motion at `629`.
- Reuse existing canonical motion/transition evidence, HyperFrames-style independent seekable channels, and pinned Resolve MCP Fusion application/readback. No broad analysis, new detector, transition work, or retiming mutation.
- Source inventory: eight shot-level motion events plus three boundary motion/VFX events. Speed-ramp flags on shots `1`, `2`, and `4` are deferred to OSS-005.
- Representative command `20261011T144031710Z_fb34ba5ed4974dadaaf2dd39c296aa62` is pending for derivative `VIDEO_CLONER_DZatr0EJt4B_MVP_V1__OSS004_MOTION_VFX_V1`.

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

`OSS-002 captions` (MVP ACCEPTED / PRODUCTION-READY / FROZEN)
-> `OSS-003 transitions` (MVP ACCEPTED / PRODUCTION-READY / FROZEN)
-> `OSS-004 core motion/VFX` (ACTIVE)
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
