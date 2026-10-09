# plan.md — S007 OSS-First Proven-Code Integration

- STAGE ID: `S007_OSS_FIRST_PROVEN_CODE_INTEGRATION`
- STAGE NAME: Replace custom wheel-reinvention with proven OSS mechanisms
- STATUS: `READY`
- MODE: `PRODUCTION`
- ACTIVE REEL AFTER DISPOSABLE SPIKES: `DZatr0EJt4B`
- ACTIVE TARGET: `VIDEO_CLONER_P001_DZatr0EJt4B_20261007_4CE37F9BC61B`
- TARGET UID: `4aaa91c0-c434-4439-a15a-92ce86e80256`
- HUMAN DIRECTIVE: **OSS-FIRST IS MANDATORY**
- DEFAULT RISK: `R1`, with R2 only for live Resolve compatibility/visual checks

## 1. Human-Set Outcome

Ship Video Cloner by end of week using proven mechanisms instead of continuing custom API experiments.

Before Video Cloner custom-builds any material mechanism, it MUST:
1. identify the best proven OSS/existing implementation;
2. verify license/maintenance/evidence;
3. run a bounded compatibility test;
4. REUSE / ADAPT / COMBINE when viable;
5. BUILD only after the proven route fails a named requirement.

## 2. Immediate reason for this Stage

The custom caption-animation carrier path entered an agentic repair loop:
- custom carrier assumptions;
- native crashes;
- item rediscovery bug;
- structural identity mismatch;
- repeated canaries without visible Reel #3 progress.

Meanwhile, `samuelgursky/davinci-resolve-mcp` already contains a live-tested MIT nested-timeline Text+ route that directly solves exact track/frame/duration placement while preserving editable Text+.

Therefore custom caption carrier development is frozen.

## 3. Proven-code authority

Research artifact:
`docs/research/OSS_PROVEN_CODE_RESEARCH_20261009.md`

Priority evidence tiers:
- `PROVEN_A`: live-tested exact-runtime mechanism OR mature active library with strong tests/benchmarks.
- `PROVEN_B`: credible implementation/tests/demos but less exact proof.
- `REFERENCE_ONLY`: weak adoption/license/proof; do not copy blindly.

Stars alone are not proof.

## 4. IN scope

- vendor/adapt minimal proven OSS mechanisms with license attribution;
- bounded compatibility tests on disposable Resolve timelines/projects;
- replace custom caption carrier with `davinci-resolve-mcp` nested-timeline Text+ route;
- audit existing VC cuts/timing/transitions/motion against proven OSS before future custom work;
- use real visual/output evidence to choose next integration;
- preserve existing Reel #3 analysis and 16-caption animation detection plan.

## 5. OUT of scope

- more custom caption-carrier designs before the nested-timeline route is tested;
- more ordinal/geometry/name-matching canaries;
- rebuilding basic captions;
- Reel #2 production;
- architecture rewrite;
- broad dependency migration unrelated to current Win Condition;
- copying AGPL/custom-license/no-license code without an explicit licensing decision.

## 6. Stage Steps

| Step | Risk | Result | Done When | Status |
|---|---|---|---|---|
| 1 | R1 | Freeze custom routes + pin research decisions | Research artifact + candidate pins/licenses/decisions exist | DONE |
| 2 | R1/R2 | Reproduce proven nested-timeline Text+ route on disposable timeline | Exact track/start/duration + editable inner Text+ readback pass on user's Resolve | ACTIVE |
| 3 | R1/R2 | Adapt nested Text+ route for one Reel #3 `sub_008` animated caption | Visual caption/style/timing/animation match accepted; no unrelated mutation | TODO |
| 4 | R1/R2 | Roll out the already-selected 16 Reel #3 animations | 10 scale + 6 slide applied via proven route and human-reviewed | TODO |
| 5 | R1 | Proven-code capability map for transitions/motion | Each Reel #3 gap mapped to proven route before code | TODO |
| 6 | R1/R2 | Integrate next highest-ROI proven transition/motion route | Visible Reel #3 improvement from proven implementation | TODO |
| 7 | R2 | Integrated Reel #3 core-style review | Human accepts basic style baseline | TODO |

Cuts remain preserved unless a real benchmark failure appears.

## 7. Step 2 — exact current task

Use pinned source:
`samuelgursky/davinci-resolve-mcp@94c7a885d53f13be78522ce96561a9e9e21d64c5`

Primary reference:
`tests/live_workaround_verification.py::case_nested_title`

Mechanism:
1. Create disposable source timeline.
2. `InsertFusionTitleIntoTimeline("Text+")`.
3. Configure Text+ in source timeline.
4. `source_timeline.GetMediaPoolItem()`.
5. Create disposable target timeline with multiple video tracks.
6. Place source-timeline media item with `MediaPool.AppendToTimeline` using:
   - `trackIndex`
   - `recordFrame`
   - `startFrame`
   - `endFrame` (exclusive)
7. Verify exact track/start/duration.
8. Reach inner timeline with `placedItem.GetMediaPoolItem().GetTimeline()`.
9. Verify Text+ remains editable and Fusion comp/tool remains reachable.

Do not touch Reel #3 during Step 2.

### Attribution
If code is copied/adapted, preserve MIT notice and record source path + pinned commit.

## 8. Step 2 kill criteria

PASS:
- mechanism works on user's Resolve in disposable state.

FAIL:
- exact documented mechanism cannot work on current runtime after one bounded adaptation.

If FAIL:
- compare only the next proven candidates (`mhadifilms/dvr`, `pydavinci`, or official Resolve mechanism);
- do NOT invent carrier V4.

## 9. Rules for every later capability

Before coding:
1. search `OSS_PROVEN_CODE_RESEARCH_20261009.md`;
2. if a proven route exists, test/adapt it first;
3. if not, run a targeted search;
4. record `REUSE / ADAPT / COMBINE / BUILD / IGNORE`;
5. only BUILD after incompatibility evidence.

## 10. Selected proven routes already approved for benchmark

- Resolve title/control: `davinci-resolve-mcp`
- Cuts: PySceneDetect; auto-editor; TransNetV2 fallback
- Rough cuts: auto-editor
- Word timing: WhisperX / VideoLingo
- Animation/transition render/reference: HyperFrames
- Timeline IR: OpenTimelineIO
- Style-process references: ghost-editor, video-style-kit, EditDNA
- QA patterns: video-editor-agent
- Content automation: MoneyPrinterTurbo
- Remotion: technically strong but license-gated
- OpenChatCut: reference only unless AGPL strategy approved

## 11. Reporting

R1:
short result only:
- OSS source + pin
- mechanism reused
- compatibility result
- files changed
- real artifact/readback

R2:
durable evidence only when a live Resolve action is required.

No report-only stages.

## 12. True BLOCK conditions

- best proven candidate has incompatible license;
- proven route requires unavailable runtime/hardware;
- exact compatibility test fails and no second proven route exists;
- human-set target/Win Condition changes;
- destructive live action needs approval.

A failed custom mechanism is NOT permission to invent another before proven OSS is exhausted.

## 13. Stage Exit

S007 exits when:
- advanced Reel #3 caption animation uses a proven reused mechanism;
- current transition/motion gaps have proven-code decisions;
- at least one next visible transition/motion improvement is integrated from a proven route;
- the human accepts the integrated basic Reel #3 style baseline.

Then continue unseen/raw Reel generalization, still under OSS-first law.
