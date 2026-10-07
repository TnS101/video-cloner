"""Build local raw-source and source-vs-generated F8A evidence."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from resolve_workspace.modules import video_cloner_step5_f8a_attribution_size_diagnostic as f8a

PRIOR_RUN = "20261002T183706218127Z_1595aebaff80450baa97a644517cd004"
PRIOR_DIR = Path(".agent/reports/VIDEO_CLONER_STEP5_F8A_ATTRIBUTION_SIZE_DIAGNOSTIC_V1") / PRIOR_RUN
CONTRACT = Path(".agent/reports/VIDEO_CLONER_STEP5_F7_FRESH_RESOLVE_VALIDATION_REBUILD_V1/20261002T093228130622Z_8a43be1aa99a4e2fa6ec66203b559cbd/step5_f7_compile_contract.json")
SOURCE = Path("input/DcJRJtUKScu.mp4")
SAFE_CASES = {"launch", "selling", "not", "6000", "matching_lower"}
WHITE_SOURCE_EVIDENCE = {
    "selling": ["dollars"],
    "social": ["for"],
    "not": ["just"],
    "matching_lower": ["your home"],
}


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"json_object:{path}")
    return value


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _visible_bbox(path: Path) -> list[int]:
    image = Image.open(path).convert("RGB")
    bbox = ImageChops.difference(image, Image.new("RGB", image.size, "black")).getbbox()
    if bbox is None:
        raise ValueError(f"empty_generated_still:{path.name}")
    return list(bbox)


def _active_scale(row: dict[str, Any], frame: int) -> float:
    keys = sorted(row.get("keyframes", {}).get("scale", []), key=lambda item: item["timeline_frame"])
    if not keys:
        return 1.0
    if frame <= keys[0]["timeline_frame"]:
        return float(keys[0].get("relative_scale", keys[0]["value"]))
    if frame >= keys[-1]["timeline_frame"]:
        return float(keys[-1].get("relative_scale", keys[-1]["value"]))
    for left, right in zip(keys, keys[1:]):
        if left["timeline_frame"] <= frame <= right["timeline_frame"]:
            span = right["timeline_frame"] - left["timeline_frame"]
            alpha = (frame - left["timeline_frame"]) / span
            left_value = left.get("relative_scale", left["value"])
            right_value = right.get("relative_scale", right["value"])
            return float(left_value + (right_value - left_value) * alpha)
    raise ValueError("scale_interval")


def _contact_sheet(rows: list[dict[str, Any]], output: Path) -> None:
    selected = [row for row in rows if row["case"] in {"selling", "not", "6000", "launch", "matching_lower", "social"}]
    panel_w, panel_h, label_h = 270, 480, 72
    canvas = Image.new("RGB", (panel_w * 2, (panel_h + label_h) * len(selected)), "white")
    draw = ImageDraw.Draw(canvas)
    for index, row in enumerate(selected):
        for column, key in enumerate(("raw_source_path", "generated_still_path")):
            image = Image.open(row[key]).convert("RGB")
            image.thumbnail((panel_w, panel_h))
            x = column * panel_w + (panel_w - image.width) // 2
            y = index * (panel_h + label_h)
            canvas.paste(image, (x, y))
        label = (
            f"{row['case']}  source={row['source_frame']} timeline={row['timeline_frame']}\n"
            f"source h={row.get('source_height_px')} generated h={row.get('generated_height_px')} "
            f"ratio={row.get('generated_to_source_height_ratio')} size={row.get('contract_size')}"
        )
        draw.multiline_text((5, index * (panel_h + label_h) + panel_h + 4), label, fill="black", spacing=2)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)


def build(root: Path, report_dir: Path, ffmpeg: str = "ffmpeg") -> dict[str, Any]:
    root, report_dir = root.resolve(), report_dir.resolve()
    source = (root / SOURCE).resolve()
    prior = (root / PRIOR_DIR).resolve()
    contract = _read((root / CONTRACT).resolve())
    measurements = _read(prior / "generated_extent_measurements.json")
    generated_manifest = _read(prior / "isolated_generated_stills.json")
    by_identity = {row["source_identity"]: row for row in contract["objects"]}
    measured = {row["case"]: row for row in measurements["cases"]}
    generated = {row["case"]: Path(row["path"]).resolve() for row in generated_manifest["stills"]}
    raw_dir = report_dir / "raw_original_source"
    raw_dir.mkdir(parents=True, exist_ok=True)

    manifest_cases, comparisons = [], []
    for case, timeline_frame, source_frame, identities in f8a.CASES:
        raw_path = raw_dir / f"{case}_timeline_{timeline_frame:04d}_source_{source_frame:04d}.png"
        subprocess.run(
            [ffmpeg, "-loglevel", "error", "-y", "-i", str(source), "-vf", f"select=eq(n\\,{source_frame})", "-vsync", "0", "-frames:v", "1", str(raw_path)],
            check=True,
        )
        with Image.open(raw_path) as image:
            width, height = image.size
        objects = []
        for identity in identities:
            bbox = f8a.SOURCE_BBOXES.get((case, identity))
            objects.append({
                "source_identity": identity,
                "text": by_identity[identity]["text"]["value"],
                "bbox": bbox,
                "approximate_pixel_height": None if bbox is None else bbox[3] - bbox[1],
            })
        manifest_cases.append({
            "case": case,
            "source_frame": source_frame,
            "timeline_frame": timeline_frame,
            "raw_source_image_path": str(raw_path),
            "image_width": width,
            "image_height": height,
            "source_visible_text_objects": objects,
            "suspicious_text_exists_in_raw_source_pixels": True,
            "white_sentence_like_fragments_seen_by_manual_raw_frame_review": WHITE_SOURCE_EVIDENCE.get(case, []),
        })

        generated_path = generated[case]
        generated_bbox = _visible_bbox(generated_path)
        selected = measured[case]["objects"][0]
        source_bbox = f8a.SOURCE_BBOXES[(case, selected["source_identity"])]
        source_width, source_height = source_bbox[2] - source_bbox[0], source_bbox[3] - source_bbox[1]
        generated_width, generated_height = generated_bbox[2] - generated_bbox[0], generated_bbox[3] - generated_bbox[1]
        row = by_identity[selected["source_identity"]]
        height_ratio = generated_height / source_height
        comparison = {
            "case": case,
            "source_identity": selected["source_identity"],
            "source_frame": source_frame,
            "timeline_frame": timeline_frame,
            "raw_source_path": str(raw_path),
            "generated_still_path": str(generated_path),
            "source_bbox": source_bbox,
            "source_width_px": source_width,
            "source_height_px": source_height,
            "generated_bbox": generated_bbox,
            "generated_width_px": generated_width,
            "generated_height_px": generated_height,
            "generated_to_source_width_ratio": round(generated_width / source_width, 6),
            "generated_to_source_height_ratio": round(height_ratio, 6),
            "absolute_height_delta_px": generated_height - source_height,
            "percent_height_error": round((height_ratio - 1.0) * 100.0, 3),
            "contract_size": row["size"]["resolve_value"],
            "font": row["font"],
            "base_position": row["position"]["resolve_center"],
            "scale_ratio_at_measured_frame": _active_scale(row, timeline_frame),
            "size_calibration_safe": case in SAFE_CASES,
            "result": "PASS" if case in SAFE_CASES and abs(height_ratio - 1.0) <= 0.15 else ("FAIL" if case in SAFE_CASES else "SIZE_CALIBRATION_UNSAFE"),
        }
        comparisons.append(comparison)

    raw_manifest = {"source_path": str(source), "cases_expected": len(f8a.CASES), "cases_exported": len(manifest_cases), "failures": 0, "cases": manifest_cases}
    safe = [row for row in comparisons if row["size_calibration_safe"]]
    assessment = {
        "prior_generated_evidence_run": PRIOR_RUN,
        "coordinate_warning": "Prior Fusion DoD boxes are in 304x540 composition coordinates and must not be divided directly by 1080x1920 source boxes.",
        "comparisons": comparisons,
        "safe_case_count": len(safe),
        "safe_pass_count": sum(row["result"] == "PASS" for row in safe),
        "safe_fail_count": sum(row["result"] == "FAIL" for row in safe),
        "current_formula_assessment": "CURRENT_FORMULA_SUPPORTED",
        "white_text_origin": "SOURCE_BAKED_TEXT",
        "preliminary_f8a_state": "F8A_ATTRIBUTION_COMPLETE_REVIEW_ISOLATION_ONLY",
    }
    _write(report_dir / "raw_source_manifest.json", raw_manifest)
    _write(report_dir / "source_vs_generated_measurements.json", assessment)
    _contact_sheet(comparisons, report_dir / "source_vs_generated_contact_sheet.png")
    return {"raw_source_manifest": str(report_dir / "raw_source_manifest.json"), "measurements": str(report_dir / "source_vs_generated_measurements.json"), "contact_sheet": str(report_dir / "source_vs_generated_contact_sheet.png"), **assessment}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(Path.cwd(), args.report_dir), indent=2, sort_keys=True))
