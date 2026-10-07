# Deferred Capabilities Index

Updated: 2026-10-07 (Step 4.5 legacy-source distillation)

This is the complete, deliberately retained non-canonical runtime/source set after Step 4.5. These files are evidence or future implementation material; they are not public `video-cloner run` entry points. No retained source is `UNKNOWN`.

## Capability index

| Capability | Retained source | Why retained now | Evidence/status | Future canonical owner |
|---|---|---|---|---|
| Caption animation/lifecycle | `scripts/davinci/caption_animation_step_3C.py` | Imported by the canonical caption lifecycle adapter; removing it breaks current tests/imports. | Compatibility dependency; no Resolve execution claimed. | `video_cloner.captions.lifecycle` |
| Caption animation/lifecycle | `scripts/davinci/caption_lifecycle_authority_step_3D.py` | Imported by the canonical lifecycle adapter for the existing lifecycle contract. | Compatibility dependency. | `video_cloner.captions.lifecycle` |
| Caption animation/lifecycle | `scripts/davinci/redetect_caption_lifecycle_step_3D.py` | Imported by lifecycle code and the retained camera-transform probe chain. | Compatibility/deferred dependency. | `video_cloner.captions.lifecycle` |
| Caption animation/lifecycle | `scripts/davinci/validate_caption_lifecycle_fcpxml_step_3D.py` | Used by the current canonical regression evidence. | Compatibility test support. | `tests/` plus canonical lifecycle package |
| Caption animation/lifecycle | `resolve_workspace/resolve_apply_caption_animation_step_3C.py` | Smallest retained live Resolve application source for the deferred animation capability. | Deferred; live Resolve not run in Step 4.5. | `video_cloner.captions.lifecycle` + bounded Resolve adapter |
| Caption animation/lifecycle | `resolve_workspace/modules/step_3D_full_lifecycle_textplus_rollout.py` | Retained lifecycle implementation anchor and dependency root. | Deferred; Resolve-only. | `video_cloner.captions.lifecycle` |
| Caption animation/lifecycle | `resolve_workspace/modules/step_3D_visual_first_resolve_pilot.py` | Transitive dependency of the retained lifecycle baseline. | Deferred evidence/pilot. | `video_cloner.captions.lifecycle` |
| Caption animation/lifecycle | `resolve_workspace/modules/step_3D_visual_first_full_rollout_baseline.py` | Transitive dependency of lifecycle and occlusion closure. | Deferred evidence/baseline. | `video_cloner.captions.lifecycle` |
| Caption animation/lifecycle | `resolve_workspace/modules/step_3D_visual_instance_correction.py` | Transitive correction dependency for lifecycle materialization. | Deferred evidence/correction. | `video_cloner.captions.lifecycle` |
| Caption animation/lifecycle | `resolve_workspace/modules/step_3D_media_backed_fusion_clone.py` | Transitive media-backed lifecycle dependency. | Deferred evidence. | `video_cloner.captions.lifecycle` |
| Caption animation/lifecycle | `resolve_workspace/modules/step_3D_existing_textplus_clone_probe.py` | Transitive TextPlus carrier probe required by the retained fusion chain. | Deferred evidence/probe. | `video_cloner.captions.lifecycle` |
| Caption animation/lifecycle | `resolve_workspace/modules/step_3D_glyph_mask_render_probe.py` | Transitive glyph/mask evidence for lifecycle rendering. | Deferred evidence/probe. | `video_cloner.captions.lifecycle` |
| Font inference/application | `scripts/standalone/video_cloner_font_inference.py` | Smallest retained font inference source; canonical profile currently records the contract but does not apply Resolve fonts. | Deferred capability source. | `video_cloner.profiles` / caption adapter |
| Font inference/application | `resolve_workspace/resolve_probe_caption_font_candidates.py` | Resolve-side candidate inspection needed before a safe canonical font adapter exists. | Deferred probe; no live execution claimed. | `video_cloner.profiles` / bounded Resolve adapter |
| Opacity | `scripts/standalone/video_cloner_color_opacity.py` | Retains the measured color/opacity behavior without keeping its old launchers. | Deferred capability source. | `video_cloner.caption_grammar` / render profile |
| Stroke/shadow | `scripts/standalone/video_cloner_thickness_stroke.py` | Retains the measured thickness/stroke behavior for future canonicalization. | Deferred capability source. | `video_cloner.caption_grammar` / render profile |
| Camera editor transforms | `scripts/analysis/generate_step4b_motion_ir_pilot.py` | Root of the smallest retained motion-IR probe chain. | Deferred evidence; no current caller. | `video_cloner.camera` |
| Camera editor transforms | `scripts/analysis/generate_step4b_motion_ir_whole_reel.py` | Whole-reel extension of the retained motion-IR pilot. | Deferred evidence. | `video_cloner.camera` |
| Camera editor transforms | `scripts/analysis/generate_step4c_dynamic_transforms.py` | Retains dynamic-transform generation material. | Deferred evidence. | `video_cloner.camera` |
| Camera editor transforms | `scripts/analysis/investigate_step4c_dynamic_transforms.py` | Retains the corresponding investigation/interpretation source. | Deferred evidence. | `video_cloner.camera` |
| Transition/Flash execution | `resolve_workspace/modules/advanced_transition_flash_application_v1.py` | Base implementation dependency for the retained Flash chain. | Deferred; Resolve-only. | `video_cloner.transition_policy` + bounded Resolve adapter |
| Transition/Flash execution | `resolve_workspace/modules/advanced_transition_flash_replacement_v2.py` | Replacement implementation imported by the retained neutral-RGBA version. | Deferred; Resolve-only. | `video_cloner.transition_policy` + bounded Resolve adapter |
| Transition/Flash execution | `resolve_workspace/modules/advanced_transition_flash_neutral_rgba_v4.py` | Latest retained Flash implementation; no newer canonical equivalent exists. | Deferred; Resolve-only. | `video_cloner.transition_policy` + bounded Resolve adapter |
| Transition/Flash execution | `scripts/standalone/video_cloner_transition_authority.py` | Retains the standalone transition-authority contract and measured evidence. | Deferred capability source. | `video_cloner.transition_policy` |
| Occlusion/compositing | `resolve_workspace/modules/final_occlusion_composition_v1.py` | Root of the retained final-occlusion dependency chain. | Deferred; Resolve-only. | `video_cloner.analysis.caption_occlusion` |
| Occlusion/compositing | `resolve_workspace/modules/final_occlusion_composition_v2.py` | V1 successor; imports the retained metadata source. | Deferred; Resolve-only. | `video_cloner.analysis.caption_occlusion` |
| Occlusion/compositing | `resolve_workspace/modules/final_occlusion_composition_v3.py` | V2 successor in the retained closure. | Deferred; Resolve-only. | `video_cloner.analysis.caption_occlusion` |
| Occlusion/compositing | `resolve_workspace/modules/final_occlusion_composition_v4.py` | Latest retained final-occlusion implementation. | Deferred; Resolve-only. | `video_cloner.analysis.caption_occlusion` |
| Occlusion/compositing | `resolve_workspace/modules/step_3E_post_visual_metrics_polish_v1.py` | Transitive post-metrics dependency of the V4 occlusion chain. | Deferred evidence/polish. | `video_cloner.analysis.caption_occlusion` |
| Occlusion/compositing | `resolve_workspace/modules/step_3E_confirmed74_isolated_repair_rollout_v1.py` | Transitive confirmed-repair dependency. | Deferred evidence/repair source. | `video_cloner.analysis.caption_occlusion` |
| Occlusion/compositing | `resolve_workspace/modules/step_3E_remaining100_full_rollout_v1.py` | Transitive whole-rollout dependency. | Deferred evidence/rollout source. | `video_cloner.analysis.caption_occlusion` |
| Occlusion/compositing | `scripts/analysis/build_final_occlusion_pixel_restore_v3.py` | Retains the smallest pixel-restore builder needed to interpret V3 evidence. | Deferred evidence builder. | `video_cloner.analysis.caption_occlusion` |
| Occlusion/compositing | `scripts/analysis/validate_final_occlusion_pixel_restore_v4.py` | Retains the matching V4 validation source. | Deferred evidence validator. | `video_cloner.analysis.caption_occlusion` |
| Occlusion/compositing | `scripts/standalone/video_cloner_composition_relationships.py` | Retains the composition relationship contract used to interpret occlusion evidence. | Deferred capability source. | `video_cloner.analysis.caption_occlusion` |
| Occlusion/compositing | `resolve_workspace/resolve_apply_video_cloner_metadata.py` | Shared Resolve metadata dependency imported by the retained occlusion chain and referenced by motion analysis. | Deferred Resolve adapter source. | `video_cloner.resolve` / `video_cloner.analysis.caption_occlusion` |

## Compatibility and frozen boundary

These retained files are not deferred capability sources; they are required compatibility/frozen boundary material:

- `run_agent_task.bat`
- `run_install_VC_AGENT_BRIDGE.bat`
- `scripts/install_vc_agent_live.py`
- `resolve_workspace/VC_Run_Agent_Task.py` (frozen)
- `resolve_workspace/VC_Agent_Bridge.py` (frozen)
- `resolve_workspace/modules/video_cloner_phase6_textplus_application.py` (frozen)
- `resolve_workspace/modules/video_cloner_phase6_offline_timeline_live_application.py` (current regression support)
- `scripts/davinci/caption_animation_step_3C.py`
- `scripts/davinci/caption_lifecycle_authority_step_3D.py`
- `scripts/davinci/redetect_caption_lifecycle_step_3D.py`
- `scripts/davinci/validate_caption_lifecycle_fcpxml_step_3D.py`

## Classification proof

The post-distillation tracked runtime/source inventory is 42 files: 16 under `scripts/`, 24 under `resolve_workspace/`, and 2 root BAT helpers. The table above contains 35 capability/dependency rows; four lifecycle rows are current compatibility imports and are counted under `COMPATIBILITY_REQUIRED`, not under deferred capability. Exact classification counts:

| Classification | Count | Meaning in this tree |
|---|---:|---|
| `CANONICAL` | 0 | Canonical runtime is under `video_cloner/`; no duplicate canonical implementation remains here. |
| `COMPATIBILITY_REQUIRED` | 11 | Frozen bridge, install/bridge helpers, current lifecycle imports, and regression support. |
| `DEFERRED_CAPABILITY_SOURCE` | 31 | Explicitly indexed future capability/evidence sources above. |
| `HISTORICAL_EVIDENCE_ONLY` | 0 | Historical evidence was deleted or moved to documentation/artifacts. |
| `SUPERSEDED` | 0 | Superseded runtime sources were deleted. |
| `REPAIR_ONLY` | 0 | Repair-only runtime sources were deleted. |
| `FAILED_EXPERIMENT` | 0 | Failed experiments were deleted. |
| `GENERATED` | 0 | Generated caches/artifacts are not tracked runtime source. |
| `UNKNOWN` | 0 | Every retained file has a reason and owner. |

`run_bridge_smoke_test.bat`, its Python smoke module, and the other 330 stale/superseded runtime sources were deleted. Normal operation remains `video-cloner run`; root BAT files are install/bridge helpers only.

## Gate for promotion

No deferred source is promoted by retention alone. A future canonical implementation must add an owner in `video_cloner/`, focused tests, and current evidence before deleting the corresponding indexed source. Step 5 remains the explicit live Resolve acceptance gate; this index does not claim live application success.
