# Canonical Regression Baseline

Date: 2026-10-07

This is the explicit pre-migration product-path suite. It does not claim that the complete historical test collection is green.

## Command

```powershell
python -m pytest --basetemp=.pytest-tmp-repo-hygiene -q tests/test_standalone_media_prep.py tests/test_standalone_analysis.py tests/test_standalone_plan.py tests/test_build_camera_style_profile.py tests/test_build_caption_style_grammar_generic.py tests/test_style_profile_mvp_generic_comparison.py tests/test_video_cloner_mvp_transition_filter.py tests/test_compile_davinci_textplus_fcpxml_lifecycle.py tests/test_prepare_video_cloner_fresh_mvp_timeline.py tests/test_vc_agent_bridge.py tests/test_video_cloner_phase6_offline_timeline_live_application.py
```

## Result

- Passed: 116
- Failed: 0
- Errors: 0
- Deselected: 0
- Runtime: 5.66 seconds

The repository-local `--basetemp` removed the prior global-temp permission errors. The former private `.agent` preflight dependency is now a minimal self-contained fixture covering the same identity, absence, protected-state, and zero-mutation contract.

`test_video_cloner_phase6_offline_timeline_authority.py` remains classified `LEGACY_EXTERNAL_FIXTURE` outside this canonical suite because it requires the absent ignored `data/DcJRJtUKScu/davinci/offline_timeline_v1` package. The current Resolve contract suite is self-contained and green.

Before Resolve consolidation or deletion in Step 4, the safety property represented by each external-fixture exclusion must either have a self-contained replacement fixture/test or be formally proven legacy-only and irrelevant to the canonical route. The `-k not` exclusion is a temporary baseline boundary, not permanent coverage policy.

## Coverage boundary

- Media preparation and safe path/config behavior
- Seven-stage analysis orchestration
- Four-stage planning orchestration
- Generic camera, caption grammar, and style profile/comparison
- MVP transition filtering
- Text+ FCPXML compiler lifecycle behavior
- Queue publication safety contract
- Agent bridge queue/dispatch behavior
- Current Resolve timeline contract and fail-closed offline validation

## Step 2.5 hardening confirmation

The Step 2.5 historical result was **115 passed, 0 failed, 0 errors, 1 deselected in 6.95 seconds**. Step 4 replaces that deselection with a self-contained equivalent, producing 116 collected current-path tests.
