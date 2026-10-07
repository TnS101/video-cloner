from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_FREEZES = {
    ".agent/state/video_cloner_static_caption_freeze.json": "37ecd1438cd55b03cdb85b437131f0cafab322c85024ced41a00f01e69317601",
    ".agent/state/video_cloner_timing_persistence_freeze.json": "e3934346a227e81a83e9c21e83860fcbf43a59f57a5b29752c149875749ccc23",
    ".agent/state/video_cloner_step4b_motion_ir_freeze.json": "414b3fa823297b060eeb719e94154e222420cca8b270efbe7bce4d184fe18b65",
    ".agent/state/video_cloner_step4c_dynamic_transforms_freeze.json": "64f1493ec24f54968f90a66bc72b8346c5cf1af8acbc8a5661f02df7c800a54f",
    ".agent/state/video_cloner_step4d_advanced_text_effects_freeze.json": "a9f6ec6a3de8693dd77d2497b028747a18057cc00b773bd3c4aa72df18a1d1e6",
}
INPUTS = {
    "static": ".agent/reports/VIDEO_CLONER_STEP2F_FONT_AUTHORITY_CALIBRATION_20260927/20260927T020000000Z_calibrated/whole_reel_static_style_contract_calibrated.json",
    "timing": ".agent/reports/VIDEO_CLONER_STEP4A_TIMING_PERSISTENCE_20260927/20260927T122000000Z_human_review_ready/step4a_timing_persistence_contract.json",
    "motion": ".agent/reports/VIDEO_CLONER_STEP4B_WHOLE_REEL_MOTION_IR_20260927/20260927T113000000Z_human_review_ready/step4b_whole_reel_motion_ir.json",
    "dynamic": ".agent/reports/VIDEO_CLONER_STEP4C_WHOLE_REEL_DYNAMIC_TRANSFORMS_20260927_V1/20260927T170000000Z_human_review_ready/step4c_dynamic_transform_contract.json",
    "shadow": ".agent/reports/VIDEO_CLONER_STEP4D_SHADOW_PARAMETER_FIDELITY_20260928_V2/20260928T123000000Z_human_review_ready/step4d_shadow_ir_calibrated.json",
    "composition": ".agent/reports/VIDEO_CLONER_STEP2E_COMPOSITION_RELATIONSHIPS_20260925/20260925T220000000Z_source_graph/step2e_composition_relationships.json",
}


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def authority(value: Any) -> str:
    return str((value or {}).get("authority", {}).get("status") or "UNRESOLVED")


def median_center(observations: list[dict[str, Any]]) -> list[float] | None:
    if not observations:
        return None
    xs = [(row["bbox"][0] + row["bbox"][2]) / 2 / 1080 for row in observations]
    ys = [1 - (row["bbox"][1] + row["bbox"][3]) / 2 / 1920 for row in observations]
    return [round(statistics.median(xs), 8), round(statistics.median(ys), 8)]


def static_angle(rotation: dict[str, Any]) -> float | None:
    if rotation.get("reproduction_authority") != "STATIC_ORIENTATION_ONLY":
        return None
    values = [float(row["angle_degrees"]) for row in rotation.get("samples") or []]
    return round(statistics.median(values), 6) if values else None


def lane_rows(rows: list[dict[str, Any]]) -> None:
    ends: list[int] = []
    for row in sorted(rows, key=lambda x: (x["source_interval"][0], x["source_interval"][1], x["source_identity"])):
        start, end = row["source_interval"]
        lane = next((i for i, value in enumerate(ends) if value <= start), len(ends))
        if lane == len(ends):
            ends.append(end)
        else:
            ends[lane] = end
        row["z_order_track"] = {"resolve_track": lane + 2, "lane": lane + 1, "source_authority": "UNRESOLVED", "value_role": "OPERATIONAL_RENDER_DEFAULT"}


def merged_keyframes(identity: str, start: int, end: int, motion: list[dict[str, Any]], dynamic: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, dict[int, dict[str, Any]]] = {name: {} for name in ("position", "scale", "relative_visibility", "rotation")}
    permitted = {"position": {"SOURCE_TEMPLATE_TRACK"}, "scale": {"CORROBORATED_TEMPLATE_MASK_GEOMETRY"}, "relative_visibility": {"SOURCE_MASK_RELATIVE_STRENGTH"}}
    for record in motion:
        if record["identity"] != identity or record.get("status") != "SOURCE_MEASURED":
            continue
        channels = record.get("channel_authority") or {}
        for sample in record.get("samples") or []:
            frame = int(sample["frame"])
            if not start <= frame < end:
                raise ValueError(f"motion_keyframe_bounds:{identity}:{frame}")
            for channel in permitted:
                if channels.get(channel) not in permitted[channel] or sample.get(channel) is None:
                    continue
                raw = sample[channel]
                value = [float(raw["x"]), 1.0 - float(raw["y"])] if channel == "position" else float(raw.get("value") if isinstance(raw, dict) else raw)
                output[channel][frame] = {"timeline_frame": frame, "local_frame": frame - start, "value": value, "authority": channels[channel], "source": "STEP_4B_RAW_SAMPLE"}
    for channel, values in (dynamic.get("editor_neutral_keyframes") or {}).items():
        for item in values or []:
            frame = int(item["frame"])
            if not start <= frame < end:
                raise ValueError(f"dynamic_keyframe_bounds:{identity}:{channel}:{frame}")
            value = item.get("value")
            if channel == "position":
                value = [float(value["x"]), 1.0 - float(value["y"])]
            elif channel == "rotation":
                value = float(item["value_degrees"])
            else:
                value = float(value)
            output[channel][frame] = {"timeline_frame": frame, "local_frame": frame - start, "value": value, "authority": item.get("authority") or item.get("semantics"), "source": "STEP_4C_EDITOR_NEUTRAL_KEYFRAME"}
    visibility = output["relative_visibility"]
    if visibility:
        peak = max(float(row["value"]) for row in visibility.values())
        if peak <= 0:
            raise ValueError(f"relative_visibility_peak:{identity}")
        for row in visibility.values():
            row["source_relative_value"] = row["value"]
            row["value"] = min(1.0, max(0.0, float(row["value"]) / peak))
            row["mapping"] = "PER_IDENTITY_PEAK_NORMALIZED_RELATIVE_VISIBILITY_NOT_ABSOLUTE_ALPHA"
            row["value_role"] = "ACCEPTED_APPROXIMATION"
    return {name: [values[key] for key in sorted(values)] for name, values in output.items()}


def compile_contract(root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any]]:
    freeze_rows = []
    for rel, expected in EXPECTED_FREEZES.items():
        path = root / rel
        actual = sha(path)
        freeze_rows.append({"path": rel, "expected_sha256": expected, "actual_sha256": actual, "match": actual == expected})
    if not all(row["match"] for row in freeze_rows):
        raise ValueError("upstream_freeze_hash_drift")
    data = {name: read(root / rel) for name, rel in INPUTS.items()}
    inputs = {name: {"path": rel, "sha256": sha(root / rel)} for name, rel in INPUTS.items()}
    static = {row["identity"]["stable_identity_id"]: row for row in data["static"]["identities"]}
    timing = {row["identity"]: row for row in data["timing"]["identities"]}
    dynamic = {row["identity"]: row for row in data["dynamic"]["records"]}
    shadows = {row["source_identity"]: row for row in data["shadow"]["shadows"] if row["presence_authority"] == "SOURCE_REQUIRED_SHADOW"}
    ids = list(static)
    if len(ids) != 113 or len(set(ids)) != 113 or set(ids) != set(timing) or set(ids) != set(dynamic):
        raise ValueError("identity_accounting")
    objects = []
    for identity in ids:
        source, times, dyn = static[identity], timing[identity], dynamic[identity]
        start, end = map(int, times["generated"]["visibility_intervals"][0])
        if start >= end or times["comparison"].get("interval_match") is not True:
            raise ValueError(f"timing:{identity}")
        ident = source["identity"]
        observations = source["geometry"]["accepted_source_observations"]
        size = source["geometry"].get("size")
        font = source["typography"]["font"]
        selected = font.get("selected_candidate") or {}
        fill, opacity, stroke = source["fill"], source["opacity"], source["stroke"]
        shadow = shadows.get(identity)
        row = {
            "source_identity": identity,
            "intended_resolve_name": f"VC5A::{identity}",
            "text": {"value": ident["text_diagnostic_only"], "source_authority": "FROZEN_STATIC_IDENTITY_TEXT", "value_role": "SOURCE_SUPPORTED_VALUE"},
            "source_interval": [start, end], "resolve_interval": [start, end],
            "font": {"requested_family": selected.get("family"), "requested_style": selected.get("style"), "source_authority": authority(font), "resolve_family": selected.get("family") or "Arial", "resolve_style": selected.get("style") or "Regular", "mapping_status": "OPERATIONAL_FALLBACK_REQUIRED" if not selected.get("family") else ("EXACT_LOCAL_MAPPING" if authority(font) == "AUTHORITATIVE" else "ACCEPTED_APPROXIMATE_MAPPING"), "value_role": "OPERATIONAL_RENDER_DEFAULT" if not selected.get("family") else ("SOURCE_SUPPORTED_VALUE" if authority(font) == "AUTHORITATIVE" else "ACCEPTED_APPROXIMATION")},
            "size": {"source_height_px": size.get("median_height_px") if isinstance(size, dict) else None, "resolve_value": round(float(size["median_height_px"]) / 1080 * 1.5, 9) if isinstance(size, dict) else 0.062, "source_authority": authority(source["geometry"]), "value_role": "SOURCE_SUPPORTED_VALUE" if isinstance(size, dict) else "OPERATIONAL_RENDER_DEFAULT"},
            "position": {"source_center": median_center(observations), "resolve_center": median_center(observations) or [0.5, 0.5], "source_authority": authority(source["geometry"]), "value_role": "SOURCE_SUPPORTED_VALUE" if observations else "OPERATIONAL_RENDER_DEFAULT", "mapping": "x_px/1080,1-y_px/1920"},
            "fill": {"source_rgb": fill.get("color_rgb"), "resolve_rgb": fill.get("color_rgb") or [255, 255, 255], "source_authority": authority(fill), "value_role": "ACCEPTED_APPROXIMATION" if fill.get("color_rgb") else "OPERATIONAL_RENDER_DEFAULT"},
            "stroke": {"presence": stroke["presence"].get("value"), "width_source_px": stroke["width"].get("value_source_px"), "color_rgb": stroke["color"].get("color_rgb"), "source_authority": authority(stroke["presence"]), "resolve_enabled": stroke["presence"].get("value") is True, "resolve_width": float(stroke["width"].get("value_source_px") or 0) / 1080, "resolve_rgb": stroke["color"].get("color_rgb") or [0, 0, 0], "value_role": "ACCEPTED_APPROXIMATION" if authority(stroke["presence"]) == "PROVISIONAL" else "OPERATIONAL_RENDER_DEFAULT"},
            "opacity": {"source_value": opacity.get("value"), "resolve_value": 1.0, "source_authority": authority(opacity), "value_role": "OPERATIONAL_RENDER_DEFAULT", "relative_visibility_is_absolute_alpha": False},
            "static_rotation": {"resolve_degrees": static_angle(dyn["rotation"]), "source_authority": dyn["rotation"]["reproduction_authority"], "value_role": "SOURCE_SUPPORTED_VALUE" if static_angle(dyn["rotation"]) is not None else "UNSUPPORTED_OMITTED"},
            "keyframes": merged_keyframes(identity, start, end, data["motion"]["records"], dyn),
            "advanced_effects": {"shadow": shadow, "glow": "NOT_SOURCE_REQUIRED", "texture": "NOT_SOURCE_REQUIRED", "gradient": "NOT_SOURCE_REQUIRED", "clipping": "UNSUPPORTED_OMITTED", "caption_occlusion": "UNSUPPORTED_OMITTED"},
            "composition": source["composition"],
            "provenance": {"static": inputs["static"], "timing": inputs["timing"], "motion": inputs["motion"], "dynamic": inputs["dynamic"], "shadow": inputs["shadow"]},
        }
        objects.append(row)
    lane_rows(objects)
    regression_6000 = [row for row in objects if row["text"]["value"] == "6000"]
    if len(regression_6000) != 2 or any(row["keyframes"]["rotation"] for row in regression_6000):
        raise ValueError("6000_dynamic_rotation")
    if [row["source_identity"] for row in objects if row["advanced_effects"]["shadow"]] != data["shadow"]["cases_with_shadow_authority"]:
        raise ValueError("shadow_scope")
    contract = {"schema": "video_cloner_step5a_textplus_compile_contract", "schema_version": 1, "project": "New Project 1", "protected_timeline": {"name": "DcJRJtUKScu_offline_timeline_v1", "unique_id": "4ad2a3c3-031c-464d-96aa-76a045608ad6"}, "validation_timeline": "VIDEO_CLONER_STEP5A_TEXTPLUS_VALIDATION", "frame_semantics": data["timing"]["frame_semantics"], "inputs": inputs, "freeze_integrity": freeze_rows, "object_count": len(objects), "objects": objects, "unsupported_effects": ["clipping", "caption_occlusion"], "step_5b_status": "NOT_STARTED"}
    checks = {
        "freeze_hashes_match": all(row["match"] for row in freeze_rows), "identity_count_113": len(objects) == 113,
        "unique_identities": len({row["source_identity"] for row in objects}) == 113,
        "timing_valid": all(row["source_interval"][0] < row["source_interval"][1] == row["resolve_interval"][1] and row["source_interval"] == row["resolve_interval"] for row in objects),
        "authority_semantics_complete": all(all(field.get("value_role") for field in (row["text"], row["font"], row["size"], row["position"], row["fill"], row["stroke"], row["opacity"], row["static_rotation"])) for row in objects),
        "no_derived_label_commands": all(key.get("source") != "DERIVED_LABEL" for row in objects for values in row["keyframes"].values() for key in values),
        "keyframes_in_bounds": all(row["source_interval"][0] <= key["timeline_frame"] < row["source_interval"][1] for row in objects for values in row["keyframes"].values() for key in values),
        "6000_dynamic_rotation_zero": all(not row["keyframes"]["rotation"] for row in regression_6000),
        "shadow_not_global": sum(bool(row["advanced_effects"]["shadow"]) for row in objects) == 1,
        "unsupported_effects_omitted": all(row["advanced_effects"]["clipping"] == row["advanced_effects"]["caption_occlusion"] == "UNSUPPORTED_OMITTED" for row in objects),
        "relative_visibility_resolve_range": all(0.0 <= key["value"] <= 1.0 and key.get("source_relative_value") is not None for row in objects for key in row["keyframes"]["relative_visibility"]),
    }
    preflight = {"schema": "video_cloner_step5a_textplus_preflight_validation", "schema_version": 1, "checks": checks, "all_pass": all(checks.values()), "contract_sha256": digest(contract), "counts": {"identities": 113, "max_resolve_track": max(row["z_order_track"]["resolve_track"] for row in objects), "shadow": 1, "dynamic_rotation_identities": sum(bool(row["keyframes"]["rotation"]) for row in objects), "operational_font_fallbacks": sum(row["font"]["value_role"] == "OPERATIONAL_RENDER_DEFAULT" for row in objects)}}
    return contract, preflight


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    out = Path(args.output_dir).resolve(); out.mkdir(parents=True, exist_ok=True)
    contract, preflight = compile_contract()
    if not preflight["all_pass"]:
        raise SystemExit(2)
    for name, value in (("step5a_textplus_compile_contract.json", contract), ("step5a_textplus_preflight_validation.json", preflight)):
        (out / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    baseline_source = ROOT / ".agent/reports/VIDEO_CLONER_STEP5_TARGETED_HUMAN_REVIEW_V1/20260919T125540282Z_fresh_reel2_cardinality/reel2_cutonly_audio.fcpxml"
    baseline_text = baseline_source.read_text(encoding="utf-8")
    old_name = 'name="VC_R2_S5_20260919T125540Z"'
    new_name = f'name="{contract["validation_timeline"]}"'
    if baseline_text.count(old_name) != 1:
        raise ValueError("baseline_timeline_name")
    (out / "step5a_cutonly_baseline.fcpxml").write_text(baseline_text.replace(old_name, new_name), encoding="utf-8")
    (out / "step5a_review_manifest.json").write_text(json.dumps({"schema": "video_cloner_step5a_review_manifest", "deterministic_selection": ["caption_tracklet_0001", "caption_tracklet_0002", "caption_tracklet_0064", "caption_tracklet_0067", "caption_tracklet_0089", "caption_tracklet_0090", "source_visible_recovery_0113"], "human_review_required": True, "step_5b_status": "NOT_STARTED"}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    selected = set(json.loads((out / "step5a_review_manifest.json").read_text())["deterministic_selection"])
    (out / "step5a_review_data.json").write_text(json.dumps({"cases": [row for row in contract["objects"] if row["source_identity"] in selected], "resolve_readback_pending": True}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rerun, rerun_preflight = compile_contract()
    proof = {"contract_sha256_first": digest(contract), "contract_sha256_second": digest(rerun), "preflight_sha256_first": digest(preflight), "preflight_sha256_second": digest(rerun_preflight), "deterministic": contract == rerun and preflight == rerun_preflight}
    (out / "determinism_proof.json").write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "output_dir": str(out), "contract_sha256": preflight["contract_sha256"], "object_count": contract["object_count"], "max_resolve_track": preflight["counts"]["max_resolve_track"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
