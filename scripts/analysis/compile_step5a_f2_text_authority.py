from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.analysis.compile_step5a_textplus_contract import ROOT, compile_contract as compile_base_contract


LINKAGE_PATH = ".agent/reports/VIDEO_CLONER_STEP2B1_FINAL_MULTI_OBJECT_MASK_ISOLATION_REPAIR_20260927/20260927T000000000Z_bounded/whole_reel_text_mask_linkage_audit_after_mask_isolation_repair.json"
MISMATCH_ADJUDICATION_PATH = ".agent/reports/VIDEO_CLONER_STEP2B1_LINKAGE_CANDIDATE_ADJUDICATION_20260926/20260926T200000000Z_readonly/adjudication_decisions.json"
DISPLAY_ADJUDICATION_PATH = ".agent/reports/VIDEO_CLONER_STEP5A_F2A_ACCEPTED_DISPLAY_TEXT_AUTHORITY_20260930/20260930T095425875Z_adjudicated/step5a_f2a_accepted_display_text_adjudication.json"
EXPECTED_DISPLAY_ADJUDICATION_SHA256 = "1e83de98b62e304d40408b2d0a74aa9de961aa87872baacc212dee5f0d81e6bb"
STRONG_VISUAL_AUTHORITIES = {
    "SOURCE_VISIBLE_OBSERVED_TEXT_BBOX_MATCH",
    "SOURCE_VISIBLE_PIXELS_BOUNDED_LINKAGE_DECISION",
    "SOURCE_VISIBLE_PIXELS_BOUNDED_OWNERSHIP_DECISION",
}
FRAGMENT_RELATIONSHIPS = {"ACCEPTED_PHYSICAL_WORD_FRAGMENT", "ACCEPTED_VISUAL_FRAGMENT"}


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(json_bytes(value)).hexdigest()


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _decision(
    linkage: dict[str, Any],
    *,
    renderable: bool,
    text: str | None,
    authority: str,
    source_field: str | None,
    suppression_reason: str | None,
    provenance: dict[str, Any],
    adjudication_group_id: str | None = None,
    canonical_owner_identity: str | None = None,
) -> dict[str, Any]:
    return {
        "identity": linkage["identity"],
        "renderable": renderable,
        "selected_display_text": text,
        "selected_display_text_normalized": normalize_text(text) or None,
        "display_text_authority": authority,
        "display_text_source_field": source_field,
        "text_mask_relationship": linkage["text_mask_relationship"],
        "contract_text": linkage.get("contract_text"),
        "source_visible_text": linkage.get("source_visible_text"),
        "font_scoring_text": linkage.get("font_scoring_text"),
        "adjudication_group_id": adjudication_group_id,
        "canonical_owner_identity": canonical_owner_identity,
        "suppression_reason": suppression_reason,
        "source_provenance": provenance,
    }


def build_display_adjudications(artifact: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if artifact.get("schema") != "video_cloner_step5a_f2a_accepted_display_text_adjudication":
        raise ValueError("display_adjudication_schema")
    if artifact.get("authority") != "ACCEPTED_DISPLAY_TEXT_ADJUDICATION":
        raise ValueError("display_adjudication_authority")
    output: dict[str, dict[str, Any]] = {}
    for case in artifact.get("adjudications") or []:
        for disposition in case.get("identity_dispositions") or []:
            identity = disposition["identity"]
            if identity in output:
                raise ValueError(f"duplicate_display_adjudication:{identity}")
            output[identity] = {
                "accepted_display_text": case.get("accepted_display_text"),
                "display_object_group_id": case.get("display_object_group_id"),
                "case": case.get("case"),
                **disposition,
            }
    return output


def select_display_text(
    linkage: dict[str, Any],
    display_adjudication: dict[str, Any] | None,
    mismatch_adjudication: dict[str, Any] | None,
) -> dict[str, Any]:
    relationship = str(linkage.get("text_mask_relationship") or "UNRESOLVED")
    identity = linkage["identity"]
    if display_adjudication is not None:
        disposition = str(display_adjudication.get("disposition") or "")
        group_id = display_adjudication.get("display_object_group_id")
        owner = display_adjudication.get("canonical_owner_identity")
        provenance = {
            "artifact": DISPLAY_ADJUDICATION_PATH,
            "case": display_adjudication.get("case"),
            "disposition": disposition,
        }
        if disposition.startswith("RENDERABLE_CANONICAL_OWNER"):
            text = str(display_adjudication.get("accepted_display_text") or "").strip()
            if not text:
                raise ValueError(f"empty_display_adjudication:{identity}")
            return _decision(
                linkage,
                renderable=True,
                text=text,
                authority="ACCEPTED_DISPLAY_TEXT_ADJUDICATION",
                source_field="adjudications[].accepted_display_text",
                suppression_reason=None,
                provenance=provenance,
                adjudication_group_id=group_id,
                canonical_owner_identity=owner,
            )
        if disposition.startswith("NON_RENDERING_") or disposition.startswith("SUPPRESS_"):
            return _decision(
                linkage,
                renderable=False,
                text=None,
                authority="ACCEPTED_DISPLAY_TEXT_ADJUDICATION",
                source_field="adjudications[].identity_dispositions[].disposition",
                suppression_reason=disposition,
                provenance=provenance,
                adjudication_group_id=group_id,
                canonical_owner_identity=owner,
            )
        raise ValueError(f"unsupported_display_adjudication_disposition:{identity}:{disposition}")

    if relationship == "EXPLICITLY_UNRESOLVED":
        return _decision(
            linkage,
            renderable=False,
            text=None,
            authority="UNRESOLVED",
            source_field=None,
            suppression_reason="EXPLICITLY_UNRESOLVED_WITHOUT_HIGHER_AUTHORITY",
            provenance={"artifact": LINKAGE_PATH, "source_evidence_provenance": linkage.get("source_evidence_provenance")},
        )

    if relationship == "MISMATCH":
        accepted = (
            mismatch_adjudication is not None
            and mismatch_adjudication.get("classification") == "HARMLESS_OCR_LINKAGE_MISMATCH"
            and mismatch_adjudication.get("confidence") in {"HIGH", "MEDIUM"}
            and mismatch_adjudication.get("layer") is None
        )
        text = str((mismatch_adjudication or {}).get("visual_text") or "").strip()
        if accepted and text:
            return _decision(
                linkage,
                renderable=True,
                text=text,
                authority="ACCEPTED_VISUAL_TEXT_LINKAGE_ADJUDICATION",
                source_field="adjudication_decisions[identity].visual_text",
                suppression_reason=None,
                provenance={"artifact": MISMATCH_ADJUDICATION_PATH, "decision": mismatch_adjudication},
            )
        return _decision(
            linkage,
            renderable=False,
            text=None,
            authority="CONTRADICTORY_TEXT_AUTHORITY",
            source_field=None,
            suppression_reason="UNSAFE_MISMATCH_WITHOUT_HIGHER_AUTHORITY",
            provenance={"artifact": LINKAGE_PATH, "source_evidence_provenance": linkage.get("source_evidence_provenance")},
        )

    if relationship in FRAGMENT_RELATIONSHIPS:
        text = str(linkage.get("font_scoring_text") or "").strip()
        if text:
            return _decision(
                linkage,
                renderable=True,
                text=text,
                authority=relationship,
                source_field="font_scoring_text",
                suppression_reason=None,
                provenance={"artifact": LINKAGE_PATH, "source_evidence_provenance": linkage.get("source_evidence_provenance")},
            )
        return _decision(
            linkage,
            renderable=False,
            text=None,
            authority=relationship,
            source_field=None,
            suppression_reason="ACCEPTED_FRAGMENT_WITHOUT_LITERAL_TEXT",
            provenance={"artifact": LINKAGE_PATH, "source_evidence_provenance": linkage.get("source_evidence_provenance")},
        )

    source_text = str(linkage.get("source_visible_text") or "").strip()
    font_text = str(linkage.get("font_scoring_text") or "").strip()
    contract_text = str(linkage.get("contract_text") or "").strip()
    source_authority = str((linkage.get("source_evidence_provenance") or {}).get("authority") or "")
    visual_agreement = (
        bool(source_text)
        and normalize_text(source_text) == normalize_text(font_text)
        and source_authority in STRONG_VISUAL_AUTHORITIES
    )
    if relationship == "EXACT_MATCH" and visual_agreement:
        if normalize_text(contract_text) == normalize_text(source_text):
            text, selected_authority, source_field = contract_text, "SAFE_CONTRACT_TEXT_AGREEMENT", "contract_text"
        else:
            text, selected_authority, source_field = source_text, "STRONG_ACCEPTED_VISUAL_TEXT", "source_visible_text"
        return _decision(
            linkage,
            renderable=True,
            text=text,
            authority=selected_authority,
            source_field=source_field,
            suppression_reason=None,
            provenance={"artifact": LINKAGE_PATH, "source_evidence_provenance": linkage.get("source_evidence_provenance")},
        )

    return _decision(
        linkage,
        renderable=False,
        text=None,
        authority="UNSAFE_OR_INCONSISTENT_TEXT_AUTHORITY",
        source_field=None,
        suppression_reason="NO_SAFE_DISPLAY_TEXT_AUTHORITY",
        provenance={"artifact": LINKAGE_PATH, "source_evidence_provenance": linkage.get("source_evidence_provenance")},
    )


def looks_transcript_like(text: str | None) -> bool:
    value = str(text or "")
    return any(marker in value for marker in (". ", "? ", "! ", "; ", ": ", ", "))


def _without_text_domain(row: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(row)
    value.pop("text", None)
    value.pop("renderable", None)
    value.pop("display_text_decision", None)
    return value


def compile_f2_contract(root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    base_contract, base_validation = compile_base_contract(root)
    linkage_path = root / LINKAGE_PATH
    mismatch_path = root / MISMATCH_ADJUDICATION_PATH
    display_path = root / DISPLAY_ADJUDICATION_PATH
    if sha(display_path) != EXPECTED_DISPLAY_ADJUDICATION_SHA256:
        raise ValueError("display_adjudication_hash_drift")
    linkage_artifact = read(linkage_path)
    mismatch_artifact = read(mismatch_path)
    display_artifact = read(display_path)
    linkage = {row["identity"]: row for row in linkage_artifact["identities"]}
    display = build_display_adjudications(display_artifact)
    base_ids = [row["source_identity"] for row in base_contract["objects"]]
    if len(base_ids) != 113 or set(base_ids) != set(linkage) or not set(display).issubset(linkage):
        raise ValueError("f2_identity_accounting")

    records: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    for base_row in base_contract["objects"]:
        identity = base_row["source_identity"]
        decision = select_display_text(linkage[identity], display.get(identity), mismatch_artifact.get(identity))
        row = copy.deepcopy(base_row)
        row["renderable"] = decision["renderable"]
        row["display_text_decision"] = decision
        row["text"] = {
            "value": decision["selected_display_text"],
            "source_authority": decision["display_text_authority"],
            "value_role": "SOURCE_SUPPORTED_VALUE" if decision["renderable"] else "UNSUPPORTED_OMITTED",
        }
        records.append(row)
        decisions.append(decision)

    objects = [row for row in records if row["renderable"]]
    suspicious = [
        row["source_identity"]
        for row in objects
        if looks_transcript_like(row["text"]["value"])
        and row["display_text_decision"]["display_text_authority"]
        not in {"ACCEPTED_DISPLAY_TEXT_ADJUDICATION", "STRONG_ACCEPTED_VISUAL_TEXT", "ACCEPTED_VISUAL_TEXT_LINKAGE_ADJUDICATION"}
    ]
    counts = {
        "total_frozen_identities": len(records),
        "renderable_identities": len(objects),
        "non_rendering_alias_identities": sum(str(row["suppression_reason"] or "").startswith("NON_RENDERING_") for row in decisions),
        "suppressed_unresolved_identities": sum(not row["renderable"] and row["text_mask_relationship"] == "EXPLICITLY_UNRESOLVED" for row in decisions),
        "suppressed_unsafe_mismatch_identities": sum(not row["renderable"] and row["text_mask_relationship"] == "MISMATCH" and not str(row["suppression_reason"] or "").startswith("NON_RENDERING_") for row in decisions),
        "suppressed_other_unsafe_identities": sum(not row["renderable"] and row["text_mask_relationship"] not in {"EXPLICITLY_UNRESOLVED", "MISMATCH"} and not str(row["suppression_reason"] or "").startswith("NON_RENDERING_") for row in decisions),
        "adjudicated_display_text_identities": len(display),
        "source_visual_text_identities": sum(row["display_text_authority"] in {"STRONG_ACCEPTED_VISUAL_TEXT", "ACCEPTED_VISUAL_TEXT_LINKAGE_ADJUDICATION"} for row in decisions),
        "accepted_fragment_identities": sum(row["renderable"] and row["display_text_authority"] in FRAGMENT_RELATIONSHIPS for row in decisions),
        "safe_contract_text_identities": sum(row["display_text_authority"] == "SAFE_CONTRACT_TEXT_AGREEMENT" for row in decisions),
    }
    inputs = dict(base_contract["inputs"])
    inputs.update({
        "text_mask_linkage": {"path": LINKAGE_PATH, "sha256": sha(linkage_path)},
        "mismatch_adjudication": {"path": MISMATCH_ADJUDICATION_PATH, "sha256": sha(mismatch_path)},
        "accepted_display_text_adjudication": {"path": DISPLAY_ADJUDICATION_PATH, "sha256": sha(display_path)},
    })
    contract = copy.deepcopy(base_contract)
    contract.update({
        "schema": "video_cloner_step5a_f2_text_authority_compile_contract",
        "schema_version": 1,
        "inputs": inputs,
        "base_compile_contract_sha256": digest(base_contract),
        "identity_count": len(records),
        "object_count": len(objects),
        "identity_records": records,
        "objects": objects,
        "text_authority_precedence": [
            "ACCEPTED_DISPLAY_TEXT_ADJUDICATION",
            "STRONG_CONSISTENT_ACCEPTED_VISUAL_TEXT",
            "ACCEPTED_VISUAL_FRAGMENT",
            "SAFE_CONTRACT_TEXT_AGREEMENT",
            "FAIL_CLOSED",
        ],
        "resolve_mutated": False,
    })
    checks = {
        "base_preflight_passed": base_validation["all_pass"] is True,
        "identity_accounting_113": len(records) == len(decisions) == 113,
        "renderable_object_filter_exact": len(objects) == sum(row["renderable"] for row in decisions),
        "no_renderable_identity_lacks_authority": all(row["selected_display_text"] and row["display_text_authority"] and row["source_provenance"] for row in decisions if row["renderable"]),
        "non_text_domains_unchanged": all(_without_text_domain(base) == _without_text_domain(current) for base, current in zip(base_contract["objects"], records)),
        "no_unsafe_transcript_like_visible_text": not suspicious,
        "all_adjudicated_members_follow_disposition": all(row["display_text_authority"] == "ACCEPTED_DISPLAY_TEXT_ADJUDICATION" for row in decisions if row["identity"] in display),
        "freeze_hashes_match": all(row["match"] for row in contract["freeze_integrity"]),
        "resolve_not_mutated": contract["resolve_mutated"] is False,
    }
    validation = {
        "schema": "video_cloner_step5a_f2_text_authority_validation",
        "schema_version": 1,
        "checks": checks,
        "all_pass": all(checks.values()),
        "counts": counts,
        "full_sentence_dump_cases_remaining": suspicious,
        "unsafe_visible_text_identities": [row["identity"] for row in decisions if row["renderable"] and (not row["selected_display_text"] or not row["source_provenance"])],
        "other_text_authority_blockers": [],
        "contract_sha256": digest(contract),
    }
    decision_artifact = {
        "schema": "video_cloner_step5a_f2_text_authority_decisions",
        "schema_version": 1,
        "inputs": {name: inputs[name] for name in ("text_mask_linkage", "mismatch_adjudication", "accepted_display_text_adjudication")},
        "counts": counts,
        "decisions": decisions,
    }
    return contract, validation, decision_artifact


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    out = Path(args.output_dir).resolve()
    out.mkdir(parents=True, exist_ok=False)
    first = compile_f2_contract()
    second = compile_f2_contract()
    names = ("step5a_f2_compile_contract.json", "step5a_f2_validation.json", "step5a_f2_text_authority_decisions.json")
    first_payloads = {name: json_bytes(value) for name, value in zip(names, first)}
    second_payloads = {name: json_bytes(value) for name, value in zip(names, second)}
    hashes = {
        name: {
            "first_sha256": hashlib.sha256(first_payloads[name]).hexdigest(),
            "second_sha256": hashlib.sha256(second_payloads[name]).hexdigest(),
            "byte_identical": first_payloads[name] == second_payloads[name],
        }
        for name in names
    }
    proof = {
        "schema": "video_cloner_step5a_f2_determinism_proof",
        "schema_version": 1,
        "artifacts": hashes,
        "deterministic": all(row["byte_identical"] for row in hashes.values()),
    }
    if not first[1]["all_pass"] or not proof["deterministic"]:
        raise SystemExit(2)
    for name, payload in first_payloads.items():
        (out / name).write_bytes(payload)
    (out / "step5a_f2_determinism_proof.json").write_bytes(json_bytes(proof))
    counts = first[1]["counts"]
    print(json.dumps({"ok": True, "output_dir": str(out), "counts": counts, "deterministic": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
