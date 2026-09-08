#!/usr/bin/env python3
"""Lock seven visual-first caption groups from reviewed source contact sheets.

This task consumes the accepted Step 3D-V1 offline pilot artifacts plus a
source-reviewed lock contract. It does not inspect transcript timing as visual
authority and does not modify Resolve.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

TASK_ID = "DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_AUTHORITY_LOCK_V2"
V1_TASK_ID = "DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_AUTHORITY_PILOT_V1"
CONTRACT_RELATIVE = Path(
    "data/DZsqH7auhjt/analysis/"
    "DZsqH7auhjt_caption_visual_first_authority_lock_v2.json"
)
V1_ARTIFACT_RELATIVE = Path("artifacts") / V1_TASK_ID
EXPECTED_GROUP_IDS = (
    "vf_group_01_nineteen_identity",
    "vf_group_02_already_decorated",
    "vf_group_03_stakes_are_high",
    "vf_group_04_knows_market_persistence",
    "vf_group_05_decorated_know",
    "vf_group_06_buildings_blocks_builders",
    "vf_group_07_something_motion",
)


class AuthorityLockError(RuntimeError):
    pass


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def require(condition: bool, code: str) -> None:
    if not condition:
        raise AuthorityLockError(code)


def validate_window(value: Any, code: str) -> list[int]:
    require(isinstance(value, list) and len(value) == 2, code)
    start, end = value
    require(isinstance(start, int) and isinstance(end, int) and end > start, code)
    return [start, end]


def validate_path(
    value: Any,
    window: list[int],
    code: str,
    *,
    vector: bool,
) -> list[dict[str, Any]]:
    require(isinstance(value, list) and len(value) >= 2, code)
    result: list[dict[str, Any]] = []
    previous_frame: int | None = None
    for row in value:
        require(isinstance(row, dict), code)
        frame = row.get("timeline_frame")
        point = row.get("value")
        require(isinstance(frame, int), code)
        require(window[0] <= frame < window[1], code)
        require(previous_frame is None or frame > previous_frame, code)
        previous_frame = frame
        if vector:
            require(
                isinstance(point, list)
                and len(point) == 2
                and all(isinstance(number, (int, float)) for number in point),
                code,
            )
            require(all(0.0 <= float(number) <= 1.0 for number in point), code)
            normalized: Any = [round(float(point[0]), 8), round(float(point[1]), 8)]
        else:
            require(isinstance(point, (int, float)), code)
            normalized = round(float(point), 8)
            require(0.0 <= normalized <= 2.0, code)
        result.append({"timeline_frame": frame, "value": normalized})
    return result


def validate_phases(value: Any, window: list[int], code: str) -> dict[str, Any]:
    require(isinstance(value, dict), code)
    classification = str(value.get("classification") or "").strip()
    require(classification, code)
    entrance = validate_window(value.get("entrance_window"), code)
    hold = validate_window(value.get("hold_window"), code)
    exit_window = validate_window(value.get("exit_window"), code)
    require(entrance[0] == window[0], code)
    require(entrance[1] == hold[0], code)
    require(hold[1] == exit_window[0], code)
    require(exit_window[1] == window[1], code)
    return {
        "classification": classification,
        "entrance_window": entrance,
        "hold_window": hold,
        "exit_window": exit_window,
        "shared_group_transform": bool(value.get("shared_group_transform")),
        "interpolation": str(value.get("interpolation") or ""),
    }


def index_by(rows: Any, key: str, code: str) -> dict[str, dict[str, Any]]:
    require(isinstance(rows, list), code)
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        require(isinstance(row, dict), code)
        identity = str(row.get(key) or "").strip()
        require(identity and identity not in result, code)
        result[identity] = row
    return result


def copy_review_artifacts(
    v1_root: Path,
    output_root: Path,
    group_id: str,
) -> dict[str, str]:
    source_group = v1_root / "windows" / group_id
    require(source_group.is_dir(), f"v1_group_artifacts_missing:{group_id}")
    target_group = output_root / "windows" / group_id
    target_group.mkdir(parents=True, exist_ok=True)
    copied: dict[str, str] = {}
    for name in (
        "source_contact_sheet.jpg",
        "visual_evidence_overlay_contact_sheet.jpg",
        "frame_evidence.json",
    ):
        source = source_group / name
        require(source.is_file(), f"v1_review_artifact_missing:{group_id}:{name}")
        target = target_group / name
        shutil.copy2(source, target)
        copied[name] = str(target)
    return copied


def lock_token(
    specification: dict[str, Any],
    v1_token: dict[str, Any],
    forbidden_placeholders: set[str],
) -> dict[str, Any]:
    token_id = str(specification.get("visual_token_id") or "")
    require(token_id == v1_token.get("visual_token_id"), f"token_identity_mismatch:{token_id}")
    window = validate_window(specification.get("visual_window"), f"window_invalid:{token_id}")
    position_path = validate_path(
        specification.get("position_path"),
        window,
        f"position_path_invalid:{token_id}",
        vector=True,
    )
    size_path = validate_path(
        specification.get("size_path"),
        window,
        f"size_path_invalid:{token_id}",
        vector=False,
    )
    opacity_path = validate_path(
        specification.get("opacity_path"),
        window,
        f"opacity_path_invalid:{token_id}",
        vector=False,
    )
    require(all(0.0 <= row["value"] <= 1.0 for row in opacity_path), f"opacity_path_invalid:{token_id}")
    phases = validate_phases(
        specification.get("animation_phases"),
        window,
        f"animation_phases_invalid:{token_id}",
    )
    style = specification.get("style_lock")
    require(isinstance(style, dict) and style.get("source_locked") is True, f"style_lock_invalid:{token_id}")
    display_text = specification.get("display_text")
    if specification.get("visual_kind") in {"text", "visual_only_text_decoration"}:
        require(isinstance(display_text, str) and display_text.strip(), f"display_text_missing:{token_id}")
    serialized = json.dumps(specification, ensure_ascii=False).casefold()
    for placeholder in forbidden_placeholders:
        require(placeholder.casefold() not in serialized, f"placeholder_forbidden:{token_id}:{placeholder}")

    return {
        "visual_token_id": token_id,
        "visual_kind": specification.get("visual_kind"),
        "display_text": display_text,
        "text_authority": specification.get("text_authority"),
        "transcript_aliases": specification.get("transcript_aliases") or [],
        "transcript_links": v1_token.get("transcript_links") or [],
        "transcript_timing_promoted_to_authority": False,
        "visual_window": window,
        "visual_window_authority": "source_reviewed_contact_sheet_lock",
        "position_path": position_path,
        "size_path": size_path,
        "opacity_path": opacity_path,
        "style_lock": style,
        "animation_phases": phases,
        "z_order": int(specification.get("z_order")),
        "role": specification.get("role"),
        "source_review_status": specification.get("source_review_status"),
        "v1_evidence_sources": v1_token.get("evidence_sources") or [],
        "v1_visual_window_candidates": v1_token.get("visual_window_candidates") or [],
        "status": "locked_for_seven_window_resolve_pilot",
    }


def build(repo_root: Path, output_dir: Path) -> dict[str, Any]:
    contract_path = repo_root / CONTRACT_RELATIVE
    v1_root = repo_root / V1_ARTIFACT_RELATIVE
    v1_manifest_path = v1_root / "visual_authority_pilot.json"
    require(contract_path.is_file(), f"contract_missing:{contract_path}")
    require(v1_manifest_path.is_file(), f"v1_manifest_missing:{v1_manifest_path}")

    contract = load_json(contract_path)
    v1_manifest = load_json(v1_manifest_path)
    require(contract.get("task_id") == TASK_ID, "contract_task_id_mismatch")
    require(contract.get("v1_task_id") == V1_TASK_ID, "contract_v1_task_id_mismatch")
    require(v1_manifest.get("task_id") == V1_TASK_ID, "v1_manifest_task_id_mismatch")

    policy = contract.get("authority_policy")
    require(isinstance(policy, dict), "authority_policy_missing")
    require(policy.get("transcript_timing_authority") is False, "transcript_timing_authority_enabled")
    require(policy.get("seven_window_resolve_pilot_authorized") is True, "resolve_pilot_not_authorized")
    require(policy.get("full_rollout_authorized") is False, "full_rollout_authorized")
    forbidden_placeholders = {
        str(value)
        for value in policy.get("forbidden_placeholders") or []
        if str(value).strip()
    }
    require(bool(forbidden_placeholders), "forbidden_placeholders_missing")

    contract_groups = index_by(contract.get("groups"), "group_id", "contract_groups_invalid")
    v1_groups = index_by(v1_manifest.get("groups"), "group_id", "v1_groups_invalid")
    require(tuple(contract_groups) == EXPECTED_GROUP_IDS, "contract_group_order_invalid")
    require(set(v1_groups) == set(EXPECTED_GROUP_IDS), "v1_group_set_invalid")

    output_dir.mkdir(parents=True, exist_ok=True)
    locked_groups: list[dict[str, Any]] = []
    token_count = 0
    visual_only_count = 0

    for group_id in EXPECTED_GROUP_IDS:
        specification = contract_groups[group_id]
        v1_group = v1_groups[group_id]
        spec_tokens = index_by(specification.get("tokens"), "visual_token_id", f"contract_tokens_invalid:{group_id}")
        v1_tokens = index_by(v1_group.get("visual_tokens"), "visual_token_id", f"v1_tokens_invalid:{group_id}")
        require(set(spec_tokens) == set(v1_tokens), f"token_set_mismatch:{group_id}")
        locked_tokens = [
            lock_token(spec_tokens[token_id], v1_tokens[token_id], forbidden_placeholders)
            for token_id in spec_tokens
        ]
        z_orders = [token["z_order"] for token in locked_tokens]
        require(len(z_orders) == len(set(z_orders)), f"duplicate_z_order:{group_id}")
        group_window = validate_window(
            specification.get("group_window"),
            f"group_window_invalid:{group_id}",
        )
        require(
            all(
                group_window[0] <= token["visual_window"][0]
                and token["visual_window"][1] <= group_window[1]
                for token in locked_tokens
            ),
            f"token_outside_group_window:{group_id}",
        )
        review_artifacts = copy_review_artifacts(v1_root, output_dir, group_id)
        locked_groups.append(
            {
                "group_id": group_id,
                "label": specification.get("label"),
                "composition_type": specification.get("composition_type"),
                "group_window": group_window,
                "group_hold_window": validate_window(
                    specification.get("group_hold_window"),
                    f"group_hold_window_invalid:{group_id}",
                ),
                "assembly_order": specification.get("assembly_order"),
                "tokens": locked_tokens,
                "review_artifacts": review_artifacts,
                "source_review_status": "locked_from_v1_contact_sheets",
                "status": "locked_for_seven_window_resolve_pilot",
            }
        )
        token_count += len(locked_tokens)
        visual_only_count += sum(
            token["text_authority"] == "visual_only"
            for token in locked_tokens
        )

    manifest: dict[str, Any] = {
        "schema": "video_cloner_caption_visual_first_authority_lock",
        "schema_version": 2,
        "task_id": TASK_ID,
        "ok": True,
        "video_id": contract.get("video_id"),
        "authority_policy": policy,
        "inputs": {
            "contract": str(contract_path),
            "contract_semantic_sha256": canonical_hash(contract),
            "v1_manifest": str(v1_manifest_path),
            "v1_manifest_semantic_sha256": canonical_hash(v1_manifest),
        },
        "summary": {
            "group_count": len(locked_groups),
            "visual_token_count": token_count,
            "visual_only_component_count": visual_only_count,
            "unresolved_component_count": 0,
            "placeholder_count": 0,
            "transcript_timing_promoted_count": 0,
            "resolve_modified": False,
            "seven_window_resolve_pilot_authorized": True,
            "full_rollout_authorized": False,
        },
        "groups": locked_groups,
        "next_boundary": {
            "objective": "build_disposable_seven_window_resolve_pilot_from_locked_authority",
            "resolve_action_allowed": True,
            "scope": "seven_windows_only",
            "full_rollout_allowed": False,
            "requires_visual_approval_after_render": True,
        },
    }
    manifest["semantic_sha256"] = canonical_hash(manifest)
    write_json(output_dir / "visual_authority_lock_v2.json", manifest)

    lines = [
        "# Step 3D Visual-First Authority Lock V2",
        "",
        f"Task: `{TASK_ID}`",
        "",
        "- Seven groups locked from reviewed source contact sheets.",
        f"- Visual tokens: {token_count}.",
        f"- Visual-only text decorations: {visual_only_count}.",
        "- Unresolved components: 0.",
        "- Transcript timing promoted: 0.",
        "- Resolve modified: no.",
        "- Next boundary: disposable seven-window Resolve pilot only.",
        "",
    ]
    write_text(output_dir / "LOCK_SUMMARY.md", "\n".join(lines))
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        manifest = build(args.repo_root.resolve(), args.output_dir.resolve())
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL {TASK_ID}: {type(exc).__name__}: {exc}")
        return 1
    summary = manifest["summary"]
    print(
        f"PASS {TASK_ID}: groups={summary['group_count']} "
        f"tokens={summary['visual_token_count']} unresolved=0"
    )
    print(args.output_dir.resolve() / "visual_authority_lock_v2.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
