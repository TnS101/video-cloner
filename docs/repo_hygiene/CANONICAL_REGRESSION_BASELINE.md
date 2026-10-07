# Canonical Regression Baseline

Date: 2026-10-07

This is the explicit pre-migration product-path suite. It does not claim that the complete historical test collection is green.

## Command

```powershell
python -m pytest --basetemp=.pytest-tmp-repo-hygiene -q tests/test_standalone_media_prep.py tests/test_standalone_analysis.py tests/test_standalone_plan.py tests/test_build_camera_style_profile.py tests/test_build_caption_style_grammar_generic.py tests/test_style_profile_mvp_generic_comparison.py tests/test_video_cloner_mvp_transition_filter.py tests/test_compile_davinci_textplus_fcpxml_lifecycle.py tests/test_prepare_video_cloner_fresh_mvp_timeline.py tests/test_vc_agent_bridge.py tests/test_video_cloner_phase6_offline_timeline_live_application.py -k "not actual_step7b_preflight_report_validates_without_mutation"
```

## Result

- Passed: 115
- Failed: 0
- Errors: 0
- Deselected: 1
- Runtime: 5.66 seconds

The repository-local `--basetemp` removed the prior global-temp permission errors. Two tests were made portable by testing containment against their supplied `tmp_path` or a genuinely external path instead of assuming pytest's temp root must live outside the repository.

`test_video_cloner_phase6_offline_timeline_authority.py` is classified `LEGACY_EXTERNAL_FIXTURE` and is retained outside this canonical suite. It requires the absent ignored `data/DcJRJtUKScu/davinci/offline_timeline_v1` package. The deselected `actual_step7b_preflight_report_validates_without_mutation` test likewise depends on a 1.65 MB ignored `.agent` report; the remaining current Resolve contract tests are self-contained and green.

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
