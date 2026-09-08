"""Roll out the locked remaining-100 Step 3E visual authority on an isolated timeline.

The task duplicates the visually approved 17-token V4 timeline. Exactly the 100
remaining VC_TEXTPLUS_* items are removed and recreated at source-pixel timing.
Each source item's current Fusion comp is exported before duplication and
re-imported into its replacement so static style (font/fill/outline/shadow and
other comp-level styling) is preserved. Only dense Center, Size and layer
opacity paths are rewritten from the locked 803-row authority.

The 17 already-approved VC_VISUAL_FIRST_FULL_* items are read-only and are
verified against the successful Step 3E.3 persistent readback before and after
save. Fade-in/fade-out refinement is explicitly deferred to a later patch.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

TASK_ID = "DZSQH7AUHJT_STEP_3E_REMAINING100_FULL_ROLLOUT_V1"
MODE = "STEP_3E_REMAINING100_FULL_ROLLOUT"
MODULE_RELATIVE_PATH = "resolve_workspace/modules/step_3E_remaining100_full_rollout_v1.py"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_17tokens_v1"
TARGET_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_all117_v1"
AUTHORITY_RELATIVE_PATH = "artifacts/DZSQH7AUHJT_STEP_3E_REMAINING100_VISUAL_AUTHORITY_V1/remaining100_visual_authority_v1.json"
AUTHORITY_VALIDATION_RELATIVE_PATH = "artifacts/DZSQH7AUHJT_STEP_3E_REMAINING100_VISUAL_AUTHORITY_V1/remaining100_visual_authority_validation.json"
STEP3E3_PERSISTENT_RELATIVE_PATH = (
    ".agent/reports/DZSQH7AUHJT_STEP_3E_FULL_BASELINE_VISUAL_POLISH_V1/"
    "20260810T110941414962Z_97d2818ffaf14c26b29ca6207316aa0d/persistent_readback.json"
)
STEP3E3_REPORT_RELATIVE_PATH = (
    ".agent/reports/DZSQH7AUHJT_STEP_3E_FULL_BASELINE_VISUAL_POLISH_V1/"
    "20260810T110941414962Z_97d2818ffaf14c26b29ca6207316aa0d/report.json"
)
ACCEPTED_STATE_RELATIVE_PATH = ".agent/state/latest_accepted.json"
EXPECTED_REMAINING = 100
EXPECTED_PROTECTED = 17
EXPECTED_TOTAL = 117
EXPECTED_FRAME_ROWS = 803
EXPECTED_EXISTING_VISUAL_PRIMARY = 39
EXPECTED_PIXEL_REDETECTED = 61
TRACK_MIN = 3
TRACK_MAX = 7
APPEND_BATCH_SIZE = 6
FULL_PREFIX = "VC_VISUAL_FIRST_FULL_"
STATIC_STYLE_INPUTS = (
    "StyledText", "Font", "Style",
    "Red1", "Green1", "Blue1", "Alpha1",
    "Enabled2", "Red2", "Green2", "Blue2", "Alpha2", "Thickness2",
    "Enabled3", "Red3", "Green3", "Blue3", "Alpha3",
    "VerticalJustificationNew", "HorizontalJustificationNew",
)
OPACITY_INPUTS = ("Opacity1", "Opacity2", "Opacity3")


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def _runtime_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_runtime() -> Tuple[Any, Any, Any, Any, Any, Any]:
    full = _runtime_module(Path(__file__).with_name("step_3D_visual_first_full_rollout_baseline.py"), "vc_full_for_step3e_remaining100")
    visual = _runtime_module(Path(__file__).with_name("step_3D_visual_instance_correction.py"), "vc_visual_for_step3e_remaining100")
    return full, full.pilot, full.v6, full.base, full.media, visual


def authority_instances(authority: Mapping[str, Any]) -> List[Dict[str, Any]]:
    if authority.get("task_id") != "DZSQH7AUHJT_STEP_3E_REMAINING100_VISUAL_AUTHORITY_V1" or authority.get("ok") is not True:
        raise ValueError("authority_identity")
    policy = authority.get("authority_policy") if isinstance(authority.get("authority_policy"), Mapping) else {}
    summary = authority.get("summary") if isinstance(authority.get("summary"), Mapping) else {}
    protected = authority.get("protected_v4") if isinstance(authority.get("protected_v4"), Mapping) else {}
    if policy.get("primary_authority") != "source_video_pixels_and_previously_accepted_source_visual_tracks":
        raise ValueError("primary_authority")
    if policy.get("transcript_timing_authority") is not False or policy.get("resolve_modified") is not False:
        raise ValueError("authority_policy")
    if policy.get("remaining_caption_rollout_authorized") is not False:
        raise ValueError("authority_pre_rollout_lock")
    expected = {
        "remaining_instance_count": EXPECTED_REMAINING,
        "accepted_visual_primary_instance_count": EXPECTED_EXISTING_VISUAL_PRIMARY,
        "source_pixel_redetected_instance_count": EXPECTED_PIXEL_REDETECTED,
        "explicit_frame_row_count": EXPECTED_FRAME_ROWS,
        "low_confidence_pixel_readback_count": 0,
        "protected_v4_token_count": EXPECTED_PROTECTED,
    }
    for key, value in expected.items():
        if summary.get(key) != value:
            raise ValueError(f"authority_summary:{key}:{summary.get(key)}")
    if protected.get("token_count") != EXPECTED_PROTECTED:
        raise ValueError("protected_token_count")
    rows = authority.get("instances")
    if not isinstance(rows, list) or len(rows) != EXPECTED_REMAINING:
        raise ValueError("authority_instances")
    result = [dict(row) for row in rows if isinstance(row, Mapping)]
    if len(result) != EXPECTED_REMAINING:
        raise ValueError("authority_instance_type")
    names = [str(row.get("target_name") or "") for row in result]
    ids = [str(row.get("instance_id") or "") for row in result]
    if not all(names) or len(set(names)) != EXPECTED_REMAINING or not all(ids) or len(set(ids)) != EXPECTED_REMAINING:
        raise ValueError("authority_identity_duplicates")
    return result


def build_unassigned_plans(authority: Mapping[str, Any]) -> List[Dict[str, Any]]:
    plans: List[Dict[str, Any]] = []
    total = 0
    for row in authority_instances(authority):
        instance_id = str(row["instance_id"])
        window = [int(value) for value in row.get("visual_window") or []]
        path = row.get("frame_path")
        if len(window) != 2 or window[1] <= window[0] or not isinstance(path, list) or not path:
            raise ValueError(f"visual_window:{instance_id}")
        frames = [int(frame["timeline_frame"]) for frame in path]
        if frames != list(range(window[0], window[1])):
            raise ValueError(f"dense_path:{instance_id}")
        if int(row.get("explicit_frame_row_count") or 0) != len(path):
            raise ValueError(f"frame_count:{instance_id}")
        total += len(path)
        position_keys = []
        size_keys = []
        opacity_keys = []
        for frame in path:
            timeline_frame = int(frame["timeline_frame"])
            local = timeline_frame - window[0]
            fusion = [float(v) for v in frame.get("position_fusion") or []]
            if len(fusion) != 2:
                raise ValueError(f"position:{instance_id}:{timeline_frame}")
            size = float(frame["application_size_candidate"])
            opacity = float(frame["opacity_factor"])
            if size <= 0.0 or not 0.0 <= opacity <= 1.0:
                raise ValueError(f"frame_value:{instance_id}:{timeline_frame}")
            position_keys.append({"timeline_frame": timeline_frame, "local_frame": local, "value": fusion})
            size_keys.append({"timeline_frame": timeline_frame, "local_frame": local, "value": size})
            opacity_keys.append({"timeline_frame": timeline_frame, "local_frame": local, "factor": opacity})
        style = row.get("style") if isinstance(row.get("style"), Mapping) else {}
        font = style.get("font") if isinstance(style.get("font"), Mapping) else {}
        if not font.get("font_family") or not font.get("font_style"):
            raise ValueError(f"font:{instance_id}")
        plans.append({
            "instance_id": instance_id,
            "target_name": str(row["target_name"]),
            "display_text": str(row.get("canonical_text") or ""),
            "target_range": window,
            "visual_window": window,
            "target_track": 0,
            "font": {"font_family": str(font["font_family"]), "font_style": str(font["font_style"])},
            "fill_hex": str(style.get("fill_hex") or ""),
            "visual_timing_authority": str(row.get("visual_timing_authority") or ""),
            "transcript_timing_authority": False,
            "position_keys": position_keys,
            "size_keys": size_keys,
            "opacity_keys": opacity_keys,
        })
    if total != EXPECTED_FRAME_ROWS:
        raise ValueError(f"explicit_frame_rows:{total}")
    return plans


def intervals_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return int(a_start) < int(b_end) and int(b_start) < int(a_end)


def assign_tracks(plans: Sequence[Mapping[str, Any]], occupied_rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    occupied: Dict[int, List[Tuple[int, int, str]]] = {track: [] for track in range(TRACK_MIN, TRACK_MAX + 1)}
    for row in occupied_rows:
        track = int(row.get("track_index") or 0)
        if track not in occupied:
            continue
        start, end = int(row.get("start") or 0), int(row.get("end") or 0)
        if end > start:
            occupied[track].append((start, end, str(row.get("name") or "")))
    result: List[Dict[str, Any]] = []
    for raw in sorted(plans, key=lambda row: (int(row["target_range"][0]), int(row["target_range"][1]), str(row["target_name"]))):
        row = dict(raw)
        start, end = int(row["target_range"][0]), int(row["target_range"][1])
        chosen = 0
        for track in range(TRACK_MIN, TRACK_MAX + 1):
            if all(not intervals_overlap(start, end, other_start, other_end) for other_start, other_end, _ in occupied[track]):
                chosen = track
                break
        if not chosen:
            raise ValueError(f"track_capacity:{row['target_name']}:{start}:{end}")
        row["target_track"] = chosen
        occupied[chosen].append((start, end, str(row["target_name"])))
        result.append(row)
    by_name = {str(row["target_name"]): row for row in result}
    return [by_name[str(raw["target_name"])] for raw in plans]


def filtered_stable_inventory(full: Any, rows: Sequence[Mapping[str, Any]], names: Iterable[str]) -> List[Tuple[Any, ...]]:
    blocked = set(str(value) for value in names)
    return full.stable_inventory([row for row in rows if str(row.get("name") or "") not in blocked])


def capture_static_style(base: Any, item: Any) -> Dict[str, Any]:
    comp = base.get_comp(item)
    tool = base.get_text_tool(comp)
    if comp is None or tool is None:
        raise RuntimeError("source_comp_or_text_tool")
    values: Dict[str, Any] = {}
    for name in STATIC_STYLE_INPUTS:
        if base.find_input(tool, name) is not None:
            values[name] = base.json_safe(base.read_input(tool, name, 0))
    return values


def capture_opacity_bases(base: Any, item: Any, duration: int) -> Dict[str, float]:
    comp = base.get_comp(item)
    tool = base.get_text_tool(comp)
    if comp is None or tool is None:
        raise RuntimeError("source_comp_or_text_tool")
    result: Dict[str, float] = {}
    frame_count = max(1, int(duration))
    for name in OPACITY_INPUTS:
        if base.find_input(tool, name) is None:
            continue
        values: List[float] = []
        for frame in range(frame_count):
            try:
                values.append(float(base.read_input(tool, name, frame)))
            except (TypeError, ValueError):
                pass
        if values:
            result[name] = max(values)
    if "Opacity1" not in result:
        raise RuntimeError("opacity1_missing")
    return result


def style_matches(base: Any, item: Any, expected: Mapping[str, Any]) -> bool:
    actual = capture_static_style(base, item)
    for key, value in expected.items():
        if key not in actual:
            return False
        if isinstance(value, (int, float)):
            try:
                if abs(float(actual[key]) - float(value)) > 1e-4:
                    return False
            except (TypeError, ValueError):
                return False
        elif str(actual[key] or "") != str(value or ""):
            return False
    return True


def apply_plan(base: Any, visual: Any, pilot: Any, item: Any, plan: Mapping[str, Any], opacity_bases: Mapping[str, float]) -> Dict[str, Any]:
    comp = base.get_comp(item)
    tool = base.get_text_tool(comp)
    if comp is None or tool is None:
        return {"ok": False, "error": "comp_or_text_tool"}
    duration = int(plan["target_range"][1]) - int(plan["target_range"][0])
    comp_range = visual.extend_comp_range(comp, tool, duration - 1)
    center = visual.apply_center_series(tool, plan["position_keys"])
    size_modifier = visual.ensure_modifier(tool, "Size", "BezierSpline")
    size = pilot.write_scalar_series(tool, "Size", plan["size_keys"], "value") if size_modifier.get("ok") else {"ok": False, "error": "size_modifier"}
    opacity_rows = []
    for input_name, base_value in sorted(opacity_bases.items()):
        modifier = visual.ensure_modifier(tool, input_name, "BezierSpline")
        keys = []
        if modifier.get("ok"):
            for key in plan["opacity_keys"]:
                expected = float(base_value) * float(key["factor"])
                write = visual.write_key(tool, input_name, int(key["local_frame"]), expected)
                keys.append({"local_frame": int(key["local_frame"]), "expected": expected, "write": write})
        opacity_rows.append({"input": input_name, "base_value": float(base_value), "modifier": modifier, "keys": keys, "ok": bool(modifier.get("ok") and len(keys) == len(plan["opacity_keys"]) and all(k["write"].get("ok") for k in keys))})
    opacity = {"rows": opacity_rows, "ok": bool(opacity_rows and all(row["ok"] for row in opacity_rows))}
    return {"comp_range": comp_range, "center": center, "size_modifier": size_modifier, "size": size, "opacity": opacity, "ok": bool(comp_range.get("ok") and center.get("ok") and size_modifier.get("ok") and size.get("ok") and opacity.get("ok"))}


def scalar_match(actual: Any, expected: float, tolerance: float = 1e-4) -> bool:
    try:
        return abs(float(actual) - float(expected)) <= tolerance
    except (TypeError, ValueError):
        return False


def read_plan(base: Any, item: Any, timeline: Any, plan: Mapping[str, Any], opacity_bases: Mapping[str, float], static_style: Mapping[str, Any]) -> Dict[str, Any]:
    comp = base.get_comp(item)
    tool = base.get_text_tool(comp)
    track = int(base.item_track_index(timeline, item) or 0)
    summary = base.item_summary(track, item)
    if comp is None or tool is None:
        return {"target_name": plan["target_name"], "ok": False, "error": "comp_or_text_tool"}
    pos = []
    size = []
    opacity = []
    for key in plan["position_keys"]:
        actual = base.read_input(tool, "Center", int(key["local_frame"]))
        pos.append(base.point_matches(actual, key["value"], 1e-4))
    for key in plan["size_keys"]:
        size.append(scalar_match(base.read_input(tool, "Size", int(key["local_frame"])), float(key["value"])))
    for input_name, base_value in sorted(opacity_bases.items()):
        input_matches = []
        for key in plan["opacity_keys"]:
            expected = float(base_value) * float(key["factor"])
            input_matches.append(scalar_match(base.read_input(tool, input_name, int(key["local_frame"])), expected))
        opacity.append({"input": input_name, "matched": all(input_matches), "count": len(input_matches)})
    expected_range = [int(v) for v in plan["target_range"]]
    checks = {
        "track": summary.get("track_index") == int(plan["target_track"]),
        "range": [summary.get("start"), summary.get("end")] == expected_range,
        "duration": summary.get("duration") == expected_range[1] - expected_range[0],
        "comp": int(base.as_int(base.safe_value(item, "GetFusionCompCount", default=0), 0)) == 1,
        "static_style_preserved": style_matches(base, item, static_style),
        "position": all(pos),
        "size": all(size),
        "opacity": bool(opacity and all(row["matched"] for row in opacity)),
    }
    return {"instance_id": plan["instance_id"], "target_name": plan["target_name"], "summary": summary, "opacity_inputs": opacity, "checks": checks, "ok": all(checks.values())}


def protected_expectations(persistent: Mapping[str, Any]) -> List[Dict[str, Any]]:
    if persistent.get("task_id") != "DZSQH7AUHJT_STEP_3E_FULL_BASELINE_VISUAL_POLISH_V1" or persistent.get("ok") is not True:
        raise ValueError("step3e3_persistent")
    rows = persistent.get("rows")
    if not isinstance(rows, list) or len(rows) != EXPECTED_PROTECTED:
        raise ValueError("protected_rows")
    result = []
    for row in rows:
        if not isinstance(row, Mapping) or row.get("ok") is not True:
            raise ValueError("protected_row")
        result.append(dict(row))
    return result


def verify_protected(base: Any, timeline: Any, expected_rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    wanted = {str(row.get("target_name") or ""): row for row in expected_rows}
    found: Dict[str, Tuple[int, Any]] = {}
    for track, item in base.all_video_items(timeline):
        name = base.item_name(item)
        if name in wanted:
            if name in found:
                raise RuntimeError(f"protected_duplicate:{name}")
            found[name] = (int(track), item)
    results = []
    for name, expected in wanted.items():
        pair = found.get(name)
        if pair is None:
            results.append({"target_name": name, "ok": False, "error": "missing"})
            continue
        track, item = pair
        comp = base.get_comp(item)
        tool = base.get_text_tool(comp)
        summary = base.item_summary(track, item)
        exp_summary = expected.get("summary") if isinstance(expected.get("summary"), Mapping) else {}
        checks = {
            "track": summary.get("track_index") == exp_summary.get("track_index"),
            "range": [summary.get("start"), summary.get("end")] == [exp_summary.get("start"), exp_summary.get("end")],
            "duration": summary.get("duration") == exp_summary.get("duration"),
            "comp": base.as_int(base.safe_value(item, "GetFusionCompCount", default=0), 0) == 1,
            "text": tool is not None and str(base.text_readback(tool)) == str(expected.get("text") or ""),
            "font": tool is not None and str(base.read_input(tool, "Font", 0) or "") == str(expected.get("font") or ""),
            "style": tool is not None and str(base.read_input(tool, "Style", 0) or "") == str(expected.get("style") or ""),
        }
        position_ok = True
        size_ok = True
        opacity_ok = True
        if tool is not None:
            for row in expected.get("position_keys") or []:
                key = row.get("key") or {}
                position_ok = position_ok and base.point_matches(base.read_input(tool, "Center", int(key["local_frame"])), key["value"], 1e-4)
            for row in expected.get("size_keys") or []:
                key = row.get("key") or {}
                size_ok = size_ok and scalar_match(base.read_input(tool, "Size", int(key["local_frame"])), float(key["value"]))
            for row in expected.get("opacity_keys") or []:
                key = row.get("key") or {}
                opacity_ok = opacity_ok and scalar_match(base.read_input(tool, "Opacity1", int(key["local_frame"])), float(key["factor"]))
        else:
            position_ok = size_ok = opacity_ok = False
        checks.update({"position": position_ok, "size": size_ok, "opacity": opacity_ok})
        results.append({"target_name": name, "checks": checks, "ok": all(checks.values())})
    return results


def cleanup_failure(resolve: Any, base: Any, project_manager: Any, project: Any, media_pool: Any, original_timeline: Any, original_page: str, accepted_path: Path, accepted_hash: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {"errors": [], "save_call_count": 0}
    try:
        target = base.find_timeline(project, TARGET_TIMELINE_NAME) if project is not None else None
        if original_timeline is not None and project is not None:
            value, _ = base.direct_call(project, "SetCurrentTimeline", original_timeline)
            if not value: result["errors"].append("restore_timeline")
        if target is not None and media_pool is not None:
            value, _ = base.direct_call(media_pool, "DeleteTimelines", [target])
            if not value: result["errors"].append("delete_target")
        if original_page:
            value, _ = base.direct_call(resolve, "OpenPage", original_page)
            if not value: result["errors"].append("restore_page")
        if project_manager is not None:
            save = base.save_project(project_manager)
            result["save"] = save
            result["save_call_count"] = 1
            if not save.get("success"): result["errors"].append("save_cleanup")
    except BaseException as exc:
        result["errors"].append(base.compact_exception(exc))
        result["traceback"] = traceback.format_exc()
    try:
        result["target_deleted"] = project is not None and base.find_timeline(project, TARGET_TIMELINE_NAME) is None
    except BaseException:
        result["target_deleted"] = False
    result["accepted_state_unchanged"] = accepted_path.is_file() and base.raw_sha256(accepted_path) == accepted_hash
    result["ok"] = bool(not result["errors"] and result["target_deleted"] and result["accepted_state_unchanged"])
    return result


def run(resolve: Any, context: Dict[str, Any]) -> Dict[str, Any]:
    full, pilot, v6, base, media, visual = load_runtime()
    root = base.repository_root()
    command = context.get("command") if isinstance(context, dict) else None
    if not isinstance(command, dict): raise ValueError("command")
    run_id = str(context.get("run_id") or command.get("run_id") or "")
    if not run_id: raise ValueError("run_id")
    if command.get("task_id") != TASK_ID or command.get("mode") != MODE: raise ValueError("command_identity")
    report_dir = base.relative_path(root, command.get("artifacts_dir")); report_dir.mkdir(parents=True, exist_ok=True)
    accepted_path = root / ACCEPTED_STATE_RELATIVE_PATH
    accepted_hash = str(command.get("accepted_state_sha256") or "")
    report: Dict[str, Any] = {
        "schema_version": 1, "task_id": TASK_ID, "run_id": run_id, "mode": MODE, "ok": False,
        "started_at": base.utc_now(), "source_timeline_name": SOURCE_TIMELINE_NAME, "target_timeline_name": TARGET_TIMELINE_NAME,
        "remaining_instance_count": 0, "protected_v4_count": 0, "explicit_frame_row_count": 0,
        "final_textplus_count": 0, "save_call_count": 0, "source_timeline_unchanged": False,
        "accepted_state_unchanged": False, "target_timeline_kept": False,
        "remaining_caption_rollout_completed": False, "visual_approval_required": True,
        "fade_polish_deferred": True, "further_rollout_authorized": False, "failures": [],
    }
    project_manager = project = media_pool = None
    original_timeline = None
    original_page = str(base.safe_value(resolve, "GetCurrentPage", default="") or "")
    source_before: List[Dict[str, Any]] = []
    source_unique_id = ""
    target_created = False
    try:
        source_contract = base.verify_source_contract(root, command)
        base.write_json(report_dir / "source_contract_verification.json", source_contract)
        if not accepted_path.is_file() or base.raw_sha256(accepted_path) != accepted_hash: raise RuntimeError("accepted_state")
        authority = load_json(root / AUTHORITY_RELATIVE_PATH)
        authority_validation = load_json(root / AUTHORITY_VALIDATION_RELATIVE_PATH)
        step3e3_persistent = load_json(root / STEP3E3_PERSISTENT_RELATIVE_PATH)
        if authority_validation.get("ok") is not True: raise RuntimeError("authority_validation")
        unassigned = build_unassigned_plans(authority)
        protected_expected = protected_expectations(step3e3_persistent)
        remaining_names = [row["target_name"] for row in unassigned]
        protected_names = [str(row["target_name"]) for row in protected_expected]
        if set(remaining_names) & set(protected_names): raise RuntimeError("scope_overlap")
        project_manager, project, media_pool, resolve_calls = base.get_project(resolve)
        original_timeline = base.safe_value(project, "GetCurrentTimeline", default=None)
        source = base.find_timeline(project, SOURCE_TIMELINE_NAME)
        if source is None: raise RuntimeError("source_timeline")
        if base.find_timeline(project, TARGET_TIMELINE_NAME) is not None: raise RuntimeError("target_timeline_exists")
        source_unique_id = base.timeline_unique_id(source)
        source_before = full.timeline_inventory(source)
        if len(full.source_textplus_names(source)) != EXPECTED_REMAINING: raise RuntimeError("source_remaining_count")
        if sorted(full.source_textplus_names(source)) != sorted(remaining_names): raise RuntimeError("source_remaining_names")
        if len(full.visual_first_names(source)) != EXPECTED_PROTECTED or sorted(full.visual_first_names(source)) != sorted(protected_names): raise RuntimeError("source_protected_names")
        if len(full.source_textplus_names(source)) + len(full.visual_first_names(source)) != EXPECTED_TOTAL: raise RuntimeError("source_total")
        if full.track_two_item_names(source): raise RuntimeError("source_v2_not_empty")
        protected_source_rows = verify_protected(base, source, protected_expected)
        if len(protected_source_rows) != EXPECTED_PROTECTED or not all(row.get("ok") for row in protected_source_rows): raise RuntimeError("protected_source_state")
        occupied_rows = [row for row in source_before if str(row.get("name") or "") not in set(remaining_names)]
        plans = assign_tracks(unassigned, occupied_rows)
        explicit_rows = sum(len(row["position_keys"]) for row in plans)
        max_duration = max(int(row["target_range"][1]) - int(row["target_range"][0]) for row in plans)
        carrier_source = base.choose_carrier_source(source, max_duration + 1)
        if not carrier_source.get("ok"): raise RuntimeError("carrier_source")
        export_dir = report_dir / "source_comp_exports"; export_dir.mkdir(parents=True, exist_ok=True)
        export_rows = []; source_meta: Dict[str, Dict[str, Any]] = {}
        source_inventory_by_name = {str(row.get("name") or ""): row for row in source_before}
        for plan in plans:
            name = str(plan["target_name"])
            track, source_item = base.find_named_item(source, name)
            if source_item is None: raise RuntimeError(f"source_item:{name}")
            comp_path = export_dir / f"{plan['instance_id']}.comp"
            value, call = base.direct_call(source_item, "ExportFusionComp", str(comp_path), 1)
            file_ok = bool(value and comp_path.is_file() and comp_path.stat().st_size > 0)
            inventory_row = source_inventory_by_name.get(name) or {}
            source_meta[name] = {
                "comp_path": comp_path,
                "static_style": capture_static_style(base, source_item),
                "opacity_bases": capture_opacity_bases(base, source_item, int(inventory_row.get("duration") or 1)),
            }
            export_rows.append({"instance_id": plan["instance_id"], "target_name": name, "track": track, "path": str(comp_path), "size": comp_path.stat().st_size if comp_path.is_file() else 0, "sha256": base.raw_sha256(comp_path) if file_ok else None, "call": call, "ok": file_ok})
            if not file_ok: raise RuntimeError(f"source_comp_export:{name}")
        base.write_json(report_dir / "source_comp_exports.json", {"rows": export_rows, "exported_count": len(export_rows), "ok": len(export_rows) == EXPECTED_REMAINING and all(row["ok"] for row in export_rows)})
        plan_document = {"schema_version": 1, "task_id": TASK_ID, "run_id": run_id, "authority_semantic_sha256": authority.get("semantic_sha256"), "source_timeline_name": SOURCE_TIMELINE_NAME, "target_timeline_name": TARGET_TIMELINE_NAME, "remaining_instance_count": len(plans), "protected_v4_count": len(protected_expected), "explicit_frame_row_count": explicit_rows, "track_range": [TRACK_MIN, TRACK_MAX], "transcript_timing_authority": False, "static_style_policy": "export_import_current_source_comp", "fade_polish_deferred": True, "plans": plans, "ok": len(plans) == EXPECTED_REMAINING and explicit_rows == EXPECTED_FRAME_ROWS}
        base.write_json(report_dir / "rollout_plan.json", plan_document)
        if not plan_document["ok"]: raise RuntimeError("rollout_plan")
        base.write_json(report_dir / "rollout_preflight.json", {"schema_version": 1, "task_id": TASK_ID, "run_id": run_id, "resolve_calls": resolve_calls, "source_unique_id": source_unique_id, "source_inventory": source_before, "source_remaining_count": len(full.source_textplus_names(source)), "source_protected_count": len(full.visual_first_names(source)), "source_total_textplus_count": EXPECTED_TOTAL, "source_v2_item_count": len(full.track_two_item_names(source)), "protected_source_rows": protected_source_rows, "carrier_source": {k: base.json_safe(v) for k,v in carrier_source.items() if k not in {"item","media_pool_item"}}, "ok": True})
        duplicate_value, duplicate_call = base.direct_call(source, "DuplicateTimeline", TARGET_TIMELINE_NAME)
        target = duplicate_value if duplicate_value is not None else base.find_timeline(project, TARGET_TIMELINE_NAME)
        if target is None: raise RuntimeError("duplicate_timeline")
        target_created = True
        selected, select_call = base.direct_call(project, "SetCurrentTimeline", target)
        if not selected: raise RuntimeError("select_target")
        deletion = full.delete_named_textplus(target, remaining_names)
        time.sleep(0.20)
        if not deletion.get("ok") or deletion.get("deleted") != EXPECTED_REMAINING: raise RuntimeError("delete_remaining100")
        track_setup = base.ensure_video_tracks(target, TRACK_MAX)
        if not track_setup.get("ok"): raise RuntimeError("track_setup")
        after_delete_inventory = full.timeline_inventory(target)
        if filtered_stable_inventory(full, after_delete_inventory, remaining_names) != filtered_stable_inventory(full, source_before, remaining_names): raise RuntimeError("protected_inventory_after_delete")
        protected_after_delete = verify_protected(base, target, protected_expected)
        if not all(row.get("ok") for row in protected_after_delete): raise RuntimeError("protected_after_delete")
        base.write_json(report_dir / "rollout_timeline_setup.json", {"schema_version": 1, "task_id": TASK_ID, "run_id": run_id, "duplicate_call": duplicate_call, "select_call": select_call, "delete": deletion, "track_setup": track_setup, "remaining_after_delete": len(full.source_textplus_names(target)), "protected_after_delete": protected_after_delete, "ok": len(full.source_textplus_names(target)) == 0 and len(full.visual_first_names(target)) == EXPECTED_PROTECTED})
        specs = [{"cue_id": row["instance_id"], "name": row["target_name"], "text": row["display_text"], "target_range": row["target_range"], "target_track": row["target_track"]} for row in plans]
        assigned: Dict[str, Any] = {}; append_rows = []
        for batch_index, batch in enumerate(pilot.chunked(specs, APPEND_BATCH_SIZE)):
            result = v6.append_batch_by_placement(media_pool, target, carrier_source, batch)
            ok = result.get("ok") is True and len(result.get("assigned") or []) == len(batch)
            append_rows.append({"batch_index": batch_index, "requested_count": len(batch), "assigned_count": len(result.get("assigned") or []), "result": base.json_safe({k:v for k,v in result.items() if k != "assigned"}), "ok": ok})
            if not ok: raise RuntimeError(f"append_batch:{batch_index}")
            for spec, item in result["assigned"]:
                cue_id = str(spec["cue_id"])
                if cue_id in assigned: raise RuntimeError(f"duplicate_assignment:{cue_id}")
                assigned[cue_id] = item
        base.write_json(report_dir / "rollout_carrier_append.json", {"schema_version": 1, "task_id": TASK_ID, "run_id": run_id, "batch_count": len(append_rows), "requested_count": len(specs), "assigned_count": len(assigned), "batches": append_rows, "ok": len(assigned) == EXPECTED_REMAINING and all(row["ok"] for row in append_rows)})
        application_rows = []
        for plan in plans:
            item = assigned.get(str(plan["instance_id"])); meta = source_meta[str(plan["target_name"])]
            if item is None: raise RuntimeError(f"assigned_item:{plan['instance_id']}")
            imported, import_call = base.direct_call(item, "ImportFusionComp", str(meta["comp_path"]))
            clone = {"returned": base.json_safe(imported), "call": import_call, "ok": bool(imported and base.as_int(base.safe_value(item, "GetFusionCompCount", default=0), 0) == 1)}
            application = apply_plan(base, visual, pilot, item, plan, meta["opacity_bases"]) if clone["ok"] else {"ok": False, "error": "clone"}
            style_ok = style_matches(base, item, meta["static_style"]) if application.get("ok") else False
            row = {"instance_id": plan["instance_id"], "target_name": plan["target_name"], "explicit_frame_rows": len(plan["position_keys"]), "clone": clone, "application": application, "static_style_preserved": style_ok, "ok": bool(clone["ok"] and application.get("ok") and style_ok)}
            application_rows.append(row)
            base.write_json(report_dir / "rollout_application.json", {"schema_version": 1, "task_id": TASK_ID, "run_id": run_id, "expected_instance_count": EXPECTED_REMAINING, "instance_count": len(application_rows), "complete": False, "rows": application_rows, "ok": False})
            if not row["ok"]: raise RuntimeError(f"apply:{plan['instance_id']}")
        base.write_json(report_dir / "rollout_application.json", {"schema_version": 1, "task_id": TASK_ID, "run_id": run_id, "expected_instance_count": EXPECTED_REMAINING, "instance_count": len(application_rows), "explicit_frame_row_count": explicit_rows, "complete": True, "rows": application_rows, "ok": len(application_rows) == EXPECTED_REMAINING and all(row["ok"] for row in application_rows)})
        found = pilot.target_items(target, plans)
        readback_rows = []
        for plan in plans:
            item = found.get(str(plan["target_name"]), (0, None))[1]; meta = source_meta[str(plan["target_name"])]
            readback_rows.append(read_plan(base, item, target, plan, meta["opacity_bases"], meta["static_style"]) if item is not None else {"target_name": plan["target_name"], "ok": False, "error": "missing"})
        protected_before_save = verify_protected(base, target, protected_expected)
        target_inventory = full.timeline_inventory(target)
        pre_checks = {
            "remaining_exact": len(readback_rows) == EXPECTED_REMAINING and all(row.get("ok") for row in readback_rows),
            "protected_v4_exact": len(protected_before_save) == EXPECTED_PROTECTED and all(row.get("ok") for row in protected_before_save),
            "remaining_names_exact": sorted(full.source_textplus_names(target)) == sorted(remaining_names),
            "protected_names_exact": sorted(full.visual_first_names(target)) == sorted(protected_names),
            "final_textplus_count": len(full.source_textplus_names(target)) + len(full.visual_first_names(target)) == EXPECTED_TOTAL,
            "v2_empty": not full.track_two_item_names(target),
            "non_scope_inventory_preserved": filtered_stable_inventory(full, target_inventory, remaining_names) == filtered_stable_inventory(full, source_before, remaining_names),
        }
        base.write_json(report_dir / "rollout_readback_before_save.json", {"schema_version": 1, "task_id": TASK_ID, "run_id": run_id, "rows": readback_rows, "protected_v4_rows": protected_before_save, "explicit_frame_row_count": explicit_rows, "checks": pre_checks, "ok": all(pre_checks.values())})
        if not all(pre_checks.values()): raise RuntimeError("readback_before_save")
        base.direct_call(project, "SetCurrentTimeline", target); base.direct_call(resolve, "OpenPage", "edit")
        save = base.save_project(project_manager); report["save_call_count"] = 1 if save.get("success") else 0
        if not save.get("success"): raise RuntimeError("save")
        project_manager, project, media_pool, reacquire_calls = base.get_project(resolve)
        source_after = base.find_timeline(project, SOURCE_TIMELINE_NAME); target_after = base.find_timeline(project, TARGET_TIMELINE_NAME)
        if source_after is None or target_after is None: raise RuntimeError("reacquire_timeline")
        source_after_inventory = full.timeline_inventory(source_after); target_after_inventory = full.timeline_inventory(target_after)
        found_after = pilot.target_items(target_after, plans); persistent_rows = []
        for plan in plans:
            item = found_after.get(str(plan["target_name"]), (0, None))[1]; meta = source_meta[str(plan["target_name"])]
            persistent_rows.append(read_plan(base, item, target_after, plan, meta["opacity_bases"], meta["static_style"]) if item is not None else {"target_name": plan["target_name"], "ok": False, "error": "missing"})
        protected_after = verify_protected(base, target_after, protected_expected)
        persistent_checks = {
            "source_timeline_unchanged": base.timeline_unique_id(source_after) == source_unique_id and full.stable_inventory(source_after_inventory) == full.stable_inventory(source_before),
            "accepted_state_unchanged": accepted_path.is_file() and base.raw_sha256(accepted_path) == accepted_hash,
            "target_retained": base.timeline_name(target_after) == TARGET_TIMELINE_NAME,
            "remaining_exact": len(persistent_rows) == EXPECTED_REMAINING and all(row.get("ok") for row in persistent_rows),
            "protected_v4_exact": len(protected_after) == EXPECTED_PROTECTED and all(row.get("ok") for row in protected_after),
            "remaining_names_exact": sorted(full.source_textplus_names(target_after)) == sorted(remaining_names),
            "protected_names_exact": sorted(full.visual_first_names(target_after)) == sorted(protected_names),
            "final_textplus_count": len(full.source_textplus_names(target_after)) + len(full.visual_first_names(target_after)) == EXPECTED_TOTAL,
            "v2_empty": not full.track_two_item_names(target_after),
            "non_scope_inventory_preserved": filtered_stable_inventory(full, target_after_inventory, remaining_names) == filtered_stable_inventory(full, source_before, remaining_names),
        }
        persistent = {"schema_version": 1, "task_id": TASK_ID, "run_id": run_id, "reacquire_calls": reacquire_calls, "rows": persistent_rows, "protected_v4_rows": protected_after, "explicit_frame_row_count": explicit_rows, "checks": persistent_checks, "save": save, "remaining_caption_rollout_completed": True, "visual_approval_required": True, "fade_polish_deferred": True, "further_rollout_authorized": False, "ok": all(persistent_checks.values())}
        base.write_json(report_dir / "persistent_readback.json", persistent)
        if not persistent["ok"]: raise RuntimeError("persistent_readback")
        report.update({"ok": True, "finished_at": base.utc_now(), "remaining_instance_count": EXPECTED_REMAINING, "protected_v4_count": EXPECTED_PROTECTED, "explicit_frame_row_count": explicit_rows, "final_textplus_count": EXPECTED_TOTAL, "source_timeline_unchanged": persistent_checks["source_timeline_unchanged"], "accepted_state_unchanged": persistent_checks["accepted_state_unchanged"], "target_timeline_kept": True, "remaining_caption_rollout_completed": True})
        return report
    except BaseException as exc:
        report["failures"].append(base.compact_exception(exc)); report["traceback"] = traceback.format_exc()
        if target_created and project_manager is not None and project is not None and media_pool is not None:
            cleanup = cleanup_failure(resolve, base, project_manager, project, media_pool, original_timeline, original_page, accepted_path, accepted_hash)
            base.write_json(report_dir / "failure_cleanup.json", cleanup); report["failure_cleanup_ok"] = cleanup.get("ok") is True; report["save_call_count"] = int(cleanup.get("save_call_count") or 0)
        report["finished_at"] = base.utc_now(); return report
