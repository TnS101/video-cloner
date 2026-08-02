#!/usr/bin/env python3
"""Build a normalized, de-duplicated caption foreground-matte span contract.

Step 2C of Video Cloner caption occlusion.

Input:
    *_caption_occlusion.json produced by detect_caption_occlusion.py v1.9+

Output:
    *_caption_matte_contract.json plus canonical per-span mask directories.

The builder only consumes events explicitly approved for editor compositing. It
merges overlapping/adjacent intervals, keeps one canonical alpha mask per source
frame, verifies every image, and records all de-duplication/conflict decisions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover - reported cleanly at runtime
    cv2 = None

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None


VERSION = "caption_matte_contract_v1_0_interval_merge_dedup"
SCHEMA = "video_cloner_caption_matte_contract"
SCHEMA_VERSION = "1.0"
STABLE_CUE_RE = re.compile(r"^sub_\d{4}$")
SPAN_DIR_RE = re.compile(r"^matte_span_\d{4}$")


def str2bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Expected boolean, got {value!r}")


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def format_mask_path(pattern: str, frame: int) -> Path:
    try:
        return Path(pattern % int(frame))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid mask pattern {pattern!r}: {exc}") from exc


def safe_clear_span_root(root: Path) -> None:
    """Delete only builder-owned matte_span_* folders and marker/manifest files."""
    root.mkdir(parents=True, exist_ok=True)
    for child in root.iterdir():
        if child.is_dir() and SPAN_DIR_RE.fullmatch(child.name):
            shutil.rmtree(child)
        elif child.is_file() and child.name in {
            ".video_cloner_caption_matte_spans",
            "contract_manifest.json",
        }:
            child.unlink()


def materialize_file(source: Path, destination: Path, mode: str) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    if mode == "copy":
        shutil.copy2(source, destination)
        return "copy"
    if mode == "hardlink_or_copy":
        try:
            os.link(source, destination)
            return "hardlink"
        except OSError:
            shutil.copy2(source, destination)
            return "copy_fallback"
    raise ValueError(f"Unsupported copy mode: {mode}")


def read_mask(path: Path, expected_width: int, expected_height: int) -> Tuple[Any, Optional[str]]:
    if cv2 is None:
        return None, "opencv_not_available"
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None or getattr(image, "size", 0) == 0:
        return None, "unreadable_png"
    height, width = image.shape[:2]
    if width != expected_width or height != expected_height:
        return image, f"dimension_mismatch:{width}x{height}!={expected_width}x{expected_height}"
    return image, None


def write_mask(path: Path, image: Any) -> None:
    if cv2 is None:
        raise RuntimeError("OpenCV is required to write merged masks.")
    path.parent.mkdir(parents=True, exist_ok=True)
    ok = bool(cv2.imwrite(str(path), image))
    if not ok:
        raise RuntimeError(f"Could not write mask: {path}")


@dataclass
class ApprovedEvent:
    index: int
    event_id: str
    cue_id: str
    text: str
    event_start_seconds: float
    event_end_seconds: float
    source_frame_start: int
    source_frame_end_exclusive: int
    width: int
    height: int
    encoding: str
    pattern: str
    relative_pattern: Optional[str]
    confidence: float
    exact_overlap: float
    layer_order: str
    mask_asset: Dict[str, Any]
    raw_event: Dict[str, Any]

    @property
    def duration_frames(self) -> int:
        return self.source_frame_end_exclusive - self.source_frame_start

    def source_path(self, frame: int) -> Path:
        return format_mask_path(self.pattern, frame)


@dataclass
class SpanAccumulator:
    start: int
    end: int
    width: int
    height: int
    encoding: str
    events: List[ApprovedEvent] = field(default_factory=list)

    def compatible_with(self, event: ApprovedEvent) -> bool:
        return (
            self.width == event.width
            and self.height == event.height
            and self.encoding == event.encoding
        )


def event_is_editor_ready(event: Dict[str, Any]) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    occlusion = event.get("occlusion") if isinstance(event.get("occlusion"), dict) else {}
    asset = event.get("mask_asset") if isinstance(event.get("mask_asset"), dict) else {}
    cue_id = str(event.get("cue_id") or "")

    if not occlusion.get("ready_for_editor_compositing"):
        reasons.append("ready_for_editor_compositing_false")
    if not occlusion.get("needs_foreground_mask"):
        reasons.append("needs_foreground_mask_false")
    if str(occlusion.get("layer_order") or "") != "foreground_over_text":
        reasons.append("layer_order_not_foreground_over_text")
    if bool(occlusion.get("review_required")):
        reasons.append("review_required_true")
    if not STABLE_CUE_RE.fullmatch(cue_id):
        reasons.append("invalid_stable_cue_id")
    if not asset.get("complete"):
        reasons.append("mask_asset_incomplete")
    if not asset.get("mask_pattern"):
        reasons.append("mask_pattern_missing")

    start = int(asset.get("source_frame_start") or 0)
    end = int(asset.get("source_frame_end_exclusive") or 0)
    expected = int(asset.get("frame_count_expected") or 0)
    written = int(asset.get("frame_count_written") or 0)
    if end <= start:
        reasons.append("invalid_frame_interval")
    if expected != end - start:
        reasons.append("expected_frame_count_mismatch")
    if written != expected:
        reasons.append("written_frame_count_mismatch")

    return not reasons, reasons


def parse_approved_events(payload: Dict[str, Any]) -> Tuple[List[ApprovedEvent], List[Dict[str, Any]]]:
    approved: List[ApprovedEvent] = []
    rejected: List[Dict[str, Any]] = []
    events = payload.get("occlusion_events")
    if not isinstance(events, list):
        return [], [{"reason": "occlusion_events_missing"}]

    for raw in events:
        if not isinstance(raw, dict):
            continue
        ok, reasons = event_is_editor_ready(raw)
        if not ok:
            # Normal non-approved events are not errors; preserve only events that
            # claimed readiness but failed the strict contract.
            occ = raw.get("occlusion") if isinstance(raw.get("occlusion"), dict) else {}
            if occ.get("ready_for_editor_compositing"):
                rejected.append({
                    "index": raw.get("index"),
                    "event_id": raw.get("id"),
                    "cue_id": raw.get("cue_id"),
                    "reasons": reasons,
                })
            continue

        occ = raw["occlusion"]
        asset = raw["mask_asset"]
        approved.append(ApprovedEvent(
            index=int(raw.get("index") or 0),
            event_id=str(raw.get("id") or raw.get("caption_event_id") or ""),
            cue_id=str(raw.get("cue_id") or ""),
            text=str(raw.get("text") or raw.get("observed_text") or ""),
            event_start_seconds=float(raw.get("start") or 0.0),
            event_end_seconds=float(raw.get("end") or 0.0),
            source_frame_start=int(asset.get("source_frame_start")),
            source_frame_end_exclusive=int(asset.get("source_frame_end_exclusive")),
            width=int(asset.get("width") or 0),
            height=int(asset.get("height") or 0),
            encoding=str(asset.get("mask_encoding") or "grayscale_u8_0_background_255_foreground"),
            pattern=str(asset.get("mask_pattern")),
            relative_pattern=str(asset.get("relative_mask_pattern")) if asset.get("relative_mask_pattern") else None,
            confidence=float(occ.get("classification_confidence") or 0.0),
            exact_overlap=float(occ.get("median_exact_foreground_overlap") or 0.0),
            layer_order=str(occ.get("layer_order") or ""),
            mask_asset=asset,
            raw_event=raw,
        ))

    approved.sort(key=lambda item: (item.source_frame_start, item.source_frame_end_exclusive, item.index))
    return approved, rejected


def merge_event_intervals(events: Sequence[ApprovedEvent], merge_gap_frames: int) -> Tuple[List[SpanAccumulator], List[Dict[str, Any]]]:
    spans: List[SpanAccumulator] = []
    incompatibilities: List[Dict[str, Any]] = []
    for event in events:
        if event.width <= 0 or event.height <= 0:
            incompatibilities.append({"event_index": event.index, "reason": "invalid_mask_dimensions"})
            continue
        if not spans:
            spans.append(SpanAccumulator(
                start=event.source_frame_start,
                end=event.source_frame_end_exclusive,
                width=event.width,
                height=event.height,
                encoding=event.encoding,
                events=[event],
            ))
            continue

        current = spans[-1]
        touches = event.source_frame_start <= current.end + merge_gap_frames
        if touches and current.compatible_with(event):
            current.end = max(current.end, event.source_frame_end_exclusive)
            current.events.append(event)
        elif touches and not current.compatible_with(event):
            incompatibilities.append({
                "left_event_indexes": [item.index for item in current.events],
                "right_event_index": event.index,
                "reason": "overlapping_intervals_have_incompatible_mask_contracts",
                "left": {"width": current.width, "height": current.height, "encoding": current.encoding},
                "right": {"width": event.width, "height": event.height, "encoding": event.encoding},
            })
            spans.append(SpanAccumulator(
                start=event.source_frame_start,
                end=event.source_frame_end_exclusive,
                width=event.width,
                height=event.height,
                encoding=event.encoding,
                events=[event],
            ))
        else:
            spans.append(SpanAccumulator(
                start=event.source_frame_start,
                end=event.source_frame_end_exclusive,
                width=event.width,
                height=event.height,
                encoding=event.encoding,
                events=[event],
            ))
    return spans, incompatibilities


def candidate_priority(event: ApprovedEvent) -> Tuple[float, float, int]:
    return (event.confidence, event.exact_overlap, -event.index)


def build_contract(args: argparse.Namespace) -> Dict[str, Any]:
    started = time.time()
    input_path = Path(args.occlusion).resolve()
    output_path = Path(args.output).resolve()
    span_root = Path(args.span_mask_root).resolve()
    payload = load_json(input_path)

    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    analysis_version = str(payload.get("analysis_version") or "")
    if args.require_analysis_version_prefix and not analysis_version.startswith(args.require_analysis_version_prefix):
        errors.append({
            "code": "analysis_version_mismatch",
            "expected_prefix": args.require_analysis_version_prefix,
            "actual": analysis_version,
        })

    if not payload.get("success") or not payload.get("ok"):
        errors.append({"code": "source_occlusion_analysis_not_ok"})

    approved, strict_rejections = parse_approved_events(payload)
    if strict_rejections:
        errors.append({"code": "claimed_editor_ready_events_failed_strict_validation", "events": strict_rejections})

    source_summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    declared_ready = int(source_summary.get("editor_ready_matte_count") or 0)
    if declared_ready != len(approved):
        errors.append({
            "code": "editor_ready_count_mismatch",
            "declared": declared_ready,
            "strictly_approved": len(approved),
        })

    if not approved and not args.allow_zero_spans:
        errors.append({"code": "no_editor_ready_matte_events"})

    spans, incompatibilities = merge_event_intervals(approved, max(0, int(args.merge_gap_frames)))
    if incompatibilities:
        errors.extend({"code": "interval_merge_incompatibility", **row} for row in incompatibilities)

    if args.clear_output:
        safe_clear_span_root(span_root)
    span_root.mkdir(parents=True, exist_ok=True)
    (span_root / ".video_cloner_caption_matte_spans").write_text(VERSION + "\n", encoding="utf-8")

    fps = float(payload.get("fps") or (payload.get("video_info") or {}).get("fps") or 24.0)
    timeline_offset = int(args.timeline_frame_offset)

    total_input_frame_refs = sum(event.duration_frames for event in approved)
    unique_frame_numbers: set[int] = set()
    overlap_frame_numbers: set[int] = set()
    duplicate_refs_removed = 0
    hash_conflict_count = 0
    missing_frame_count = 0
    unreadable_frame_count = 0
    canonical_frames_written = 0
    copy_method_counts: Dict[str, int] = {}
    contract_spans: List[Dict[str, Any]] = []

    for span_number, span in enumerate(spans, start=1):
        span_id = f"matte_span_{span_number:04d}"
        span_dir = span_root / span_id
        span_dir.mkdir(parents=True, exist_ok=True)
        frame_rows: List[Dict[str, Any]] = []
        span_errors: List[Dict[str, Any]] = []
        span_overlap_frames = 0
        span_duplicate_refs_removed = 0
        span_hash_conflicts = 0

        candidate_map: Dict[int, List[Tuple[ApprovedEvent, Path]]] = {}
        for event in span.events:
            for frame in range(event.source_frame_start, event.source_frame_end_exclusive):
                candidate_map.setdefault(frame, []).append((event, event.source_path(frame)))

        for frame in range(span.start, span.end):
            unique_frame_numbers.add(frame)
            candidates = candidate_map.get(frame, [])
            if not candidates:
                missing_frame_count += 1
                span_errors.append({"frame": frame, "code": "no_source_mask_candidate"})
                continue

            if len(candidates) > 1:
                overlap_frame_numbers.add(frame)
                span_overlap_frames += 1
                duplicate_refs_removed += len(candidates) - 1
                span_duplicate_refs_removed += len(candidates) - 1

            candidate_rows: List[Dict[str, Any]] = []
            valid_candidates: List[Tuple[ApprovedEvent, Path, str, Any]] = []
            for event, path in candidates:
                row: Dict[str, Any] = {
                    "event_index": event.index,
                    "event_id": event.event_id,
                    "cue_id": event.cue_id,
                    "path": str(path),
                    "exists": path.is_file(),
                }
                image = None
                error = None
                file_hash = None
                if not path.is_file():
                    error = "missing_source_mask"
                else:
                    file_hash = sha256_file(path)
                    if args.verify_images:
                        image, error = read_mask(path, span.width, span.height)
                row["sha256"] = file_hash
                row["error"] = error
                candidate_rows.append(row)
                if error:
                    if error == "missing_source_mask":
                        missing_frame_count += 1
                    else:
                        unreadable_frame_count += 1
                else:
                    valid_candidates.append((event, path, str(file_hash), image))

            if not valid_candidates:
                span_errors.append({"frame": frame, "code": "no_valid_source_masks", "candidates": candidate_rows})
                continue

            hashes = {item[2] for item in valid_candidates}
            canonical_path = span_dir / f"mask_{frame:06d}.png"
            selection_reason = "single_candidate"
            selected_event: Optional[ApprovedEvent] = None
            selected_source: Optional[Path] = None
            output_hash: Optional[str] = None
            materialization_method: Optional[str] = None

            if len(hashes) == 1:
                selected_event, selected_source, output_hash, _ = max(valid_candidates, key=lambda item: candidate_priority(item[0]))
                selection_reason = "identical_duplicate_hashes" if len(valid_candidates) > 1 else "single_candidate"
                materialization_method = materialize_file(selected_source, canonical_path, args.copy_mode)
            else:
                hash_conflict_count += 1
                span_hash_conflicts += 1
                if args.overlap_conflict_policy == "fail":
                    span_errors.append({
                        "frame": frame,
                        "code": "overlap_mask_hash_conflict",
                        "candidates": candidate_rows,
                    })
                    continue
                if args.overlap_conflict_policy == "highest_confidence":
                    selected_event, selected_source, output_hash, _ = max(valid_candidates, key=lambda item: candidate_priority(item[0]))
                    selection_reason = "hash_conflict_highest_confidence"
                    materialization_method = materialize_file(selected_source, canonical_path, args.copy_mode)
                elif args.overlap_conflict_policy == "max_alpha":
                    if cv2 is None or np is None:
                        span_errors.append({"frame": frame, "code": "max_alpha_requires_opencv_and_numpy"})
                        continue
                    images = []
                    for event, path, _, image in valid_candidates:
                        if image is None:
                            image, read_error = read_mask(path, span.width, span.height)
                            if read_error:
                                span_errors.append({"frame": frame, "code": read_error, "path": str(path)})
                                images = []
                                break
                        images.append(image)
                    if not images:
                        continue
                    merged = np.maximum.reduce(images)
                    write_mask(canonical_path, merged)
                    output_hash = sha256_file(canonical_path)
                    selection_reason = "hash_conflict_max_alpha_union"
                    materialization_method = "generated_max_alpha"
                else:
                    span_errors.append({"frame": frame, "code": "unknown_overlap_conflict_policy"})
                    continue

            if materialization_method:
                copy_method_counts[materialization_method] = copy_method_counts.get(materialization_method, 0) + 1
            canonical_frames_written += 1
            frame_rows.append({
                "source_frame": frame,
                "timeline_frame": frame + timeline_offset,
                "canonical_path": str(canonical_path),
                "canonical_sha256": output_hash,
                "candidate_count": len(candidates),
                "valid_candidate_count": len(valid_candidates),
                "selection_reason": selection_reason,
                "selected_event_index": selected_event.index if selected_event else None,
                "selected_cue_id": selected_event.cue_id if selected_event else None,
                "selected_source_path": str(selected_source) if selected_source else None,
                "materialization_method": materialization_method,
                "candidates": candidate_rows,
            })

        cue_ids = sorted({event.cue_id for event in span.events})
        texts = [event.text for event in sorted(span.events, key=lambda item: item.index)]
        canonical_pattern = str(span_dir / "mask_%06d.png")
        relative_pattern = str(Path(span_id) / "mask_%06d.png")
        expected_count = span.end - span.start
        span_complete = (
            not span_errors
            and len(frame_rows) == expected_count
            and all(Path(row["canonical_path"]).is_file() for row in frame_rows)
        )
        source_events = [{
            "event_index": event.index,
            "event_id": event.event_id,
            "cue_id": event.cue_id,
            "text": event.text,
            "event_start_seconds": event.event_start_seconds,
            "event_end_seconds": event.event_end_seconds,
            "source_frame_start": event.source_frame_start,
            "source_frame_end_exclusive": event.source_frame_end_exclusive,
            "classification_confidence": event.confidence,
            "median_exact_foreground_overlap": event.exact_overlap,
            "input_mask_pattern": event.pattern,
            "input_mask_manifest": event.mask_asset.get("manifest"),
        } for event in span.events]

        manifest = {
            "schema": "video_cloner_caption_matte_span_manifest",
            "schema_version": "1.0",
            "builder_version": VERSION,
            "span_id": span_id,
            "complete": span_complete,
            "source_frame_start": span.start,
            "source_frame_end_exclusive": span.end,
            "timeline_frame_start": span.start + timeline_offset,
            "timeline_frame_end_exclusive": span.end + timeline_offset,
            "duration_frames": expected_count,
            "fps": fps,
            "width": span.width,
            "height": span.height,
            "mask_encoding": span.encoding,
            "mask_pattern": canonical_pattern,
            "relative_mask_pattern": relative_pattern,
            "affected_cue_ids": cue_ids,
            "source_events": source_events,
            "deduplication": {
                "input_frame_references": sum(event.duration_frames for event in span.events),
                "unique_frames": expected_count,
                "overlap_frame_count": span_overlap_frames,
                "duplicate_frame_references_removed": span_duplicate_refs_removed,
                "hash_conflict_count": span_hash_conflicts,
            },
            "frame_assets": frame_rows,
            "errors": span_errors,
        }
        manifest_path = span_dir / "manifest.json"
        atomic_write_json(manifest_path, manifest)

        contract_spans.append({
            "span_id": span_id,
            "complete": span_complete,
            "layer_order": "foreground_over_text",
            "composition_order": ["base_video", "caption_textplus_v3", "foreground_matte_v4"],
            "source_frame_start": span.start,
            "source_frame_end_exclusive": span.end,
            "timeline_frame_start": span.start + timeline_offset,
            "timeline_frame_end_exclusive": span.end + timeline_offset,
            "duration_frames": expected_count,
            "start_seconds": round(span.start / fps, 6),
            "end_seconds": round(span.end / fps, 6),
            "fps": fps,
            "affected_cue_ids": cue_ids,
            "affected_texts": texts,
            "source_event_indexes": [event.index for event in span.events],
            "source_event_ids": [event.event_id for event in span.events],
            "source_events": source_events,
            "mask_asset": {
                "asset_type": "png_sequence_alpha_mask",
                "mask_encoding": span.encoding,
                "root": str(span_root),
                "event_dir": str(span_dir),
                "mask_pattern": canonical_pattern,
                "relative_mask_pattern": relative_pattern,
                "manifest": str(manifest_path),
                "source_frame_start": span.start,
                "source_frame_end_exclusive": span.end,
                "frame_count_expected": expected_count,
                "frame_count_written": len(frame_rows),
                "width": span.width,
                "height": span.height,
                "complete": span_complete,
            },
            "deduplication": manifest["deduplication"],
            "renderer_hints": {
                "preferred_asset_build": "full_resolution_rgba_foreground_from_source_video_plus_alpha_sequence",
                "resolve_target_track": "V4 foreground matte above V3 TextPlus",
                "frame_semantics": "zero_based_source_frames_end_exclusive",
                "timeline_frame_offset": timeline_offset,
            },
            "errors": span_errors,
        })

    # Verify spans themselves are normalized and non-overlapping after merge.
    interval_conflicts: List[Dict[str, Any]] = []
    for left, right in zip(contract_spans, contract_spans[1:]):
        if int(right["source_frame_start"]) <= int(left["source_frame_end_exclusive"]):
            interval_conflicts.append({
                "left_span_id": left["span_id"],
                "right_span_id": right["span_id"],
                "left_end_exclusive": left["source_frame_end_exclusive"],
                "right_start": right["source_frame_start"],
            })
    if interval_conflicts:
        errors.append({"code": "normalized_spans_still_overlap_or_touch", "conflicts": interval_conflicts})

    complete_span_count = sum(1 for span in contract_spans if span.get("complete"))
    incomplete_span_count = len(contract_spans) - complete_span_count
    if incomplete_span_count:
        errors.append({"code": "incomplete_canonical_spans", "count": incomplete_span_count})
    if hash_conflict_count and args.overlap_conflict_policy == "fail":
        errors.append({"code": "mask_hash_conflicts", "count": hash_conflict_count})
    if missing_frame_count:
        errors.append({"code": "missing_mask_frames", "count": missing_frame_count})
    if unreadable_frame_count:
        errors.append({"code": "unreadable_or_wrong_size_mask_frames", "count": unreadable_frame_count})

    contract_ready = bool(
        not errors
        and complete_span_count == len(contract_spans)
        and (len(contract_spans) > 0 or args.allow_zero_spans)
    )

    result: Dict[str, Any] = {
        "success": contract_ready,
        "ok": contract_ready,
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "builder_version": VERSION,
        "created_at_unix": time.time(),
        "elapsed_seconds": round(time.time() - started, 4),
        "inputs": {
            "caption_occlusion": str(input_path),
            "source_analysis_version": analysis_version,
            "source_video": (payload.get("inputs") or {}).get("video"),
        },
        "outputs": {
            "contract": str(output_path),
            "span_mask_root": str(span_root),
        },
        "config": {
            "merge_gap_frames": int(args.merge_gap_frames),
            "timeline_frame_offset": timeline_offset,
            "copy_mode": args.copy_mode,
            "overlap_conflict_policy": args.overlap_conflict_policy,
            "verify_images": bool(args.verify_images),
            "clear_output": bool(args.clear_output),
            "allow_zero_spans": bool(args.allow_zero_spans),
        },
        "video_info": {
            **(payload.get("video_info") if isinstance(payload.get("video_info"), dict) else {}),
            "fps": fps,
        },
        "summary": {
            "source_events_analyzed_count": int(source_summary.get("events_analyzed_count") or 0),
            "source_editor_ready_matte_count": declared_ready,
            "strictly_approved_event_count": len(approved),
            "input_interval_count": len(approved),
            "normalized_matte_span_count": len(contract_spans),
            "complete_span_count": complete_span_count,
            "incomplete_span_count": incomplete_span_count,
            "input_frame_reference_count": total_input_frame_refs,
            "unique_source_frame_count": len(unique_frame_numbers),
            "overlap_frame_count": len(overlap_frame_numbers),
            "duplicate_frame_references_removed": duplicate_refs_removed,
            "mask_hash_conflict_count": hash_conflict_count,
            "missing_frame_count": missing_frame_count,
            "unreadable_frame_count": unreadable_frame_count,
            "canonical_frames_written": canonical_frames_written,
            "copy_method_counts": copy_method_counts,
            "interval_conflict_count": len(interval_conflicts),
            "ready_for_matte_asset_build": contract_ready,
            "ready_for_merge_analysis": contract_ready,
            "ready_for_editor_compilers": contract_ready,
        },
        "approved_events": [{
            "event_index": event.index,
            "event_id": event.event_id,
            "cue_id": event.cue_id,
            "text": event.text,
            "source_frame_start": event.source_frame_start,
            "source_frame_end_exclusive": event.source_frame_end_exclusive,
            "duration_frames": event.duration_frames,
            "classification_confidence": event.confidence,
            "median_exact_foreground_overlap": event.exact_overlap,
            "mask_pattern": event.pattern,
        } for event in approved],
        "matte_spans": contract_spans,
        "errors": errors,
        "warnings": warnings,
    }

    atomic_write_json(output_path, result)
    atomic_write_json(span_root / "contract_manifest.json", {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "builder_version": VERSION,
        "contract": str(output_path),
        "ready": contract_ready,
        "span_count": len(contract_spans),
        "created_at_unix": result["created_at_unix"],
    })
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build normalized de-duplicated caption matte spans.")
    parser.add_argument("--occlusion", required=True, help="Path to *_caption_occlusion.json (v1.9+).")
    parser.add_argument("--output", required=True, help="Path to write *_caption_matte_contract.json.")
    parser.add_argument("--span-mask-root", required=True, help="Directory for canonical matte_span_XXXX mask sequences.")
    parser.add_argument("--merge-gap-frames", type=int, default=0, help="Merge overlapping or adjacent intervals up to this frame gap. Default: 0.")
    parser.add_argument("--timeline-frame-offset", type=int, default=0, help="Timeline frame offset added to source frames. Default: 0.")
    parser.add_argument("--copy-mode", choices=["hardlink_or_copy", "copy"], default="hardlink_or_copy")
    parser.add_argument("--overlap-conflict-policy", choices=["fail", "highest_confidence", "max_alpha"], default="fail")
    parser.add_argument("--verify-images", type=str2bool, default=True)
    parser.add_argument("--clear-output", type=str2bool, default=True)
    parser.add_argument("--allow-zero-spans", type=str2bool, default=False)
    parser.add_argument("--require-analysis-version-prefix", default="caption_occlusion_v1_9")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = build_contract(args)
    except Exception as exc:
        failure = {
            "success": False,
            "ok": False,
            "schema": SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "builder_version": VERSION,
            "error": f"{type(exc).__name__}: {exc}",
        }
        try:
            atomic_write_json(Path(args.output).resolve(), failure)
        except Exception:
            pass
        print(json.dumps(failure, ensure_ascii=False))
        return 1

    print(json.dumps({
        "success": result.get("success"),
        "output": result.get("outputs", {}).get("contract"),
        "span_mask_root": result.get("outputs", {}).get("span_mask_root"),
        **result.get("summary", {}),
    }, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
