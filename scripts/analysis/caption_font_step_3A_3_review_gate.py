#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


VERSION = "caption_font_step_3A_3_visual_approval_gate_v1_0"

SYMBOL_FAMILIES = {
    "wingdings",
    "wingdings 2",
    "wingdings 3",
    "webdings",
    "marlett",
    "symbol",
    "segoe mdl2 assets",
    "segoe fluent icons",
}

JUNK_PATH_PARTS = {
    "packagecache",
    "packages~",
    "qtquick",
    "site-packages",
    "third_party",
    "test",
    "tests",
    "expected",
    "node_modules",
    "__pycache__",
}

FONT_EXTENSIONS = {".ttf", ".otf", ".ttc", ".otc"}


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)

    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")

    return value


def write_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def normalize(value: Any) -> str:
    return "".join(
        character.lower()
        for character in str(value or "")
        if character.isalnum()
    )


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_filename(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
    return value.strip("._") or "asset"


def normalized_path(path: Path) -> str:
    try:
        return os.path.normcase(os.path.abspath(str(path)))
    except Exception:
        return os.path.normcase(str(path))


def build_pool_lookup(preparation: Dict[str, Any]) -> Dict[str, str]:
    lookup: Dict[str, str] = {}

    manifest = (
        (preparation.get("font_pool") or {}).get("manifest")
        or []
    )

    for row in manifest:
        if not isinstance(row, dict):
            continue

        pool_path = str(row.get("pool_path") or "")
        source_path = str(row.get("source_path") or "")

        if pool_path and source_path:
            lookup[normalized_path(Path(pool_path))] = source_path

    return lookup


def candidate_source(
    candidate: Dict[str, Any],
    pool_lookup: Dict[str, str],
) -> Path:
    raw = str(
        candidate.get("original_source_file")
        or candidate.get("path")
        or candidate.get("font_file")
        or ""
    )

    path = Path(raw)
    return Path(pool_lookup.get(normalized_path(path), raw))


def candidate_is_usable(
    candidate: Dict[str, Any],
    source: Path,
) -> Tuple[bool, Optional[str]]:
    family = str(candidate.get("family") or "").strip()

    if not family:
        return False, "missing_family"

    if family.lower() in SYMBOL_FAMILIES:
        return False, "symbol_font"

    if source.suffix.lower() not in FONT_EXTENSIONS:
        return False, "unsupported_extension"

    lowered_parts = {part.lower() for part in source.parts}

    if lowered_parts.intersection(JUNK_PATH_PARTS):
        return False, "package_or_test_font"

    lowered_name = source.name.lower()

    if any(
        token in lowered_name
        for token in (
            "icons",
            "glyphs",
            "dummy",
            "testfont",
            "materialicons",
        )
    ):
        return False, "icon_or_test_font"

    if not source.is_file():
        return False, "font_file_missing"

    return True, None


def copy_asset(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)

    if destination.exists():
        return

    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def find_candidate(
    candidates: List[Dict[str, Any]],
    family: str,
    face: str,
) -> Optional[Dict[str, Any]]:
    wanted = (normalize(family), normalize(face or "Regular"))

    for candidate in candidates:
        key = (
            normalize(candidate.get("family")),
            normalize(candidate.get("face") or "Regular"),
        )

        if key == wanted:
            return candidate

    return None


def generate_review(args: argparse.Namespace) -> int:
    candidates_path = Path(args.candidates)
    preparation_path = Path(args.preparation_report)
    output_dir = Path(args.output_dir)

    candidates_payload = load_json(candidates_path)
    preparation = load_json(preparation_path)
    pool_lookup = build_pool_lookup(preparation)

    if output_dir.exists() and args.clear_output:
        shutil.rmtree(output_dir)

    font_dir = output_dir / "assets" / "fonts"
    crop_dir = output_dir / "assets" / "crops"

    font_dir.mkdir(parents=True, exist_ok=True)
    crop_dir.mkdir(parents=True, exist_ok=True)

    review_profiles: List[Dict[str, Any]] = []
    font_faces_css: List[str] = []
    rejected_candidates: List[Dict[str, Any]] = []

    for profile_index, profile in enumerate(
        candidates_payload.get("profiles") or [],
        start=1,
    ):
        if not isinstance(profile, dict):
            continue

        profile_id = str(
            profile.get("style_profile_id")
            or f"profile_{profile_index}"
        )

        samples = []

        for sample_index, sample in enumerate(
            profile.get("samples") or [],
            start=1,
        ):
            if not isinstance(sample, dict):
                continue

            crop_source = Path(str(sample.get("crop_path") or ""))
            crop_relative = None

            if crop_source.is_file():
                crop_name = safe_filename(
                    f"{profile_id}_{sample_index:02d}"
                    f"{crop_source.suffix.lower()}"
                )
                crop_destination = crop_dir / crop_name
                copy_asset(crop_source, crop_destination)
                crop_relative = (
                    Path("assets") / "crops" / crop_name
                ).as_posix()

            samples.append({
                "text": str(sample.get("text") or ""),
                "timestamp": sample.get("timestamp"),
                "cue_id": sample.get("cue_id"),
                "crop": crop_relative,
                "font_height_px": sample.get("font_height_px"),
            })

        options = []
        seen_pairs = set()

        for candidate in profile.get("candidates") or []:
            if not isinstance(candidate, dict):
                continue

            family = str(candidate.get("family") or "").strip()
            face = str(candidate.get("face") or "Regular").strip()
            pair = (normalize(family), normalize(face))

            if not all(pair) or pair in seen_pairs:
                continue

            seen_pairs.add(pair)
            source = candidate_source(candidate, pool_lookup)
            usable, rejection = candidate_is_usable(
                candidate,
                source,
            )

            if not usable:
                rejected_candidates.append({
                    "style_profile_id": profile_id,
                    "family": family,
                    "face": face,
                    "source": str(source),
                    "reason": rejection,
                })
                continue

            rank = len(options) + 1

            if rank > args.max_candidates:
                break

            font_name = safe_filename(
                f"{profile_index:02d}_{rank:02d}_{source.name}"
            )
            font_destination = font_dir / font_name
            copy_asset(source, font_destination)

            css_family = f"VCFont_{profile_index}_{rank}"
            relative_font = (
                Path("assets") / "fonts" / font_name
            ).as_posix()

            weight = int(candidate.get("weight_class") or 400)
            weight = max(100, min(900, weight))

            font_faces_css.append(
                "@font-face {"
                f"font-family:'{css_family}';"
                f"src:url('{relative_font}');"
                f"font-style:{'italic' if candidate.get('italic') else 'normal'};"
                f"font-weight:{weight};"
                "font-display:block;"
                "}"
            )

            options.append({
                "rank": rank,
                "family": family,
                "face": face,
                "font_file": str(source),
                "asset_font_file": relative_font,
                "css_family": css_family,
                "visual_score": safe_float(
                    candidate.get("visual_score")
                ),
                "raw_shape_score": safe_float(
                    candidate.get("raw_shape_score")
                ),
                "hint_penalty": safe_float(
                    candidate.get("hint_penalty")
                ),
                "installed_on_windows": bool(
                    candidate.get("installed_on_windows")
                ),
                "weight_class": weight,
                "italic": bool(candidate.get("italic")),
            })

        review_profiles.append({
            "style_profile_id": profile_id,
            "is_primary_style": bool(
                profile.get("is_primary_style")
            ),
            "selection_status": profile.get("selection_status"),
            "sample_count": len(samples),
            "samples": samples,
            "candidates": options,
        })

    review_data = {
        "schema": "video_cloner_caption_font_visual_review",
        "schema_version": "1.0",
        "version": VERSION,
        "source_candidates": str(candidates_path),
        "profiles": review_profiles,
    }

    write_json(output_dir / "review_data.json", review_data)

    template = {
        "schema": "video_cloner_caption_font_selection",
        "schema_version": "1.0",
        "version": VERSION,
        "instructions": (
            "Open index.html, select exactly one candidate per profile "
            "and use Download completed selection JSON."
        ),
        "selections": [],
    }

    write_json(
        output_dir / "font_selection_template.json",
        template,
    )

    css = "\n".join(font_faces_css)
    data_json = json.dumps(
        review_data,
        ensure_ascii=False,
    ).replace("</", "<\\/")

    sections: List[str] = []

    for profile in review_profiles:
        profile_id = html.escape(profile["style_profile_id"])
        primary = (
            " — PRIMARY"
            if profile["is_primary_style"]
            else ""
        )

        source_cards = []

        for sample in profile["samples"]:
            crop = sample.get("crop")

            if crop:
                source_cards.append(
                    "<figure class='source-sample'>"
                    f"<img src='{html.escape(crop)}' alt='Source crop'>"
                    f"<figcaption>{html.escape(sample['text'])}"
                    f" · {sample.get('timestamp')}</figcaption>"
                    "</figure>"
                )
            else:
                source_cards.append(
                    "<div class='missing-crop'>"
                    f"Missing crop: {html.escape(sample['text'])}"
                    "</div>"
                )

        candidate_cards = []

        for candidate in profile["candidates"]:
            rendered_words = "".join(
                "<div class='rendered-word' "
                f"style=\"font-family:'{candidate['css_family']}';"
                f"font-weight:{candidate['weight_class']};"
                f"font-style:{'italic' if candidate['italic'] else 'normal'}\">"
                f"{html.escape(sample['text'])}"
                "</div>"
                for sample in profile["samples"]
            )

            candidate_cards.append(
                "<label class='candidate-card'>"
                "<div class='candidate-header'>"
                f"<input type='radio' "
                f"name='{profile_id}' "
                f"data-profile='{profile_id}' "
                f"value='{candidate['rank']}'>"
                f"<strong>#{candidate['rank']} — "
                f"{html.escape(candidate['family'])} / "
                f"{html.escape(candidate['face'])}</strong>"
                f"<span>score {candidate['visual_score']:.6f}</span>"
                f"<span>{'installed' if candidate['installed_on_windows'] else 'not installed'}</span>"
                "</div>"
                f"{rendered_words}"
                "</label>"
            )

        sections.append(
            "<section class='profile'>"
            f"<h2>{profile_id}{primary}</h2>"
            f"<p>Status: {html.escape(str(profile['selection_status']))}; "
            f"samples: {profile['sample_count']}</p>"
            "<h3>Real source crops</h3>"
            f"<div class='source-grid'>{''.join(source_cards)}</div>"
            "<h3>Candidate renderings</h3>"
            f"<div class='candidate-grid'>{''.join(candidate_cards)}</div>"
            "</section>"
        )

    html_document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Video Cloner — Caption Font Review</title>
<style>
{css}
body {{
    background:#111;
    color:#eee;
    font-family:Arial,sans-serif;
    margin:0;
    padding:24px;
}}
main {{
    max-width:1500px;
    margin:auto;
}}
.profile {{
    border:1px solid #444;
    border-radius:12px;
    margin:0 0 30px;
    padding:20px;
    background:#191919;
}}
.source-grid {{
    display:grid;
    grid-template-columns:repeat(auto-fit,minmax(240px,1fr));
    gap:12px;
}}
.source-sample {{
    margin:0;
    background:#080808;
    padding:8px;
    border-radius:8px;
}}
.source-sample img {{
    width:100%;
    max-height:230px;
    object-fit:contain;
}}
.source-sample figcaption {{
    padding-top:6px;
    font-size:13px;
}}
.candidate-grid {{
    display:grid;
    gap:12px;
}}
.candidate-card {{
    display:block;
    background:#fff;
    color:#111;
    border:4px solid transparent;
    border-radius:10px;
    padding:14px;
    cursor:pointer;
}}
.candidate-card:has(input:checked) {{
    border-color:#ff6a00;
}}
.candidate-header {{
    display:flex;
    gap:16px;
    align-items:center;
    flex-wrap:wrap;
    font-family:Arial,sans-serif;
    border-bottom:1px solid #ccc;
    padding-bottom:8px;
    margin-bottom:8px;
}}
.rendered-word {{
    font-size:70px;
    line-height:1.15;
    overflow-wrap:anywhere;
}}
button {{
    font-size:18px;
    font-weight:bold;
    padding:14px 20px;
    margin:0 0 24px;
    cursor:pointer;
}}
.notice {{
    background:#30210e;
    border:1px solid #ff8c23;
    padding:14px;
    margin-bottom:20px;
}}
</style>
</head>
<body>
<main>
<h1>Major Step 3A.3 — Visual Font Approval</h1>
<div class="notice">
Compare letter construction only. Ignore source color, outline and shadow.
Choose one candidate for every profile. Do not choose based only on the score.
</div>
<button onclick="downloadSelection()">Download completed selection JSON</button>
{''.join(sections)}
</main>
<script>
const REVIEW = {data_json};

function downloadSelection() {{
    const selections = [];
    const missing = [];

    for (const profile of REVIEW.profiles) {{
        const selector =
            `input[data-profile="${{profile.style_profile_id}}"]:checked`;
        const checked = document.querySelector(selector);

        if (!checked) {{
            missing.push(profile.style_profile_id);
            continue;
        }}

        const rank = Number(checked.value);
        const candidate =
            profile.candidates.find(item => item.rank === rank);

        selections.push({{
            style_profile_id: profile.style_profile_id,
            is_primary_style: profile.is_primary_style,
            selected_rank: rank,
            candidate: candidate
        }});
    }}

    if (missing.length) {{
        alert("Missing selections: " + missing.join(", "));
        return;
    }}

    const output = {{
        schema: "video_cloner_caption_font_selection",
        schema_version: "1.0",
        version: "{VERSION}",
        source_candidates: REVIEW.source_candidates,
        selections: selections
    }};

    const blob = new Blob(
        [JSON.stringify(output, null, 2) + "\\n"],
        {{type:"application/json"}}
    );

    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download =
        "DZsqH7auhjt_caption_font_selection_step_3A_3.json";
    anchor.click();
    URL.revokeObjectURL(url);
}}
</script>
</body>
</html>
"""

    index_path = output_dir / "index.html"
    index_path.write_text(
        html_document,
        encoding="utf-8",
        newline="\n",
    )

    report = {
        "ok": bool(review_profiles),
        "version": VERSION,
        "profile_count": len(review_profiles),
        "candidate_count": sum(
            len(profile["candidates"])
            for profile in review_profiles
        ),
        "rejected_candidate_count": len(rejected_candidates),
        "rejected_candidates": rejected_candidates,
        "index": str(index_path),
        "review_data": str(output_dir / "review_data.json"),
    }

    write_json(
        output_dir / "review_generation_report.json",
        report,
    )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"OPEN: {index_path}")
    return 0


def generate_probe_payload(
    original_candidates: Dict[str, Any],
    selections: List[Dict[str, Any]],
) -> Dict[str, Any]:
    payload = dict(original_candidates)
    probe_rows = []

    selected_by_profile = {
        str(row.get("style_profile_id")): row
        for row in selections
    }

    for row in selections:
        candidate = row.get("candidate") or {}

        probe_rows.append({
            "family": candidate.get("family"),
            "face": candidate.get("face") or "Regular",
            "font_file": candidate.get("font_file"),
            "font_index": 0,
            "visual_score": candidate.get("visual_score"),
            "style_profile_ids": [
                row.get("style_profile_id")
            ],
            "source": "step_3A_3_visual_approval",
        })

    profiles = []

    for profile in original_candidates.get("profiles") or []:
        profile_copy = dict(profile)
        profile_id = str(profile.get("style_profile_id") or "")
        selection = selected_by_profile.get(profile_id)

        if selection:
            candidate = selection.get("candidate") or {}
            existing = list(profile.get("candidates") or [])
            matched = find_candidate(
                existing,
                str(candidate.get("family") or ""),
                str(candidate.get("face") or "Regular"),
            )

            selected_candidate = matched or {
                "path": candidate.get("font_file"),
                "index": 0,
                "family": candidate.get("family"),
                "face": candidate.get("face") or "Regular",
                "visual_score": candidate.get("visual_score"),
                "installed_on_windows": candidate.get(
                    "installed_on_windows",
                    False,
                ),
            }

            profile_copy["candidates"] = [
                selected_candidate,
                *[
                    item for item in existing
                    if (
                        normalize(item.get("family")),
                        normalize(item.get("face") or "Regular"),
                    ) != (
                        normalize(candidate.get("family")),
                        normalize(candidate.get("face") or "Regular"),
                    )
                ],
            ]

        profiles.append(profile_copy)

    payload["profiles"] = profiles
    payload["resolve_probe_candidates"] = probe_rows
    payload["step_3A_3_visual_selections"] = selections
    payload["analysis_version"] = (
        f"{payload.get('analysis_version', 'unknown')}"
        "+step_3A_3_visual_approval"
    )

    return payload


def powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def write_font_installer(
    selections: List[Dict[str, Any]],
    output: Path,
) -> int:
    fonts = []

    for selection in selections:
        candidate = selection.get("candidate") or {}

        if candidate.get("installed_on_windows"):
            continue

        source = Path(str(candidate.get("font_file") or ""))

        if source.is_file():
            fonts.append({
                "source": str(source),
                "family": str(candidate.get("family") or source.stem),
                "face": str(candidate.get("face") or "Regular"),
            })

    lines = [
        "$ErrorActionPreference = 'Stop'",
        "$fontDir = Join-Path $env:LOCALAPPDATA 'Microsoft\\Windows\\Fonts'",
        "$regPath = 'HKCU:\\Software\\Microsoft\\Windows NT\\CurrentVersion\\Fonts'",
        "New-Item -ItemType Directory -Path $fontDir -Force | Out-Null",
        "New-Item -Path $regPath -Force | Out-Null",
        "",
    ]

    for font in fonts:
        source = font["source"]
        filename = Path(source).name
        destination = (
            "$fontDir + '\\\\" + filename.replace("'", "''") + "'"
        )
        registry_name = (
            f"{font['family']} {font['face']} "
            f"({'OpenType' if Path(filename).suffix.lower() == '.otf' else 'TrueType'})"
        )

        lines.extend([
            f"$source = {powershell_quote(source)}",
            f"$destination = Join-Path $fontDir {powershell_quote(filename)}",
            "Copy-Item -LiteralPath $source -Destination $destination -Force",
            (
                "New-ItemProperty -Path $regPath "
                f"-Name {powershell_quote(registry_name)} "
                "-Value $destination -PropertyType String -Force "
                "| Out-Null"
            ),
            "",
        ])

    lines.append(
        "Write-Host 'Font installation complete. Restart DaVinci Resolve.'"
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8-sig",
    )

    return len(fonts)


def finalize(args: argparse.Namespace) -> int:
    selection_path = Path(args.selection)
    candidates_path = Path(args.candidates)
    inventory_path = Path(args.resolve_inventory)

    selection = load_json(selection_path)
    candidates = load_json(candidates_path)
    inventory = load_json(inventory_path)

    selections = selection.get("selections") or []

    accepted_pairs = {
        (
            normalize(row.get("family")),
            normalize(row.get("face") or "Regular"),
        )
        for row in inventory.get("accepted_candidates") or []
        if row.get("accepted")
    }

    mappings = []
    pending = []

    for row in selections:
        candidate = row.get("candidate") or {}
        pair = (
            normalize(candidate.get("family")),
            normalize(candidate.get("face") or "Regular"),
        )

        mapping = {
            "style_profile_id": row.get("style_profile_id"),
            "family": candidate.get("family"),
            "face": candidate.get("face") or "Regular",
            "font_file": candidate.get("font_file"),
            "visual_score": candidate.get("visual_score"),
            "human_visual_approved": True,
            "resolve_verified": pair in accepted_pairs,
        }

        if mapping["resolve_verified"]:
            mappings.append(mapping)
        else:
            pending.append(mapping)

    ready = bool(selections) and not pending

    mapping_output = Path(args.mapping_output)
    validation_output = Path(args.validation_output)
    probe_candidates_output = Path(args.probe_candidates_output)
    probe_config_path = Path(args.probe_config)
    installer_path = Path(args.installer_output)

    probe_payload = generate_probe_payload(
        candidates,
        selections,
    )
    write_json(probe_candidates_output, probe_payload)

    config = (
        load_json(probe_config_path)
        if probe_config_path.is_file()
        else {}
    )

    config["font_candidates"] = str(probe_candidates_output)
    config["resolve_font_inventory_output"] = str(inventory_path)
    config.setdefault("caption_textplus_track", 3)
    config.setdefault("caption_item_prefix", "VC_TEXTPLUS_")
    config["max_candidates"] = max(1, len(selections))

    write_json(probe_config_path, config)

    installer_count = write_font_installer(
        selections,
        installer_path,
    )

    mapping_payload = {
        "success": ready,
        "schema": "video_cloner_caption_font_mapping",
        "schema_version": "1.2",
        "analysis_version": VERSION,
        "primary_style_id": next(
            (
                row.get("style_profile_id")
                for row in selections
                if row.get("is_primary_style")
            ),
            None,
        ),
        "profile_mappings": mappings if ready else [],
        "pending_resolve_verification": pending,
        "ready_for_controller_apply": ready,
        "policy": {
            "human_visual_approval_required": True,
            "resolve_readback_required": True,
            "unsafe_installed_fallback_forbidden": True,
        },
    }

    validation_payload = {
        "ok": ready,
        "step": "Major Step 3A.3",
        "version": VERSION,
        "visual_selection_count": len(selections),
        "resolve_verified_count": len(mappings),
        "pending_count": len(pending),
        "ready_for_controller_apply": ready,
        "probe_candidates": str(probe_candidates_output),
        "probe_config": str(probe_config_path),
        "font_installer": str(installer_path),
        "font_installer_count": installer_count,
        "mapping_output": str(mapping_output),
        "failures": (
            []
            if ready
            else ["selected_fonts_not_yet_resolve_verified"]
        ),
    }

    write_json(mapping_output, mapping_payload)
    write_json(validation_output, validation_payload)

    print(json.dumps(
        validation_payload,
        ensure_ascii=False,
        indent=2,
    ))

    if ready:
        print(
            "PASS: Major Step 3A is visually approved and "
            "Resolve-verified."
        )
    else:
        print(
            "PENDING: Run the generated font installer when needed, "
            "restart Resolve, run resolve_probe_caption_font_candidates, "
            "then run this finalizer again."
        )

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    review = subparsers.add_parser("review")
    review.add_argument("--candidates", required=True)
    review.add_argument("--preparation-report", required=True)
    review.add_argument("--output-dir", required=True)
    review.add_argument("--max-candidates", type=int, default=6)
    review.add_argument(
        "--clear-output",
        action="store_true",
    )

    finalize_parser = subparsers.add_parser("finalize")
    finalize_parser.add_argument("--selection", required=True)
    finalize_parser.add_argument("--candidates", required=True)
    finalize_parser.add_argument(
        "--resolve-inventory",
        required=True,
    )
    finalize_parser.add_argument(
        "--mapping-output",
        required=True,
    )
    finalize_parser.add_argument(
        "--validation-output",
        required=True,
    )
    finalize_parser.add_argument(
        "--probe-candidates-output",
        required=True,
    )
    finalize_parser.add_argument(
        "--probe-config",
        required=True,
    )
    finalize_parser.add_argument(
        "--installer-output",
        required=True,
    )

    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.command == "review":
        return generate_review(args)

    if args.command == "finalize":
        return finalize(args)

    raise RuntimeError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())