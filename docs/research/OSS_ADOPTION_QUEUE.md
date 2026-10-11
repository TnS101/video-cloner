# OSS_ADOPTION_QUEUE.md — Video Cloner Proven-Code Queue

- UPDATED: 2026-10-11
- MODE: SPEEDRUN / PROVEN-CODE-FIRST
- RULE: `REUSE > ADAPT > COMBINE > BUILD`
- ACTIVE: `OSS-004` (CORE MOTION/VFX REPRESENTATIVE BATCH)

## Production Override — 2026-10-10

Human visual review overrules the prior assumption that the existing Video Cloner caption-animation detector was good enough to roll forward.

### Frozen route

Existing custom Step 3C plan:

- 16 selected captions;
- 10 `scale`;
- 6 `slide`;
- 0 `scale_pop`.

What the live evidence proves:

- the Resolve application carrier works;
- one persisted `sub_008` slide is visible/editable;
- many real source animations remain undetected;
- several source captions use compound motion such as translation + scale;
- the simple custom taxonomy is not close enough to production fidelity.

Decision: **FROZEN / REJECTED FOR PRODUCTION. No further tuning.**

## Sequential Queue

### OSS-001 — Editable Resolve Text+ carrier — PASS / CLOSED

Primary:
- `samuelgursky/davinci-resolve-mcp@94c7a885d53f13be78522ce96561a9e9e21d64c5`
- MIT.

Proven:
- native Text+ insertion;
- nested source timeline;
- source MediaPoolItem;
- exact `AppendToTimeline` placement;
- placed-item `GetTimeline()`;
- inner Text+ reach-back/editability.

Keep frozen as the application primitive.

### OSS-002 — Caption animation detection/representation/application — MVP ACCEPTED / PRODUCTION-READY / FROZEN

Objective:
- replace the frozen custom detector with proven OSS adaptation that materially improves coverage and compound-motion fidelity.

Audited representation source:
- `heygen-com/hyperframes@46f6cb356785bed79e1ce7b79d7e7accc697786a`
- Apache-2.
- Actual capability: seekable GSAP animation catalog/render adapters and independent property/keyframe representation; no reference-video detector.

Supporting audited source:
- `kurbaitaev/ghost-editor@9f197e4e65691d190ba63efa6c061d9c43f02cf6` — MIT; Gemini-generated edit study plus GSAP recipe renderer, not deterministic transform extraction.

Selected composition:
- OpenCV multi-scale edge-template tracking: `89.8/100`, 5/5 real Reel #3 benchmark cases.
- OpenCV sparse LK affine comparison: `57.4/100`, 2/5 cases.
- Decision: **COMBINE** template extraction + HyperFrames-style independent channels + OSS-001 carrier.
- Four missed captions (`sub_009`, `sub_012`, `sub_015`, `sub_026`) passed representative production review.
- Human accepted the representative batch as materially closer to source; no further motion-route benchmark is authorized.
- Full authority: 112 captions, 56 meaningful-motion, 56 static/no-motion, 32 extraction failures recorded explicitly.
- Production run `20261010T105509634Z_5d7d0cc58b344d24a62f0fee7795f9e0` persisted the 56/56 state and passed save verification; human review accepted detected motion as materially better.
- Reconciliation: preserve `sub_008` + four representatives; supersede 11 Step 3C items; remove 4 Step 3C static items and re-enable originals; expected final replacement count 56.

Execution:
- map winning OSS representation through OSS-001 Resolve carrier.

Acceptance:
- materially better coverage than 16-caption custom plan;
- compound transforms supported where present;
- editable Resolve output;
- batch HUMAN_REVIEW accepted.

Build gate:
- no greenfield detector work before the strongest two compatible OSS routes/compositions fail the same named requirement.

### OSS-002B — Raw exact-token localization — CLOSED / HISTORICAL

Audited and benchmarked on 12 real failed captions / 36 anchor frames:

- `PaddlePaddle/PaddleOCR@95dc316a8490a350c1d1fcf3bc80bf83d4e52450` (`3.3.2`, Apache-2.0): candidate boxes on 35/36 anchors; correct expected-caption selection 0/12; tracker recovery 0/12.
- `JaidedAI/EasyOCR@c4f3cd7225efd4f85451bd8b4a7646ae9a092420` (`1.7.2`, Apache-2.0): candidate boxes on 33/36 anchors; correct expected-caption selection 0/12; tracker recovery 0/12.
- Both failed closed with zero accepted false localizations.
- Root cause: OCR detects real baked text, but the expected V2 token at the same timestamp is generally different; this is a cross-authority association gap, not a text-detector-quality gap.

Decision at this layer: raw expected-token equality is invalid. Preserve the fail-closed evidence; OSS-002C supplies the authorized missing association layer without changing either OCR detector.

### OSS-002C — Cross-authority caption association — PASS / FROZEN

- Same 12 cases with phrase-aware association: PaddleOCR `11/12`, EasyOCR `11/12`; both `0` accepted false and `1` ambiguous; all 11 accepted regions seeded the existing tracker.
- Selected PaddleOCR on lower runtime and slightly higher tracker confidence.
- Full 32 pass: 26 recovered, 5 ambiguous, 1 rejected non-caption logo, 13 meaningful-motion, 13 static, 18 lifecycle composition proposals.
- Existing 56 accepted recipes remain unchanged. Seven-caption run `20261011T075523823Z_9505c20c898e475abcd84880e4420ffb` completed; the human accepted ordinals `5, 37, 54, 75, 80, 101, 107` as approximate but useful motion.
- Canonical 13 meaningful-motion captions reconcile to those seven live replacements plus exact six-caption delta `53, 78, 79, 87, 88, 108`. The 13 recovered-static and six unsupported captions stay original/static.
- Run `20261011T091036387Z_d111541339de4973b185c41e30bebedb` completed the six-caption delta. Human review accepts the combined V2/V3 result for MVP; no more caption work is on the current path.
- Evidence: `data/DZatr0EJt4B/analysis/DZatr0EJt4B_oss002c_cross_authority_benchmark.json` and `data/DZatr0EJt4B/analysis/DZatr0EJt4B_oss002c_cross_authority_recovery.json`.

### OSS-003 — Transitions — MVP ACCEPTED / PRODUCTION-READY / FROZEN

Authority: six existing Reel #3 candidates. The automated native Blur Dissolve proof at frame `80` passed live readback and human playback review.

Warning: the clip-level Fusion approximation is rejected. DRT evidence contains zero native transition elements; do not repair or tune it again.

Decision: reuse pinned Resolve MCP `placeTransition` (MIT) plus the Resolve-authored Blur Dissolve donor to author three native 11-frame transitions at `80`, `286`, and `376` in a disposable final derivative. Production remains untouched; live first-class transition readback and one final human review are mandatory.

Slides `211` / `629` and whip `461` are motion/VFX deferred to OSS-004. Experimental Fusion effects are non-blocking cleanup debt.

Final derivative `VIDEO_CLONER_DZatr0EJt4B_MVP_V1__OSS003_TRANSITIONS_V1` contains exactly three human-accepted native Blur Dissolves at `80`, `286`, and `376`. No further OSS-003 work is authorized.

### OSS-004 — Core motion / VFX

**ACTIVE.** Build on the accepted OSS-003 derivative. Mandatory representative targets are slide-like clip motion at `211`, paired whip motion at `461`, and slide-like clip motion at `629`, plus at most two source-backed shot-level transform examples.

Reuse HyperFrames independent seekable channel concepts, existing OpenCV-derived motion evidence, and pinned Resolve MCP Fusion graph/application/readback. Use minimum `MediaIn -> Transform -> [Blur] -> MediaOut` graphs. Do not mutate retiming.

Representative batch: shot 1 pull-out, incoming slides at `211` / `629`, shot 4 push-in plus right/down reframe, and paired whip at `461`. Three speed-ramp flags are deferred to OSS-005. Pending run: `20261011T144031710Z_fb34ba5ed4974dadaaf2dd39c296aa62`.

Potential CV primitives already researched:
- OpenCV;
- RAFT / GMFlow where optical-flow evidence materially improves a required effect.

### OSS-005 — Speed ramps / retiming

Reuse proven retiming mechanisms; integrate only source-backed ramps.

### OSS-006 — Cuts / scene detection

Current cuts are accepted.

Only reopen on actual failure/generalization evidence.

Candidates:
- PySceneDetect;
- TransNetV2 fallback.

### OSS-007 — Auto rough-cut
- auto-editor.

### OSS-008 — Caption timing/alignment
- WhisperX;
- VideoLingo.

### OSS-009 — Timeline IR/interchange
- OpenTimelineIO.

### OSS-010 — Style schema
- current VC profile + EditDNA/video-style-kit/ghost-editor audit.

### OSS-011 — QA / acceptance
- reusable render/readback/human-review acceptance layer.

### OSS-012 — Content automation
- MoneyPrinterTurbo + VideoLingo/ghost-editor patterns.

## Visual Critical Path

`OSS-002 captions` (MVP ACCEPTED / FROZEN)
-> `OSS-003 transitions` (MVP ACCEPTED / FROZEN)
-> `OSS-004 motion/VFX` (ACTIVE)
-> `OSS-005 speed ramps`
-> integrated visual review.

## Future Animation Exemplar Sources

After the current critical path, the animation system should accept adapters for:

- reference-video frames/clips;
- CSS/JS/GSAP;
- pure code;
- GIFs;
- frame sequences;
- very short MP4/GIF samples;
- Resolve templates/timelines/DRT/DRP-like project artifacts where supported.

All should normalize to a common animation recipe/representation before editor-specific application.
