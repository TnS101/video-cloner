# TEST_STRATEGY.md — Video Cloner Stable Verification Policy

- STATUS: APPROVED
- LAST UPDATED: 2026-10-07

Exact verification for a Plan belongs in `plan.md`. This file defines stable project-wide rules.

## Verification order

1. Git/config/schema/import/static safety check.
2. Focused tests for the changed/current boundary.
3. Reproduction with a real supplied/local fixture when needed.
4. Affected regression.
5. Artifact/output identity/semantic validation.
6. External runtime readback where applicable.
7. Human visual/subjective approval when the result is visual.

## Principles

- Test behavior, not exit code zero.
- Never weaken validators/tests to manufacture PASS.
- Separate machine acceptance from visual acceptance.
- Do not launch/mutate real Resolve from automated tests.
- Prefer focused tests during bounded Plans; run full canonical suite when shared/core contracts change or evidence warrants it.
- Treat warnings/flaky/transient failures as evidence to classify, not noise to hide.
- A flattened finished Reel is not sufficient final proof of clean/raw style transfer.
- Run ID, hashes, reports, target identity, and readback are stronger evidence than screenshots alone.

## Current canonical regression authority

Source: `docs/repo_hygiene/CANONICAL_REGRESSION_BASELINE.md`

```powershell
python -m pytest --basetemp=.pytest-tmp-repo-hygiene -q tests/test_standalone_media_prep.py tests/test_standalone_analysis.py tests/test_standalone_plan.py tests/test_build_camera_style_profile.py tests/test_build_caption_style_grammar_generic.py tests/test_style_profile_mvp_generic_comparison.py tests/test_video_cloner_mvp_transition_filter.py tests/test_compile_davinci_textplus_fcpxml_lifecycle.py tests/test_prepare_video_cloner_fresh_mvp_timeline.py tests/test_vc_agent_bridge.py tests/test_video_cloner_phase6_offline_timeline_live_application.py
```

Accepted baseline at bootstrap creation: **116 passed, 0 failed, 0 errors, 0 deselected**.

CI authority: `.github/workflows/offline-core.yml` (64-test focused core at cleanup completion).

## Manual approval gates

| Gate | Trigger | Human checks | Evidence returned |
|---|---|---|---|
| Resolve live execution | A Plan has prepared a bounded safe command | Run exact Workspace action only when instructed | observed result + requested report/run ID |
| Visual fidelity | Machine state exists and is ready for review | timeline/captions/transitions/camera look correct for the Plan's scope | APPROVE / REJECT + concise notes |
| Destructive action | deletion/migration/overwrite outside normal reversible Git work | confirm target and downside | explicit approval |
| Architecture/dependency change | current mechanism cannot meet requirement or new material dependency proposed | approve route/tradeoff | explicit decision |
