#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


VERSION = "validate_caption_font_step_3A_v1_0"


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Major Step 3A font detection and Resolve mapping.")
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--resolve-inventory", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--mapping-output", required=True)
    args = parser.parse_args()

    candidates_path = Path(args.candidates)
    inventory_path = Path(args.resolve_inventory)
    output_path = Path(args.output)
    mapping_path = Path(args.mapping_output)

    candidates = load_json(candidates_path)
    inventory = load_json(inventory_path)
    failures: List[str] = []
    warnings: List[str] = []

    if not candidates.get("success"):
        failures.append("font_candidate_detection_failed")
    if not inventory.get("success"):
        failures.append("resolve_font_probe_failed")

    profiles = candidates.get("profiles") or []
    profile_mappings = inventory.get("profile_mappings") or []
    if not profiles:
        failures.append("no_visual_font_profiles")
    if not profile_mappings:
        failures.append("no_resolve_profile_mappings")

    if int(candidates.get("inventory", {}).get("font_face_count") or 0) <= 0:
        failures.append("empty_font_file_inventory")
    if int(inventory.get("accepted_count") or 0) <= 0:
        failures.append("no_resolve_accepted_font")

    restore = inventory.get("restore") or {}
    if not restore.get("ok"):
        failures.append("probe_item_font_restore_failed")

    primary_candidates = next((row for row in profiles if row.get("is_primary_style")), None)
    primary_mapping = inventory.get("primary_mapping") or next(
        (row for row in profile_mappings if row.get("is_primary_style")),
        None,
    )
    selected_primary = (primary_mapping or {}).get("selected_mapping")
    if not primary_candidates:
        failures.append("primary_visual_profile_missing")
    if not selected_primary or not selected_primary.get("resolve_verified"):
        failures.append("primary_style_resolve_mapping_missing")

    mappings = []
    unresolved = []
    for row in profile_mappings:
        selected = row.get("selected_mapping")
        if selected:
            mappings.append({
                "style_profile_id": row.get("style_profile_id"),
                "family": selected.get("family"),
                "face": selected.get("face") or "Regular",
                "font_file": selected.get("font_file"),
                "visual_score": selected.get("visual_score"),
                "resolve_verified": True,
                "source": "visual_shape_match_plus_resolve_snapshot_readback",
            })
        else:
            unresolved.append(row.get("style_profile_id"))

    if unresolved:
        warnings.append(
            "Some style profiles remain unresolved and must inherit the verified primary mapping: "
            + ", ".join(str(value) for value in unresolved)
        )

    mapping_payload = {
        "success": not failures,
        "schema": "video_cloner_caption_font_mapping",
        "schema_version": "1.0",
        "analysis_version": "caption_font_mapping_step_3A_v1_0",
        "primary_style_id": candidates.get("primary_style_id"),
        "primary_mapping": selected_primary,
        "profile_mappings": mappings,
        "unresolved_style_profile_ids": unresolved,
        "fallback_policy": {
            "unresolved_profiles_inherit_primary_mapping": bool(selected_primary),
            "never_infer_face_from_ocr_weight": True,
            "only_resolve_verified_family_face_pairs_may_be_applied": True,
        },
        "inputs": {
            "font_candidates": str(candidates_path),
            "resolve_font_inventory": str(inventory_path),
        },
        "warnings": warnings,
        "failures": failures,
    }
    write_json(mapping_path, mapping_payload)

    result = {
        "ok": not failures,
        "validator_version": VERSION,
        "step": "Major Step 3A",
        "font_faces_scanned": int(candidates.get("inventory", {}).get("font_face_count") or 0),
        "visual_profiles": len(profiles),
        "resolve_candidates_tested": int(inventory.get("candidates_tested") or 0),
        "resolve_candidates_accepted": int(inventory.get("accepted_count") or 0),
        "primary_mapping": selected_primary,
        "resolved_profile_count": len(mappings),
        "unresolved_profile_count": len(unresolved),
        "probe_item_restored": bool(restore.get("ok")),
        "mapping_output": str(mapping_path),
        "warnings": warnings,
        "failures": failures,
    }
    write_json(output_path, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["ok"]:
        print(
            "PASS: Major Step 3A produced a visually ranked and Resolve-verified "
            "font family/face mapping without permanently changing V3."
        )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
