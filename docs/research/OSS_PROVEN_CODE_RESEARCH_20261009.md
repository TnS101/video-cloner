# OSS_PROVEN_CODE_RESEARCH_20261009.md

## 2026-10-10 Production Visual Review Override — OSS-002

Human visual evidence changes the production decision.

- The Resolve application layer is proven: OSS-001 + persisted `sub_008` establish editable Text+ placement and animation application.
- The custom Step 3C caption-animation detector is **FROZEN / REJECTED FOR PRODUCTION**.
- It selected only 16 captions and visibly misses many real animations.
- The source contains compound transforms (for example movement + size change) that the simple `scale` / `slide` taxonomy does not model adequately.
- Therefore no more custom detector tuning is authorized on the speedrun critical path.

### Active OSS action

Promote the strongest already-vetted animation/style candidates from benchmark/reference status to an immediate bounded adaptation spike:

1. HyperFrames first for concrete animation runtime / seekable GSAP / caption-identity / synthetic-reference mechanisms.
2. ghost-editor and video-style-kit/EditDNA patterns for concrete reusable extraction/recipe mechanisms.
3. Keep the proven davinci-resolve-mcp Text+ carrier as the editor application layer.
4. Verify whether each candidate actually derives animation from reference evidence versus only rendering supplied recipes; do not invent capability.
5. Benchmark at most two serious compatible routes/compositions on the same Reel #3 evidence, then choose `REUSE / ADAPT / COMBINE / REPLACE`.

Future architecture should also support animation exemplar adapters for CSS/JS/GSAP, code, GIF/frame sequences, short MP4/GIF samples and supported Resolve template/timeline artifacts, all normalized into a common animation recipe before editor-specific execution.


## Decision

**OSS-FIRST is now a hard product-development rule for Video Cloner.**

Before Video Cloner custom-builds a material mechanism, it must first search, audit, benchmark, and reuse/adapt proven existing code. Custom code is the fallback only after the best compatible OSS route fails a bounded compatibility test or cannot satisfy a named product requirement.

This research supersedes the earlier sequencing that postponed OSS research until after the Reel #3 basic-style stage.

## What "proven" means

A repository is not "proven" merely because it exists or has stars.

### PROVEN_A — preferred for production adoption
At least one of:
- live integration tests against the real target system/runtime;
- current, maintained library with substantial adoption + automated tests/benchmarks;
- end-to-end reproducible demo with direct readback/output verification.

Also required:
- usable license for our intended integration;
- mechanism actually overlaps the named Video Cloner gap.

### PROVEN_B — benchmark/adapt
- credible implementation + tests/demos, but not exact target-runtime proof;
- or strong adoption but indirect fit.

### REFERENCE_ONLY
- close concept but weak adoption/tests;
- no usable license;
- stale/archived;
- claims exceed evidence;
- useful algorithm/architecture reference only.

## Search scope

Comprehensive GitHub search was run across:
- DaVinci Resolve scripting / MCP / automation;
- Resolve Text+ / subtitles / Fusion;
- reference-video style cloning / editing DNA;
- short-form / Reels automation;
- cuts / shot-boundary detection;
- automatic rough cutting;
- caption timing / forced alignment;
- caption animation / kinetic text;
- transitions / WebGL / Fusion;
- optical flow / motion tracking / speed ramps;
- timeline IR / FCPXML / multi-editor interchange;
- full content-automation pipelines.

Literal enumeration of every GitHub repository is not useful or possible; this audit instead covers the materially relevant search space and records serious candidates plus screened-out near matches.

---

# P0 — ADOPT / BENCHMARK NOW

## 1. samuelgursky/davinci-resolve-mcp — **ADOPT NOW**
- URL: https://github.com/samuelgursky/davinci-resolve-mcp
- Pin: `94c7a885d53f13be78522ce96561a9e9e21d64c5`
- License: MIT
- Evidence: ~3.4k stars, active on 2026-10-09, extensive live Resolve verification harnesses.
- Proof: **PROVEN_A**
- Relevance: **10/10 — exact current Resolve automation problem.**

### Mechanisms to reuse
1. `tests/live_workaround_verification.py::case_nested_title`
   - Create a source timeline.
   - `InsertFusionTitleIntoTimeline("Text+")`.
   - Configure Text+ inside the source timeline.
   - Get source timeline `MediaPoolItem`.
   - Place that timeline onto the target with `AppendToTimeline` using exact `trackIndex`, `recordFrame`, `startFrame`, `endFrame`.
   - Re-open the inner timeline later and edit Text+.
   - Verified track/start/duration readback.

2. `docs/reference/api-limitations.md`
   - Documents why direct `InsertFusionTitleIntoTimeline` is insufficient for arbitrary target-track placement.
   - Track locking does **not** re-target insertion.
   - **Nested timeline is the recommended, live-measured route.**
   - Compound clips are explicitly rejected because they sever Text+ reachability.
   - DRP-injected Fusion titles are explicitly rejected after rendering/readback contradictions.

3. Live deletion/rollback verification patterns using `Timeline.DeleteClips`.

4. Resolve capability/limitations ledger to stop us re-discovering API dead ends.

### Immediate Video Cloner decision
**Vendor/adapt the nested-timeline Text+ placement mechanism and its live verification behavior. Freeze the custom caption-carrier experiments.**

Do not copy the entire MCP stack unless later useful. Reuse the smallest MIT-licensed mechanism + tests + attribution, pinned to the commit above.

---

## 2. Breakthrough/PySceneDetect — **REUSE**
- URL: https://github.com/Breakthrough/PySceneDetect
- Pin: `81c414cb4b706e58648f98efd381024790b1565f`
- License: BSD-3-Clause
- ~5.2k stars; active 2026-10.
- Proof: **PROVEN_A**
- Mechanisms: `ContentDetector`, `AdaptiveDetector`, `ThresholdDetector`, benchmarks.
- Decision: primary classical scene/cut detector benchmark. Do not reinvent generic shot-boundary detection.

## 3. WyattBlue/auto-editor — **ADAPT / BENCHMARK**
- URL: https://github.com/WyattBlue/auto-editor
- Pin: `5ab59aba3b8961aeef2c156300a7259d026e98fe`
- License: Unlicense
- ~5.4k stars; active 2026-10.
- Proof: **PROVEN_A**
- Mechanisms:
  - deterministic audio/motion cutting;
  - interval logic, margins/smoothing;
  - effects;
  - Resolve/FCPXML export (`--export resolve`);
  - transition export to Resolve.
- Decision: benchmark before any future custom rough-cut/interval/export implementation.

## 4. m-bain/whisperX — **REUSE**
- URL: https://github.com/m-bain/whisperX
- Pin: `771b4a14a9486f8fd5aef18ef49e35d639523dd3`
- License: BSD-2-Clause
- ~24k stars; active 2026-09.
- Proof: **PROVEN_A**
- Mechanisms: word-level forced alignment, diarization, batched transcription.
- Decision: preferred reference/engine for word-accurate caption timing instead of custom timestamp inference.

## 5. heygen-com/hyperframes — **ADOPT FOR RENDER/ANIMATION BENCHMARK**
- URL: https://github.com/heygen-com/hyperframes
- Pin: `46f6cb356785bed79e1ce7b79d7e7accc697786a`
- License: Apache-2.0
- ~59k stars; active 2026-10-09.
- Proof: **PROVEN_A**
- Mechanisms:
  - deterministic GSAP frame adapters;
  - seekable animation timelines;
  - embedded captions and caption identity catalog;
  - transition catalog;
  - speed-ramp core;
  - talking-head caption/occlusion workflows;
  - animation parsing/unrolling.
- Decision:
  - primary permissive renderer/reference for caption animation, synthetic ground truth, transitions, and speed-ramp behavior;
  - use before writing custom animation/transition render logic.

## 6. AcademySoftwareFoundation/OpenTimelineIO — **REUSE WHEN TIMELINE IR GAP APPEARS**
- URL: https://github.com/AcademySoftwareFoundation/OpenTimelineIO
- Pin: `00c22fa3a64256d8d3dcafbc7276492185dd970d`
- License: Apache-2.0
- ~2k stars; active 2026-10.
- Proof: **PROVEN_A**
- Decision: do not design a new generic timeline interchange model before testing OTIO against the requirement.

---

# P1 — STRONG SECONDARY CANDIDATES

## 7. mhadifilms/dvr — **ADAPT**
- URL: https://github.com/mhadifilms/dvr
- Pin: `dcc592be88e462a4d4cc58f6be77631e56cf96ee`
- License: MIT
- Proof: **PROVEN_B**
- Mechanisms:
  - Python/CLI/MCP wrapper for Resolve;
  - structured errors;
  - Text+ insertion/styling;
  - `AppendToTimeline` clipInfo support including `trackIndex`/`recordFrame`;
  - integration-test surface.
- Decision: use wrapper/helpers only where they reduce code; `davinci-resolve-mcp` remains authority for exact current title-placement workaround.

## 8. pedrolabonia/pydavinci — **REFERENCE / WRAPPER BENCHMARK**
- URL: https://github.com/pedrolabonia/pydavinci
- Pin: `6c5859f3bd5eac3584bde4040e8e59ca5674e218`
- License: MIT
- ~180 stars.
- Proof: **PROVEN_B**
- Decision: compare wrapper ergonomics before expanding our raw Resolve scripting layer.

## 9. Huanshere/VideoLingo — **ADAPT FOR CAPTION/ALIGNMENT PIPELINE**
- URL: https://github.com/Huanshere/VideoLingo
- Pin: `01f843492759be9bbfd1a5cb697b799cc9de1609`
- License: Apache-2.0
- ~18k stars; active.
- Proof: **PROVEN_A/B**
- Mechanisms:
  - word timestamp alignment;
  - subtitle splitting/merging;
  - Qwen/WhisperX backends;
  - caching/retry;
  - audio preprocessing and sample-alignment fixes.
- Decision: mine/reuse before custom subtitle chunking/alignment work.

## 10. soCzech/TransNetV2 — **BENCHMARK SECONDARY SHOT DETECTOR**
- URL: https://github.com/soCzech/TransNetV2
- Pin: `85cef72af9a916bdfd7cc94a670c9cdfbf12d1ed`
- License: MIT
- ~1k stars; older maintenance.
- Proof: **PROVEN_B**
- Decision: benchmark only when PySceneDetect/current cuts fail on difficult material.

## 11. kurbaitaev/ghost-editor — **ADAPT PROCESS / CAPTION-MOTION RECIPES**
- URL: https://github.com/kurbaitaev/ghost-editor
- Pin: `9f197e4e65691d190ba63efa6c061d9c43f02cf6`
- License: MIT
- ~66 stars; active 2026-10.
- Proof: **PROVEN_B**
- Very close to our product:
  - reference-reel style reverse engineering;
  - captions;
  - zoom/motion graphics;
  - sound;
  - HyperFrames rendering;
  - public demos.
- Decision: inspect its style extraction and motion/caption recipes before writing equivalent style-rule machinery.

## 12. krusemediallc/video-editor-agent — **ADAPT QA + STYLE-CLONE PROCESS**
- URL: https://github.com/krusemediallc/video-editor-agent
- Pin: `522856bc4b8036e4113c1f45752da8a9b938dfe2`
- License: repository metadata does not expose a standard license — verify before copying code.
- ~26 stars.
- Proof: **PROVEN_B / LICENSE_REVIEW**
- Strong mechanisms:
  - `reel-style-clone`;
  - render-first QA;
  - frame/dB evidence;
  - resumable projects;
  - review canvas;
  - offline integration suite.
- Decision: use process/QA ideas now; copy code only after license confirmation.

## 13. baneets/video-style-kit — **HIGH CONCEPT FIT / PLATFORM-LIMITED**
- URL: https://github.com/baneets/video-style-kit
- License: MIT
- Proof: **PROVEN_B**
- Exact concept:
  - scan reference video frame-by-frame;
  - extract cuts, transitions, text, caption motion, framing, push-ins, color, audio level;
  - store style recipe;
  - edit new footage;
  - Resolve build + Remotion transparent text layer;
  - end-to-end synthetic smoke test.
- Constraint: Apple Silicon / Apple Vision / MLX centered.
- Decision: mine schemas, calibration, style measurement and smoke-test patterns; do not adopt Mac-only runtime into our Windows production path.

## 14. itsjwill/vanta — **TRANSITION/CAPTION LIBRARY REFERENCE**
- URL: https://github.com/itsjwill/vanta
- Pin: `350b053ee18fb856a87516cfbfd1ad2295c26a73`
- ~136 stars.
- License metadata unresolved — verify before copying.
- Proof: **PROVEN_B / LICENSE_REVIEW**
- Mechanisms: Remotion engine, animated captions, 100+ GPU transitions, timeline.
- Decision: catalog/reference; no source copying until license is clear.

## 15. OpenShot/libopenshot / MLT — **MATURE EDITING ENGINES**
- OpenShot: https://github.com/OpenShot/libopenshot
- MLT: https://github.com/mltframework/mlt
- Mature timeline/effects frameworks.
- Decision: benchmark only if our execution/render backend itself becomes the blocker. Too heavy to adopt merely for one caption/transition defect.

---

# DIRECT STYLE-CLONER PROJECTS — AUDITED BUT NOT YET "PROVEN ENOUGH" TO TRUST BLINDLY

These are strategically valuable because they target almost exactly the same product, but low adoption/test evidence means **audit/reference first**, not blind integration.

## 16. MEX-creator/easy-edit (EditDNA)
- URL: https://github.com/MEX-creator/easy-edit
- Pin: `8591e4f9ba88894b2a78e4c0d47d47bd4a53c818`
- License: MIT
- Stars: ~1
- Direct match: **extremely high**.
- Architecture:
  - reference Reel -> StyleTemplate;
  - PySceneDetect cuts;
  - transition classification;
  - EasyOCR text/caption detection;
  - librosa beats;
  - deterministic/LLM edit plan;
  - Resolve timeline builder.
- Important honesty in README:
  - animated Fusion titles are explicitly deferred;
  - transition classification is best-effort;
  - Resolve Text+ property names are soft spots.
- Decision: mine schemas + deterministic planning + comparison tests, but do not replace proven components with this low-adoption project.

## 17. NSK-394/ai-video-agent
- URL: https://github.com/NSK-394/ai-video-agent
- Pin: `55fe83ad59e7efa0fe0c97bdb3f2212a8a68926d`
- License: MIT
- Stars: ~4
- Direct match: high.
- Includes: reference blueprint, cuts, beats, semantic ranking, zoom, speed-ramp plan, smart transitions, Resolve.
- Evidence caveat: README says demos/screenshots were planned; some effects are planned rather than fully proven.
- Decision: algorithm/reference source only until mechanisms are independently verified.

## 18. krshailendra/Agentic-Video-Editor
- URL: https://github.com/krshailendra/Agentic-Video-Editor
- License: unclear
- Direct style-rhythm copying concept.
- Decision: reference only unless tests/license improve.

## 19. rockwithsystems/AIvideokit
- URL: https://github.com/rockwithsystems/AIvideokit
- License: MIT
- Uses HyperFrames + FFmpeg; reference-video cuts, captions, transitions, b-roll.
- Honest status labels in prompts distinguish "works out of the box" vs unsupported tooling.
- Decision: recipe/reference source, especially HyperFrames orchestration.

## 20. jitheender-ops/ai-editing-claud
- Direct Resolve style-measure/apply concept.
- No clear license at research time.
- Decision: reference only.

## 21. rajj0777/vdk-ai-video-editor
- Direct reference-style recreation concept.
- No clear license at research time.
- Decision: reference only.

## 22. Julius1222/viralclone-ai / organicclone
- MIT, exact viral-style recreation concept, near-zero adoption.
- Decision: reference only.

## 23. Tedysek01/quickcut
- MIT; short-form auto-cuts/zooms/captions/transitions.
- Near-zero adoption.
- Decision: reference only.

## 24. ArtCog/chatmonteur
- MIT; talking-head meaning-based cuts/captions/graphics/sound.
- Low adoption.
- Decision: reference/UX patterns.

## 25. he­lenlpang/talking-head-video-editor / AutoEditPostPUBLIC / similar small projects
- Useful idea fragments.
- weak proof / unclear licenses.
- Decision: screened out from production adoption.

---

# RENDERER / TRANSITION / CAPTION ECOSYSTEM

## 26. Remotion
- URL: https://github.com/remotion-dev/remotion
- Pin researched around current main (`1d6c1c35...` after latest fetch).
- ~62k stars, extremely active.
- Has `@remotion/captions` and `@remotion/transitions`.
- License: source-available custom license, **not a simple permissive OSS license**.
  - free for individuals / small companies up to stated threshold;
  - larger for-profit use requires company license;
  - derivative resale restrictions.
- Decision: technically proven, but legal/product fit must be approved before tight integration. HyperFrames is preferred when equivalent and permissive.

## 27. 0xsline/OpenChatCut
- URL: https://github.com/0xsline/OpenChatCut
- Pin: `2e6f4a29b784200cfb32b859b16f2561592bc3e8`
- License: AGPL-3.0
- ~2.2k stars, active.
- Very relevant:
  - multi-track timeline;
  - captions;
  - Remotion/FFmpeg;
  - FCPXML;
  - GLSL transition runtime;
  - custom shader transition verification;
  - playback-rate support.
- Decision: mechanism/reference benchmark. Do not copy/integrate into proprietary product without explicit AGPL strategy.

## 28. MoneyPrinterTurbo
- URL: https://github.com/harry0703/MoneyPrinterTurbo
- Pin: `b819f7e1213ca2bc444cbf53ad3e0e3080c8a866`
- License: MIT
- ~129k stars.
- Excellent content-automation pipeline reference: scripts, stock, TTS, subtitles, transitions, FFmpeg.
- Decision: reuse workflow/glue patterns for later content-automation expansion, not core Resolve edit semantics.

## 29. ShortGPT
- MIT; mature short-video workflow but less current.
- Decision: architecture/reference only.

---

# MOTION / TRACKING / CV BUILDING BLOCKS

## 30. OpenCV
- Apache-2.0, ~91k stars.
- Use for classical motion, geometry, phase correlation, transforms, cheap CV.
- Decision: reuse before custom image-processing primitives.

## 31. RAFT
- BSD-3-Clause, ~4.1k stars.
- Optical flow.
- Decision: benchmark for difficult motion/whip/zoom inference before custom flow model.

## 32. GMFlow
- Apache-2.0.
- Optical flow alternative.
- Decision: secondary benchmark.

## 33. CoTracker
- strong point-tracking implementation.
- License requires verification before adoption.
- Decision: benchmark for subject/camera motion tracking when needed.

## 34. Ultralytics
- strong detection/pose/tracking ecosystem.
- AGPL-3.0 by default.
- Decision: use only with explicit license strategy or alternative permissive models.

---

# SCREENED OUT / REFERENCE ONLY

The following were found in the dedicated tracker/search space but are not production adoption candidates without stronger proof/license:
- Seibeltron/resolve-autocut — near-zero adoption, no clear license.
- Rraz0rR/DaVinci-Resolve-Subtitle-to-TextPlus — direct relevance but tiny adoption and no clear license.
- eonurk/cutty — no clear license / no adoption.
- devzaneai/autosplice — tiny adoption.
- andriidrok1/autobroll — interesting, but low proof; use architecture ideas only.
- timkulbaev/ai-video-editor — MIT and useful VAD/filler patterns, but low adoption.
- various `video-editor-agent`, `AI-Video-Editor`, and reference-style repos returned by GitHub search with zero/near-zero adoption and no strong tests.

---

# Final route decisions by Video Cloner capability

| Capability | Proven route first | Backup / benchmark | Custom only after |
|---|---|---|---|
| Resolve automation / exact placement | **davinci-resolve-mcp nested-timeline + live verification** | `dvr`, `pydavinci` | proven route fails bounded compatibility test |
| Advanced editable Text+ | **davinci-resolve-mcp nested timeline** | `dvr` Text+ helpers | exact requirement cannot be expressed |
| Cuts / scenes | **PySceneDetect** | TransNetV2, auto-editor | benchmark failure on corpus |
| Rough cut / silence/motion intervals | **auto-editor** | timkulbaev AI editor | missing product behavior measured |
| Word timing | **WhisperX** | VideoLingo forced alignment | benchmark failure |
| Caption animation/render ground truth | **HyperFrames** | ghost-editor recipes; Remotion if license accepted | proven renderer cannot express style |
| Transitions | **Resolve MCP known API/advanced routes + HyperFrames catalog** | OpenChatCut reference, Remotion | measured gap remains |
| Speed ramps / retime | **Resolve MCP verified capability ledger / DRT-OTIO route where API lacks speed; HyperFrames for render/synthetic truth** | auto-editor effects | both routes fail product requirement |
| Timeline IR/interchange | **OpenTimelineIO** | auto-editor formats/FCPXML | OTIO cannot represent required contract |
| Content automation | **MoneyPrinterTurbo + VideoLingo + ghost-editor/video-editor-agent patterns** | ShortGPT | only unique Video Cloner glue |
| Style-template schema | Video Cloner current + **EditDNA/video-style-kit schema audit** | ghost-editor style guide | only after comparing schemas |
| QA / visual acceptance | **video-editor-agent QA patterns + real rendered evidence** | existing VC validation | gaps remain |

---

# Immediate implementation order

## OSS-1 — current caption blocker
**Adopt `davinci-resolve-mcp` nested-timeline Text+ placement at pinned commit `94c7a885...`.**

Required compatibility spike:
1. Vendor/copy only the minimal MIT mechanism and attribution.
2. Port its live `case_nested_title` test into a disposable Video Cloner test command.
3. Run on the user's Resolve runtime without touching Reel #3.
4. Require exact track/start/duration + editable inner Text+ readback.
5. If PASS, use the same route for one Reel #3 `sub_008` caption.
6. If visual PASS, roll out the 16 already-detected animations.

**No more custom title carriers, ordinal/geometry canaries, or new placement algorithms before this route is tried.**

## OSS-2 — transitions / motion after captions
Before custom code:
- query Resolve MCP's limitation/capability ledger for the exact operation;
- use its verified public API/DRT/OTIO route if one exists;
- use HyperFrames' permissive animation/transition implementation as render/synthetic/reference mechanism;
- benchmark rather than invent.

## OSS-3 — cuts / timing
Do not reopen working cuts unless measured failure. When generalized testing starts:
- PySceneDetect first;
- auto-editor interval logic;
- WhisperX/VideoLingo for timing.

---

# Kill rules

1. **No material custom mechanism before OSS audit.**
2. If a PROVEN_A candidate exists, it gets a bounded compatibility test before custom code.
3. Do not replace proven code because we dislike its architecture.
4. Do not copy code with unclear/incompatible license.
5. One OSS compatibility spike should answer one question; no new agentic research loop.
6. After a proven route passes, integrate it and move to visible production output.
7. If an OSS route fails, record the exact incompatibility. Only then may BUILD be considered.
