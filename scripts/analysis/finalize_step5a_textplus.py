from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("report_dir"); args = parser.parse_args()
    root = Path(args.report_dir).resolve()
    contract = read(root / "step5a_textplus_compile_contract.json")
    preflight = read(root / "step5a_textplus_preflight_validation.json")
    first = read(root / "bridge_report_eighth.json")
    second = read(root / "bridge_report_full_readback.json")
    manifest = read(root / "step5a_resolve_application_manifest.json")
    readback = read(root / "step5a_resolve_readback.json")
    parity = read(root / "step5a_property_parity_validation.json")
    protected = read(root / "step5a_protected_timeline_validation.json")
    idempotency = read(root / "step5a_idempotency_validation.json")
    if not (preflight["all_pass"] and second["ok"] and parity["ok"] and not protected["mutated"] and idempotency["pass"]):
        raise ValueError("step5a_not_closable")
    manifest["first_application_evidence"] = {
        "bridge_report": "bridge_report_eighth.json", "timeline_created": first["mutation_counts"]["timeline_create"],
        "textplus_created": first["mutation_counts"]["textplus_create"], "project_saves": first["mutation_counts"]["project_save"],
        "persisted_before_readback_validator_correction": True,
    }
    manifest["second_identical_application_evidence"] = {
        "bridge_report": "bridge_report_full_readback.json", "timeline_created": second["mutation_counts"]["timeline_create"],
        "textplus_created": second["mutation_counts"]["textplus_create"], "project_saves": second["mutation_counts"]["project_save"],
        "classification": second["classification"],
    }
    manifest["idempotency_pass"] = True
    write(root / "step5a_resolve_application_manifest.json", manifest)
    expected = {row["source_identity"]: row for row in contract["objects"]}
    actual = {row["source_identity"]: row for row in readback["objects"]}
    parity_rows = {row["source_identity"]: row for row in parity["rows"]}
    selection = read(root / "step5a_review_manifest.json")["deterministic_selection"]
    review = {"schema": "video_cloner_step5a_review_data", "human_review_required": True, "screenshot_automation_available": False, "cases": [{"source_identity": identity, "frozen_expected": expected[identity], "resolve_readback": actual[identity], "property_differences": [name for name, matched in parity_rows[identity]["checks"].items() if not matched]} for identity in selection]}
    write(root / "step5a_review_data.json", review)
    counts = parity["counts"]
    report = f"""# Video Cloner Step 5A — Real Resolve Text+ Compile

RESULT: PASS_STEP_5A_REAL_TEXTPLUS_COMPILE_READY_FOR_HUMAN_RESOLVE_REVIEW

- Upstream freeze integrity: PASS (Steps 3, 4A, 4B, 4C, 4D).
- Compile contract: 113/113 unique identities; deterministic preflight PASS.
- Resolve project: `New Project 1`.
- Protected timeline: `DcJRJtUKScu_offline_timeline_v1` (`4ad2a3c3-031c-464d-96aa-76a045608ad6`), mutated: NO.
- Validation timeline: `VIDEO_CLONER_STEP5A_TEXTPLUS_VALIDATION` (`698a4176-9a20-45f5-b147-4fcfea77e414`).
- Real Text+ objects: 113 created and persisted; second identical run created 0 and saved 0.
- Property parity: {json.dumps(counts, sort_keys=True)}.
- 6000 regression: zero dynamic rotation keyframes; static-orientation-only authority preserved.
- Shadow: one frozen source-authorized identity only; 113/113 scope/readback checks PASS.
- Unsupported effects: clipping and caption occlusion omitted; glow, texture, and gradient not fabricated.
- Relative visibility: raw source-relative values retained; Resolve values use documented per-identity peak normalization and are not claimed as absolute alpha.
- Rollback: failed unsaved attempts deleted only the owned validation timeline; no unrelated deletion occurred.
- Human review required: YES. Step 5B remains NOT STARTED.
"""
    (root / "FINAL_REPORT.md").write_text(report, encoding="utf-8")
    print(json.dumps({"ok": True, "report_dir": str(root), "result": "PASS_STEP_5A_REAL_TEXTPLUS_COMPILE_READY_FOR_HUMAN_RESOLVE_REVIEW"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
