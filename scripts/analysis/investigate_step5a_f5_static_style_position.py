from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _load_pinned(root: Path, record: dict[str, str]) -> dict[str, Any]:
    path = root / record["path"]
    actual = _sha256(path)
    if actual != record["sha256"]:
        raise ValueError(f"pinned_hash_mismatch:{record['path']}:{actual}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def compile_audit(root: Path, spec_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    spec = json.loads(spec_path.read_text(encoding="utf-8-sig"))
    f4 = _load_pinned(root, spec["inputs"]["f4_contract"])
    for record in spec["inputs"]["evidence"]:
        actual = _sha256(root / record["path"])
        if actual != record["sha256"]:
            raise ValueError(f"evidence_hash_mismatch:{record['path']}:{actual}")

    identities = {row["source_identity"]: row for row in f4["identity_records"]}
    objects = {row["source_identity"]: row for row in f4["objects"]}
    if len(identities) != 113 or len(objects) != 64:
        raise ValueError("f4_accounting_mismatch")

    for target in spec["targets"]:
        for object_id, expected in target["current_state_checks"].items():
            row = objects.get(object_id) or identities.get(object_id)
            if row is None:
                raise ValueError(f"missing_current_object:{object_id}")
            if row["renderable"] is not expected["renderable"]:
                raise ValueError(f"renderability_mismatch:{object_id}")
            if row["text"]["value"] != expected["text"]:
                raise ValueError(f"text_mismatch:{object_id}")

    structural = [row["target"] for row in spec["targets"] if row["disposition"] == "BLOCKED_STRUCTURAL_OWNERSHIP"]
    insufficient = [row["target"] for row in spec["targets"] if row["disposition"] == "BLOCKED_INSUFFICIENT_SOURCE_EVIDENCE"]
    audit = {
        "schema": "video_cloner_step5a_f5_static_style_position_attribution_audit",
        "schema_version": 1,
        "result": "BLOCKED_F5_STRUCTURAL_OWNERSHIP" if structural else "BLOCKED_F5_INSUFFICIENT_STATIC_EVIDENCE",
        "counts": {
            "target_count": len(spec["targets"]),
            "repaired_target_count": 0,
            "already_resolved_count": sum(row["disposition"] == "ALREADY_RESOLVED_BY_PRIOR_PHASE" for row in spec["targets"]),
            "blocked_target_count": len(structural) + len(insufficient),
            "base_frozen_identities": len(identities),
            "base_renderable_identities": int(f4["base_renderable_identity_count"]),
            "recovered_display_objects": int(f4["recovered_display_object_count"]),
            "final_renderable_objects": len(objects),
        },
        "structural_blockers": structural,
        "insufficient_static_evidence": insufficient,
        "targets": spec["targets"],
        "implementation_authorized": False,
        "resolve_mutated": False,
    }
    blocker = {
        "schema": "video_cloner_step5a_f5_blocker",
        "schema_version": 1,
        "result": audit["result"],
        "blocked_targets": structural,
        "smallest_next_boundary": "Recover the independently source-visible listing object without changing caption_tracklet_0061 reels ownership.",
        "f5_overlay_authorized": False,
    }
    review = {
        "schema": "video_cloner_step5a_f5_static_review_manifest",
        "schema_version": 1,
        "human_review_required": bool(insufficient),
        "targets": [
            {
                "target": row["target"],
                "question": row["human_review_question"],
                "evidence_paths": row["source_provenance"],
            }
            for row in spec["targets"]
            if row["disposition"] == "BLOCKED_INSUFFICIENT_SOURCE_EVIDENCE"
        ],
    }
    return audit, blocker, review


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--spec", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    artifacts = compile_audit(root, Path(args.spec).resolve())
    names = (
        "step5a_f5_target_attribution_audit.json",
        "step5a_f5_blocker.json",
        "step5a_f5_static_review_manifest.json",
    )
    for name, artifact in zip(names, artifacts):
        (output / name).write_bytes(_bytes(artifact))
    print(json.dumps({"ok": True, "result": artifacts[0]["result"], "counts": artifacts[0]["counts"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
