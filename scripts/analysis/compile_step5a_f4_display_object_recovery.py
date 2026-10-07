from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(os.environ.get("VIDEO_CLONER_ROOT", Path(__file__).resolve().parents[2])).resolve()
F3_CONTRACT = Path(
    ".agent/reports/VIDEO_CLONER_STEP5A_F3_GENERIC_SCALE_SIZE_REPAIR_20260930_V1/"
    "20260930T130023481Z_luna_execute/first/step5a_f3_compile_contract.json"
)
F3_SHA256 = "97a663e705854e5880fb8bdbf2c1b5ec9c135eba1bba6c54b2c85572af7f5775"
AUTHORITY_GLOB = "config/*.accepted_display_object_recovery.json"
AUTHORITY_SHA256 = "84897912db92d43faf63950dffaa00018e5a0ab952f400837d170839ad91fd40"


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_pinned(path: Path, expected_hash: str) -> dict[str, Any]:
    actual_hash = _sha256(path)
    if actual_hash != expected_hash:
        raise ValueError(f"pinned_hash_mismatch:{path.as_posix()}:{actual_hash}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_recovery_authority(root: Path = ROOT) -> tuple[dict[str, Any], Path]:
    paths = sorted(root.glob(AUTHORITY_GLOB))
    matches = [path for path in paths if _sha256(path) == AUTHORITY_SHA256]
    if len(matches) != 1:
        raise ValueError(f"accepted_recovery_authority_count:{len(matches)}")
    authority = _load_pinned(matches[0], AUTHORITY_SHA256)
    if authority.get("schema") != "video_cloner_accepted_display_object_recovery":
        raise ValueError("accepted_recovery_authority_schema")
    if authority.get("authority") != "ACCEPTED_DISPLAY_OBJECT_RECOVERY":
        raise ValueError("accepted_recovery_authority_status")
    for artifact in authority.get("evidence_artifacts", []):
        actual_hash = _sha256(root / artifact["path"])
        if actual_hash != artifact["sha256"]:
            raise ValueError(f"evidence_hash_mismatch:{artifact['path']}:{actual_hash}")
    return authority, matches[0]


def _validate_record(record: dict[str, Any], authority: dict[str, Any]) -> None:
    required_text = str(record.get("accepted_display_text") or "").strip()
    if not required_text or record.get("source_existence") != "PROVEN" or record.get("renderable") is not True:
        raise ValueError("recovery_requires_proven_text_and_renderability")
    source_start = record.get("source_visible_start_frame")
    source_end = record.get("source_visible_end_frame")
    timeline_start = record.get("timeline_start_frame")
    timeline_end = record.get("timeline_end_frame")
    if not all(isinstance(value, int) for value in (source_start, source_end, timeline_start, timeline_end)):
        raise ValueError("recovery_requires_integer_lifecycle")
    if source_start > source_end or timeline_start >= timeline_end:
        raise ValueError("recovery_invalid_lifecycle")
    source_fps = float(authority["source_video"]["fps"])
    timeline_fps = float(authority["timeline_semantics"]["fps"])
    expected_start = round(source_start / source_fps * timeline_fps)
    expected_end = round(source_end / source_fps * timeline_fps) + 1
    if (timeline_start, timeline_end) != (expected_start, expected_end):
        raise ValueError("recovery_source_timeline_mapping_mismatch")
    bbox = record.get("source_bbox")
    width = int(authority["source_video"]["width"])
    height = int(authority["source_video"]["height"])
    if not isinstance(bbox, list) or len(bbox) != 4 or not (0 <= bbox[0] < bbox[2] <= width and 0 <= bbox[1] < bbox[3] <= height):
        raise ValueError("recovery_invalid_source_bbox")
    expected_center = [(bbox[0] + bbox[2]) / (2 * width), 1.0 - (bbox[1] + bbox[3]) / (2 * height)]
    if any(abs(left - right) > 1e-8 for left, right in zip(record.get("resolve_center", []), expected_center)):
        raise ValueError("recovery_center_bbox_mismatch")
    style = record.get("static_style_source") or {}
    if not style.get("classification") or not style.get("font_family") or not style.get("font_style"):
        raise ValueError("recovery_style_classification_required")
    if float(record.get("resolve_size") or 0.0) <= 0.0:
        raise ValueError("recovery_positive_size_required")
    motion = record.get("motion") or {}
    if any(motion.get(name) for name in ("position_keyframes", "scale_keyframes", "rotation_keyframes", "relative_visibility_keyframes")):
        raise ValueError("recovery_unsupported_motion_keyframes")


def compile_recovery_object(record: dict[str, Any], authority_path: Path, authority_hash: str) -> dict[str, Any]:
    style = record["static_style_source"]
    recovery_id = record["recovery_object_id"]
    interval = [record["timeline_start_frame"], record["timeline_end_frame"]]
    return {
        "advanced_effects": {
            "caption_occlusion": "UNSUPPORTED_OMITTED",
            "clipping": "UNSUPPORTED_OMITTED",
            "glow": "UNSUPPORTED_OMITTED",
            "gradient": "STYLE_UNRESOLVED_F5",
            "shadow": "STYLE_UNRESOLVED_F5",
            "texture": "UNSUPPORTED_OMITTED",
        },
        "composition": copy.deepcopy(record["composition_relationship"]),
        "display_text_decision": {
            "display_text_authority": "ACCEPTED_DISPLAY_OBJECT_RECOVERY",
            "identity": recovery_id,
            "renderable": True,
            "selected_display_text": record["accepted_display_text"],
            "source_provenance": copy.deepcopy(record["source_provenance"]),
        },
        "fill": {
            "resolve_rgb": copy.deepcopy(style["fill_rgb"]),
            "source_authority": style["fill_authority"],
            "value_role": "SOURCE_SUPPORTED_VALUE" if style["fill_authority"] == "SOURCE_SUPPORTED_VALUE" else "OPERATIONAL_RENDER_DEFAULT",
        },
        "font": {
            "resolve_family": style["font_family"],
            "resolve_style": style["font_style"],
            "source_authority": style["classification"],
            "value_role": "OPERATIONAL_RENDER_FALLBACK",
        },
        "intended_resolve_name": f"VC5A::RECOVERY::{recovery_id}",
        "keyframes": {"position": [], "relative_visibility": [], "rotation": [], "scale": []},
        "object_origin": "RECOVERED_DISPLAY_OBJECT",
        "opacity": {"resolve_value": 1.0, "source_authority": "OPERATIONAL_RENDER_DEFAULT", "value_role": "OPERATIONAL_RENDER_DEFAULT"},
        "position": {
            "mapping": "x_px/1080,1-y_px/1920",
            "resolve_center": copy.deepcopy(record["resolve_center"]),
            "source_authority": "ACCEPTED_DISPLAY_OBJECT_RECOVERY",
            "source_bbox": copy.deepcopy(record["source_bbox"]),
            "value_role": "SOURCE_SUPPORTED_VALUE",
        },
        "provenance": {"recovery_authority": {"path": authority_path.as_posix(), "sha256": authority_hash}},
        "renderable": True,
        "resolve_interval": interval,
        "scale_decision": {
            "compiled_absolute_size_anchors": [],
            "interpolation_policy": "STATIC_BASE_SIZE",
            "relative_scale_anchors": [],
            "scale_authority_status": "SUPPRESSED",
            "scale_suppression_reason": "NO_ACCEPTED_REPRODUCTION_AUTHORITY",
            "static_base_size": record["resolve_size"],
        },
        "size": {
            "resolve_value": record["resolve_size"],
            "source_authority": "ACCEPTED_DISPLAY_OBJECT_RECOVERY",
            "source_height_px": record["source_height_px"],
            "value_role": "SOURCE_SUPPORTED_VALUE",
        },
        "source_identity": recovery_id,
        "source_interval": interval,
        "static_rotation": {"resolve_degrees": None, "source_authority": "UNRESOLVED", "value_role": "UNSUPPORTED_OMITTED"},
        "stroke": {"resolve_enabled": False, "resolve_rgb": [0, 0, 0], "resolve_width": 0.0, "source_authority": "UNRESOLVED", "value_role": "OPERATIONAL_RENDER_DEFAULT"},
        "text": {"source_authority": "ACCEPTED_DISPLAY_OBJECT_RECOVERY", "value": record["accepted_display_text"], "value_role": "SOURCE_SUPPORTED_VALUE"},
        "z_order_track": {"resolve_track": 3, "source_authority": "OPERATIONAL_RENDER_DEFAULT", "value_role": "OPERATIONAL_RENDER_DEFAULT"},
    }


def append_recovery_objects(base_objects: list[dict[str, Any]], records: list[dict[str, Any]], authority_path: Path, authority_hash: str) -> list[dict[str, Any]]:
    output = copy.deepcopy(base_objects)
    known_ids = {row["source_identity"] for row in output}
    for record in records:
        recovery_id = record["recovery_object_id"]
        if recovery_id in known_ids:
            raise ValueError(f"duplicate_recovery_object_id:{recovery_id}")
        output.append(compile_recovery_object(record, authority_path, authority_hash))
        known_ids.add(recovery_id)
    return output


def compile_f4_contract(root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    f3 = _load_pinned(root / F3_CONTRACT, F3_SHA256)
    authority, authority_path = load_recovery_authority(root)
    records = authority.get("recovery_objects") or []
    if len({row.get("recovery_object_id") for row in records}) != len(records):
        raise ValueError("recovery_object_ids_not_unique")
    for record in records:
        _validate_record(record, authority)

    base_records = copy.deepcopy(f3["identity_records"])
    base_objects = copy.deepcopy(f3["objects"])
    final_objects = append_recovery_objects(base_objects, records, authority_path.relative_to(root), AUTHORITY_SHA256)
    contract = copy.deepcopy(f3)
    contract.update(
        {
            "schema": "video_cloner_step5a_f4_display_object_recovery_compile_contract",
            "schema_version": 1,
            "base_f3_contract": {"path": F3_CONTRACT.as_posix(), "sha256": F3_SHA256},
            "recovery_authority": {"path": authority_path.relative_to(root).as_posix(), "sha256": AUTHORITY_SHA256},
            "base_frozen_identity_count": len(base_records),
            "base_renderable_identity_count": len(base_objects),
            "recovered_display_object_count": len(records),
            "final_renderable_object_count": len(final_objects),
            "object_count": len(final_objects),
            "objects": final_objects,
            "resolve_mutated": False,
        }
    )

    rows = {row["source_identity"]: row for row in base_records}
    controls_ok = all(
        control["identity"] in rows
        and rows[control["identity"]]["renderable"] is control["renderable"]
        and rows[control["identity"]]["text"]["value"] == control["display_text"]
        for control in authority["regression_controls"]
    )
    checks = {
        "base_identity_accounting_113": len(base_records) == 113,
        "base_renderable_identity_accounting_62": len(base_objects) == 62,
        "base_identity_records_unchanged": contract["identity_records"] == f3["identity_records"],
        "base_renderable_objects_unchanged": contract["objects"][: len(base_objects)] == f3["objects"],
        "recovery_authority_nonempty": bool(records),
        "recovery_objects_all_renderable": all(row["renderable"] for row in final_objects[len(base_objects) :]),
        "final_count_reconciles": len(final_objects) == len(base_objects) + len(records),
        "regression_controls_unchanged": controls_ok,
        "f3_scale_decisions_unchanged": [row["scale_decision"] for row in contract["identity_records"]] == [row["scale_decision"] for row in f3["identity_records"]],
        "resolve_not_mutated": contract["resolve_mutated"] is False,
        "upstream_not_mutated": authority["upstream_artifacts_changed"] is False,
    }
    validation = {
        "schema": "video_cloner_step5a_f4_display_object_recovery_validation",
        "schema_version": 1,
        "all_pass": all(checks.values()),
        "checks": checks,
        "counts": {
            "base_frozen_identities": len(base_records),
            "base_renderable_identities": len(base_objects),
            "recovered_display_objects": len(records),
            "final_renderable_objects": len(final_objects),
        },
    }
    decisions = {
        "schema": "video_cloner_step5a_f4_display_object_recovery_decisions",
        "schema_version": 1,
        "decisions": [
            {
                "recovery_object_id": row["recovery_object_id"],
                "accepted_display_text": row["accepted_display_text"],
                "source_interval": [row["source_visible_start_frame"], row["source_visible_end_frame"] + 1],
                "timeline_interval": [row["timeline_start_frame"], row["timeline_end_frame"]],
                "method": "ACCEPTED_DISPLAY_OBJECT_RECOVERY",
            }
            for row in records
        ],
    }
    if not validation["all_pass"]:
        raise ValueError("f4_validation_failed")
    return contract, validation, decisions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    first = compile_f4_contract()
    second = compile_f4_contract()
    names = ("step5a_f4_compile_contract.json", "step5a_f4_validation.json", "step5a_f4_recovery_decisions.json")
    artifacts = {}
    for name, left, right in zip(names, first, second):
        left_bytes = _bytes(left)
        right_bytes = _bytes(right)
        digest = hashlib.sha256(left_bytes).hexdigest()
        artifacts[name] = {"byte_identical": left_bytes == right_bytes, "first_sha256": digest, "second_sha256": hashlib.sha256(right_bytes).hexdigest()}
        (output / name).write_bytes(left_bytes)
    proof = {"schema": "video_cloner_step5a_f4_determinism_proof", "schema_version": 1, "deterministic": all(row["byte_identical"] for row in artifacts.values()), "artifacts": artifacts}
    (output / "step5a_f4_determinism_proof.json").write_bytes(_bytes(proof))
    print(json.dumps({"ok": True, "output_dir": str(output), "counts": first[1]["counts"], "deterministic": proof["deterministic"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
