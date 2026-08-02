#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


VERSION = "caption_font_step_3A_2_strict_accuracy_v1_0"
FONT_EXTENSIONS = {".ttf", ".otf", ".ttc", ".otc"}

JUNK_PATH_PARTS = {
    ".git",
    "__pycache__",
    "node_modules",
    "site-packages",
    "third_party",
    "tests",
    "test",
    "expected",
    "cache",
    "caches",
    "gradio",
    "matplotlib",
    "harfbuzz",
    "katex",
}

JUNK_FILE_PATTERNS = (
    "glyphs.ttf",
    "cmsy10.ttf",
    "cmr10.ttf",
    "cmex10.ttf",
    "dummy",
    "testfont",
)


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")

    return payload


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalized_token(value: Any) -> str:
    return "".join(
        character.lower()
        for character in normalize_text(value)
        if character.isalnum()
    )


def normalized_pair(family: Any, face: Any) -> Tuple[str, str]:
    return normalized_token(family), normalized_token(face or "Regular")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def event_confidence(event: Dict[str, Any]) -> float:
    value = event.get("confidence")

    if isinstance(value, dict):
        value = value.get("score")

    return safe_float(value)


def event_quality(event: Dict[str, Any]) -> Tuple[float, float, float, float]:
    match = event.get("match") or {}

    confidence = event_confidence(event)
    match_score = safe_float(match.get("score"))
    text_similarity = safe_float(match.get("text_similarity"))

    combined = (
        0.40 * confidence
        + 0.30 * match_score
        + 0.30 * text_similarity
    )

    return confidence, match_score, text_similarity, combined


def event_text(event: Dict[str, Any]) -> str:
    match = event.get("match") or {}
    cue = normalize_text(match.get("cue_text"))
    observed = normalize_text(event.get("observed_text") or event.get("text"))

    if cue and normalized_token(cue) == normalized_token(observed):
        return cue

    return observed


def event_timestamp(event: Dict[str, Any]) -> float:
    if event.get("mid") is not None:
        return safe_float(event.get("mid"))

    start = safe_float(event.get("start"))
    end = safe_float(event.get("end"))

    return (start + end) / 2.0


def choose_clean_events(
    report: Dict[str, Any],
    min_confidence: float,
    min_match_score: float,
    min_text_similarity: float,
    min_chars: int,
    max_chars: int,
    samples_per_profile: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    events = (
        report.get("caption_style_events")
        or report.get("style_events")
        or []
    )

    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    rejection_counts: Dict[str, int] = defaultdict(int)

    for event in events:
        if not isinstance(event, dict):
            rejection_counts["not_an_object"] += 1
            continue

        cue_id = normalize_text(event.get("cue_id"))
        if not cue_id:
            rejection_counts["missing_cue_id"] += 1
            continue

        text = event_text(event)
        token = normalized_token(text)

        if len(token) < min_chars:
            rejection_counts["text_too_short"] += 1
            continue

        if len(token) > max_chars:
            rejection_counts["text_too_long"] += 1
            continue

        confidence, match_score, similarity, combined = event_quality(event)

        if confidence < min_confidence:
            rejection_counts["low_confidence"] += 1
            continue

        if match_score < min_match_score:
            rejection_counts["low_match_score"] += 1
            continue

        if similarity < min_text_similarity:
            rejection_counts["low_text_similarity"] += 1
            continue

        placement = event.get("placement") or {}
        bbox = placement.get("bbox")

        if not isinstance(bbox, list) or len(bbox) != 4:
            rejection_counts["missing_bbox"] += 1
            continue

        profile_id = normalize_text(
            event.get("style_profile_id") or "unassigned"
        )

        row = dict(event)
        row["_font_selection_quality"] = round(combined, 6)
        row["_font_selection_text"] = text

        grouped[profile_id].append(row)

    selected: List[Dict[str, Any]] = []
    selected_counts: Dict[str, int] = {}

    for profile_id, rows in grouped.items():
        rows.sort(
            key=lambda row: (
                -safe_float(row.get("_font_selection_quality")),
                -len(normalized_token(row.get("_font_selection_text"))),
                event_timestamp(row),
            )
        )

        profile_selected: List[Dict[str, Any]] = []
        seen_tokens = set()

        for row in rows:
            token = normalized_token(row.get("_font_selection_text"))

            if token in seen_tokens:
                continue

            seen_tokens.add(token)
            profile_selected.append(row)

            if len(profile_selected) >= samples_per_profile:
                break

        selected.extend(profile_selected)
        selected_counts[profile_id] = len(profile_selected)

    selected.sort(
        key=lambda event: (
            event_timestamp(event),
            normalize_text(event.get("style_profile_id")),
        )
    )

    audit = {
        "input_event_count": len(events),
        "clean_event_count": len(selected),
        "selected_counts_by_profile": selected_counts,
        "rejection_counts": dict(sorted(rejection_counts.items())),
        "thresholds": {
            "min_confidence": min_confidence,
            "min_match_score": min_match_score,
            "min_text_similarity": min_text_similarity,
            "min_chars": min_chars,
            "max_chars": max_chars,
            "samples_per_profile": samples_per_profile,
        },
    }

    return selected, audit


def is_junk_font_path(path: Path) -> bool:
    lowered_parts = [part.lower() for part in path.parts]
    lowered_name = path.name.lower()

    if any(part in JUNK_PATH_PARTS for part in lowered_parts):
        return True

    if any(part.startswith("venv") for part in lowered_parts):
        return True

    if "virtual environments" in lowered_parts:
        return True

    if any(pattern in lowered_name for pattern in JUNK_FILE_PATTERNS):
        return True

    return False


def iter_font_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return

    if root.is_file():
        if root.suffix.lower() in FONT_EXTENSIONS:
            yield root
        return

    for path in root.rglob("*"):
        if not path.is_file():
            continue

        if path.suffix.lower() not in FONT_EXTENSIONS:
            continue

        yield path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def build_clean_font_pool(
    roots: Sequence[Path],
    pool_dir: Path,
    max_fonts: int,
) -> Dict[str, Any]:
    if pool_dir.exists():
        shutil.rmtree(pool_dir)

    pool_dir.mkdir(parents=True, exist_ok=True)

    seen_hashes = set()
    manifest: List[Dict[str, Any]] = []
    rejection_counts: Dict[str, int] = defaultdict(int)

    pool_absolute = os.path.normcase(os.path.abspath(str(pool_dir)))

    for root in roots:
        if not root.exists():
            rejection_counts[f"missing_root:{root}"] += 1
            continue

        for source in iter_font_files(root):
            source_absolute = os.path.normcase(os.path.abspath(str(source)))

            if source_absolute.startswith(pool_absolute + os.sep):
                continue

            if is_junk_font_path(source):
                rejection_counts["junk_path"] += 1
                continue

            try:
                digest = file_sha256(source)
            except (OSError, PermissionError):
                rejection_counts["unreadable"] += 1
                continue

            if digest in seen_hashes:
                rejection_counts["duplicate_content"] += 1
                continue

            seen_hashes.add(digest)

            destination = pool_dir / f"{digest[:12]}_{source.name}"

            try:
                os.link(source, destination)
                copy_method = "hardlink"
            except OSError:
                try:
                    shutil.copy2(source, destination)
                    copy_method = "copy"
                except OSError:
                    rejection_counts["copy_failed"] += 1
                    continue

            manifest.append({
                "source_path": str(source),
                "pool_path": str(destination),
                "sha256": digest,
                "copy_method": copy_method,
            })

            if max_fonts > 0 and len(manifest) >= max_fonts:
                rejection_counts["max_fonts_reached"] += 1
                break

        if max_fonts > 0 and len(manifest) >= max_fonts:
            break

    return {
        "pool_dir": str(pool_dir),
        "font_count": len(manifest),
        "manifest": manifest,
        "rejection_counts": dict(sorted(rejection_counts.items())),
    }


def prepare(args: argparse.Namespace) -> int:
    source_path = Path(args.caption_style)
    output_path = Path(args.output_style)
    report_path = Path(args.preparation_report)
    pool_dir = Path(args.font_pool)

    source = load_json(source_path)

    selected_events, event_audit = choose_clean_events(
        source,
        min_confidence=args.min_confidence,
        min_match_score=args.min_match_score,
        min_text_similarity=args.min_text_similarity,
        min_chars=args.min_chars,
        max_chars=args.max_chars,
        samples_per_profile=args.samples_per_profile,
    )

    if not selected_events:
        raise RuntimeError("No reliable caption events survived the strict filter")

    filtered = dict(source)
    filtered["caption_style_events"] = selected_events

    if "style_events" in filtered:
        filtered["style_events"] = selected_events

    filtered["font_detection_filter"] = {
        "version": VERSION,
        **event_audit,
    }

    write_json(output_path, filtered)

    pool_report = build_clean_font_pool(
        roots=[Path(root) for root in args.download_font_root],
        pool_dir=pool_dir,
        max_fonts=args.max_download_fonts,
    )

    report = {
        "success": True,
        "version": VERSION,
        "source_caption_style": str(source_path),
        "filtered_caption_style": str(output_path),
        "event_audit": event_audit,
        "font_pool": pool_report,
    }

    write_json(report_path, report)

    print(json.dumps({
        "success": True,
        "filtered_caption_style": str(output_path),
        "clean_events": event_audit["clean_event_count"],
        "font_pool": str(pool_dir),
        "downloaded_fonts_kept": pool_report["font_count"],
        "preparation_report": str(report_path),
    }, ensure_ascii=False))

    return 0


def source_path_lookup(preparation: Dict[str, Any]) -> Dict[str, str]:
    lookup: Dict[str, str] = {}

    for row in (
        (preparation.get("font_pool") or {}).get("manifest")
        or []
    ):
        pooled = os.path.normcase(
            os.path.abspath(str(row.get("pool_path") or ""))
        )

        if pooled:
            lookup[pooled] = str(row.get("source_path") or "")

    return lookup


def robust_candidate_score(candidate: Dict[str, Any]) -> Dict[str, float]:
    scores = sorted(
        safe_float(row.get("score"))
        for row in candidate.get("sample_scores") or []
        if safe_float(row.get("score")) > 0
    )

    if not scores:
        fallback = safe_float(candidate.get("visual_score"))

        return {
            "robust_score": round(fallback, 6),
            "sample_mean": round(fallback, 6),
            "sample_median": round(fallback, 6),
            "sample_min": round(fallback, 6),
            "sample_stdev": 0.0,
        }

    mean = statistics.fmean(scores)
    median = statistics.median(scores)
    minimum = min(scores)
    stdev = statistics.pstdev(scores) if len(scores) > 1 else 0.0
    lower_quartile = scores[max(0, int(math.floor((len(scores) - 1) * 0.25)))]

    robust = (
        0.45 * median
        + 0.25 * lower_quartile
        + 0.20 * mean
        + 0.10 * minimum
    )

    robust -= min(0.10, stdev * 0.22)
    robust = max(0.0, robust)

    return {
        "robust_score": round(robust, 6),
        "sample_mean": round(mean, 6),
        "sample_median": round(median, 6),
        "sample_min": round(minimum, 6),
        "sample_stdev": round(stdev, 6),
    }


def rank_profile_candidates(
    profile: Dict[str, Any],
    pool_lookup: Dict[str, str],
    accepted_pairs: Dict[Tuple[str, str], Dict[str, Any]],
) -> List[Dict[str, Any]]:
    deduplicated: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for candidate in profile.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue

        family = normalize_text(candidate.get("family"))
        face = normalize_text(candidate.get("face") or "Regular")

        if not family:
            continue

        key = normalized_pair(family, face)
        path = str(candidate.get("path") or "")
        normalized_path = os.path.normcase(os.path.abspath(path))
        original_source = pool_lookup.get(normalized_path, path)

        scores = robust_candidate_score(candidate)

        row = {
            "family": family,
            "face": face,
            "font_file": path,
            "original_source_file": original_source,
            "installed_on_windows": bool(
                candidate.get("installed_on_windows")
            ),
            "resolve_verified": key in accepted_pairs,
            "detector_visual_score": safe_float(
                candidate.get("visual_score")
            ),
            **scores,
        }

        existing = deduplicated.get(key)

        if (
            existing is None
            or row["robust_score"] > existing["robust_score"]
        ):
            deduplicated[key] = row

    ranked = list(deduplicated.values())
    ranked.sort(
        key=lambda row: (
            -row["robust_score"],
            -row["sample_min"],
            -int(row["resolve_verified"]),
        )
    )

    for index, row in enumerate(ranked, start=1):
        row["rank"] = index

    return ranked


def validate(args: argparse.Namespace) -> int:
    candidates_path = Path(args.candidates)
    inventory_path = Path(args.resolve_inventory)
    preparation_path = Path(args.preparation_report)
    mapping_path = Path(args.mapping_output)
    validation_path = Path(args.validation_output)

    candidates = load_json(candidates_path)
    inventory = load_json(inventory_path)
    preparation = load_json(preparation_path)

    accepted_pairs: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for row in inventory.get("accepted_candidates") or []:
        if not isinstance(row, dict) or not row.get("accepted"):
            continue

        key = normalized_pair(row.get("family"), row.get("face"))
        accepted_pairs[key] = row

    pool_lookup = source_path_lookup(preparation)
    primary_style_id = normalize_text(
        candidates.get("primary_style_id")
    )

    profile_audits: List[Dict[str, Any]] = []
    resolved_mappings: List[Dict[str, Any]] = []
    unresolved_ids: List[str] = []
    installation_shortlist: List[Dict[str, Any]] = []

    for profile in candidates.get("profiles") or []:
        if not isinstance(profile, dict):
            continue

        profile_id = normalize_text(profile.get("style_profile_id"))
        is_primary = profile_id == primary_style_id
        sample_count = int(profile.get("sample_count") or 0)

        ranked = rank_profile_candidates(
            profile,
            pool_lookup,
            accepted_pairs,
        )

        top = ranked[0] if ranked else None
        second = ranked[1] if len(ranked) > 1 else None

        top_score = safe_float((top or {}).get("robust_score"))
        second_score = safe_float((second or {}).get("robust_score"))
        margin = top_score - second_score

        minimum_samples = (
            args.min_primary_samples
            if is_primary
            else args.min_secondary_samples
        )

        if not top:
            status = "no_candidates"
        elif sample_count < minimum_samples:
            status = "insufficient_clean_samples"
        elif top_score < args.min_robust_score:
            status = "weak_visual_match"
        elif margin < args.min_margin:
            status = "ambiguous_visual_candidates"
        elif not top["installed_on_windows"]:
            status = "pending_font_installation"
        elif not top["resolve_verified"]:
            status = "exact_pair_not_verified_by_resolve"
        else:
            status = "resolved"

        audit = {
            "style_profile_id": profile_id,
            "is_primary_style": is_primary,
            "sample_count": sample_count,
            "required_sample_count": minimum_samples,
            "status": status,
            "top_score": round(top_score, 6),
            "top_two_margin": round(margin, 6),
            "top_candidate": top,
            "shortlist": ranked[:5],
        }

        profile_audits.append(audit)

        if status == "resolved" and top:
            resolved_mappings.append({
                "style_profile_id": profile_id,
                "family": top["family"],
                "face": top["face"],
                "font_file": top["font_file"],
                "original_source_file": top["original_source_file"],
                "robust_score": top["robust_score"],
                "resolve_verified": True,
                "source": (
                    "strict_visual_rerank_plus_exact_resolve_readback"
                ),
            })
        else:
            unresolved_ids.append(profile_id)

        if status == "pending_font_installation" and top:
            installation_shortlist.append({
                "style_profile_id": profile_id,
                "family": top["family"],
                "face": top["face"],
                "font_file_to_install": top["original_source_file"],
                "robust_score": top["robust_score"],
            })

    primary_mapping = next(
        (
            mapping
            for mapping in resolved_mappings
            if mapping["style_profile_id"] == primary_style_id
        ),
        None,
    )

    ready_for_primary_apply = primary_mapping is not None
    ready_for_full_apply = (
        bool(profile_audits)
        and len(unresolved_ids) == 0
    )

    mapping = {
        "success": True,
        "schema": "video_cloner_caption_font_mapping",
        "schema_version": "1.1",
        "analysis_version": VERSION,
        "primary_style_id": primary_style_id or None,
        "primary_mapping": primary_mapping,
        "profile_mappings": resolved_mappings,
        "unresolved_style_profile_ids": unresolved_ids,
        "installation_shortlist": installation_shortlist,
        "ready_for_primary_controller_apply": ready_for_primary_apply,
        "ready_for_full_controller_apply": ready_for_full_apply,
        "fallback_policy": {
            "unresolved_profiles_inherit_primary_mapping": False,
            "best_installed_candidate_may_replace_visual_best": False,
            "exact_visual_family_face_must_be_resolve_verified": True,
            "ambiguous_profiles_may_be_automatically_applied": False,
        },
        "inputs": {
            "font_candidates": str(candidates_path),
            "resolve_font_inventory": str(inventory_path),
            "preparation_report": str(preparation_path),
        },
    }

    validation = {
        "ok": True,
        "validator_version": VERSION,
        "step": "Major Step 3A.2",
        "technical_pipeline_valid": True,
        "semantic_mapping_valid": ready_for_full_apply,
        "primary_mapping_valid": ready_for_primary_apply,
        "ready_for_controller_apply": ready_for_full_apply,
        "primary_style_id": primary_style_id or None,
        "resolved_profile_count": len(resolved_mappings),
        "unresolved_profile_count": len(unresolved_ids),
        "profile_audits": profile_audits,
        "installation_shortlist": installation_shortlist,
        "mapping_output": str(mapping_path),
        "warnings": (
            []
            if ready_for_full_apply
            else [
                "Font mapping is not ready for automatic V3 application.",
                "Do not use the old Step 3A v1.0 mapping.",
            ]
        ),
        "failures": [],
    }

    write_json(mapping_path, mapping)
    write_json(validation_path, validation)

    print(json.dumps({
        "success": True,
        "step": "Major Step 3A.2",
        "resolved_profiles": len(resolved_mappings),
        "unresolved_profiles": len(unresolved_ids),
        "ready_for_primary_apply": ready_for_primary_apply,
        "ready_for_full_apply": ready_for_full_apply,
        "mapping": str(mapping_path),
        "validation": str(validation_path),
    }, ensure_ascii=False))

    if ready_for_full_apply:
        print(
            "PASS: Strict font mapping is visually supported and "
            "Resolve-verified."
        )
    else:
        print(
            "BLOCKED: No unsafe installed-font fallback was produced. "
            "Review the validation shortlist."
        )

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Major Step 3A.2: prepare reliable font samples and "
            "strictly validate visual font mappings."
        )
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--caption-style", required=True)
    prepare_parser.add_argument("--output-style", required=True)
    prepare_parser.add_argument("--font-pool", required=True)
    prepare_parser.add_argument(
        "--download-font-root",
        action="append",
        default=[],
    )
    prepare_parser.add_argument(
        "--preparation-report",
        required=True,
    )
    prepare_parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.60,
    )
    prepare_parser.add_argument(
        "--min-match-score",
        type=float,
        default=0.85,
    )
    prepare_parser.add_argument(
        "--min-text-similarity",
        type=float,
        default=0.90,
    )
    prepare_parser.add_argument("--min-chars", type=int, default=4)
    prepare_parser.add_argument("--max-chars", type=int, default=18)
    prepare_parser.add_argument(
        "--samples-per-profile",
        type=int,
        default=8,
    )
    prepare_parser.add_argument(
        "--max-download-fonts",
        type=int,
        default=1200,
    )

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--candidates", required=True)
    validate_parser.add_argument(
        "--resolve-inventory",
        required=True,
    )
    validate_parser.add_argument(
        "--preparation-report",
        required=True,
    )
    validate_parser.add_argument(
        "--mapping-output",
        required=True,
    )
    validate_parser.add_argument(
        "--validation-output",
        required=True,
    )
    validate_parser.add_argument(
        "--min-primary-samples",
        type=int,
        default=3,
    )
    validate_parser.add_argument(
        "--min-secondary-samples",
        type=int,
        default=2,
    )
    validate_parser.add_argument(
        "--min-robust-score",
        type=float,
        default=0.58,
    )
    validate_parser.add_argument(
        "--min-margin",
        type=float,
        default=0.015,
    )

    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.command == "prepare":
        return prepare(args)

    if args.command == "validate":
        return validate(args)

    raise RuntimeError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(
            json.dumps({
                "success": False,
                "version": VERSION,
                "error": f"{type(error).__name__}: {error}",
            }, ensure_ascii=False),
            file=sys.stderr,
        )
        raise