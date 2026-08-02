import argparse
import json
import os
from statistics import median

import numpy as np
import librosa


ANALYSIS_VERSION = "rhythm_beats_v2_next_layer_ready"


def round_float(value, digits=3):
    try:
        return round(float(value), digits)
    except Exception:
        return None


def safe_float(value, fallback=None):
    try:
        arr = np.asarray(value).flatten()
        if arr.size > 0:
            return float(arr[0])
        return float(value)
    except Exception:
        return fallback


def limit_list(items, max_items):
    if max_items is None or max_items <= 0:
        return items
    return items[:max_items]


def top_by_strength_then_time(items, max_items):
    """
    Picks the strongest markers across the whole clip, then returns them sorted by time.
    This fixes the bad behavior where early markers dominate only because they appear first.
    """

    if not items:
        return []

    ranked = sorted(
        items,
        key=lambda x: float(x.get("strength", 0.0) or 0.0),
        reverse=True
    )

    selected = limit_list(ranked, max_items)

    return sorted(
        selected,
        key=lambda x: float(x.get("time", 0.0) or 0.0)
    )


def estimate_tempo_from_beats(beat_times):
    if not beat_times or len(beat_times) < 2:
        return None

    intervals = []

    for i in range(1, len(beat_times)):
        diff = beat_times[i] - beat_times[i - 1]
        if 0.15 <= diff <= 2.0:
            intervals.append(diff)

    if not intervals:
        return None

    avg_interval = median(intervals)

    if avg_interval <= 0:
        return None

    return round_float(60.0 / avg_interval, 3)


def normalize_times(times, digits=3):
    clean = []

    for t in times:
        try:
            value = round(float(t), digits)
            if value >= 0:
                clean.append(value)
        except Exception:
            continue

    return clean


def normalize_onset_env(onset_env):
    onset_env = np.asarray(onset_env, dtype=float)

    if onset_env.size == 0:
        return onset_env

    max_value = np.max(onset_env)

    if max_value > 0:
        return onset_env / max_value

    return onset_env


def build_onset_markers_from_frames(frames, onset_env, sr, hop_length):
    """
    Converts librosa onset frames into markers with normalized strength.
    """

    if frames is None:
        return []

    normalized_env = normalize_onset_env(onset_env)

    markers = []

    for i, frame_idx in enumerate(frames):
        try:
            frame_idx = int(frame_idx)
            t = librosa.frames_to_time(frame_idx, sr=sr, hop_length=hop_length)

            strength = 0.0

            if 0 <= frame_idx < len(normalized_env):
                strength = float(normalized_env[frame_idx])

            markers.append({
                "index": i,
                "time": round_float(t),
                "strength": round_float(strength, 4)
            })

        except Exception:
            continue

    return markers


def extract_onset_strength_peaks(
    onset_env,
    sr,
    hop_length,
    max_peaks=80,
    min_strength=0.25
):
    """
    Extracts strong energy/onset peaks.

    Important:
    We first find all valid peaks, then select the strongest ones across the full clip,
    then sort the selected markers by time. This makes the output useful for edit planning.
    """

    if onset_env is None or len(onset_env) == 0:
        return [], 0

    normalized = normalize_onset_env(onset_env)

    all_peaks = []

    try:
        from scipy.signal import find_peaks

        # Distance controls how close peaks can be.
        # 0.18s avoids excessive micro-peaks in speech-heavy reels.
        min_distance_frames = max(1, int(0.18 * sr / hop_length))

        peak_indices, _ = find_peaks(
            normalized,
            height=min_strength,
            distance=min_distance_frames
        )

        for idx in peak_indices:
            t = librosa.frames_to_time(idx, sr=sr, hop_length=hop_length)
            strength = float(normalized[idx])

            all_peaks.append({
                "time": round_float(t),
                "strength": round_float(strength, 4)
            })

    except Exception:
        # Fallback: treat strongest envelope frames as peaks.
        sorted_indices = np.argsort(normalized)[::-1]

        for idx in sorted_indices:
            strength = float(normalized[idx])

            if strength < min_strength:
                continue

            t = librosa.frames_to_time(idx, sr=sr, hop_length=hop_length)

            all_peaks.append({
                "time": round_float(t),
                "strength": round_float(strength, 4)
            })

    all_peaks = sorted(all_peaks, key=lambda x: x["time"])
    major_peaks = top_by_strength_then_time(all_peaks, max_peaks)

    return major_peaks, len(all_peaks)


def analyze_with_librosa(
    audio_path,
    max_markers=500,
    max_strong_onsets=50,
    max_energy_peaks=50,
    energy_min_strength=0.25
):
    """
    Librosa is the stable base layer:
    - duration
    - BPM
    - beats
    - onsets
    - strong onsets
    - major energy peaks
    """

    y, sr = librosa.load(audio_path, sr=None, mono=True)

    duration = librosa.get_duration(y=y, sr=sr)

    hop_length = 512

    onset_env = librosa.onset.onset_strength(
        y=y,
        sr=sr,
        hop_length=hop_length
    )

    tempo, beat_frames = librosa.beat.beat_track(
        y=y,
        sr=sr,
        onset_envelope=onset_env,
        hop_length=hop_length
    )

    bpm_librosa = safe_float(tempo)

    beat_times = librosa.frames_to_time(
        beat_frames,
        sr=sr,
        hop_length=hop_length
    )

    onset_frames = librosa.onset.onset_detect(
        y=y,
        sr=sr,
        onset_envelope=onset_env,
        hop_length=hop_length,
        units="frames",
        backtrack=False
    )

    all_onset_markers = build_onset_markers_from_frames(
        frames=onset_frames,
        onset_env=onset_env,
        sr=sr,
        hop_length=hop_length
    )

    strong_onsets = top_by_strength_then_time(
        all_onset_markers,
        max_strong_onsets
    )

    major_energy_peaks, all_energy_peaks_count = extract_onset_strength_peaks(
        onset_env=onset_env,
        sr=sr,
        hop_length=hop_length,
        max_peaks=max_energy_peaks,
        min_strength=energy_min_strength
    )

    beats = normalize_times(beat_times)

    return {
        "sample_rate": int(sr),
        "duration": round_float(duration),
        "bpm_librosa": round_float(bpm_librosa),
        "beats_librosa": limit_list(beats, max_markers),
        "all_onsets": limit_list(all_onset_markers, max_markers),
        "strong_onsets": strong_onsets,
        "major_energy_peaks": major_energy_peaks,
        "librosa_counts": {
            "beats": len(beats),
            "all_onsets": len(all_onset_markers),
            "strong_onsets": len(strong_onsets),
            "all_energy_peaks": all_energy_peaks_count,
            "major_energy_peaks": len(major_energy_peaks)
        }
    }


def analyze_with_madmom(audio_path, max_markers=500):
    """
    Madmom is optional enhancement:
    - stronger beat tracking
    - actual bar-position/downbeat estimation

    Important:
    madmom's downbeat processor returns bar positions:
    [time, beat_number]

    beat_number == 1 is the true downbeat.
    Other beat numbers are useful bar positions, but they are not downbeats.
    """

    result = {
        "available": False,
        "beats_madmom": [],
        "bar_positions_madmom": [],
        "true_downbeats_madmom": [],
        "errors": {}
    }

    try:
        from madmom.features.beats import RNNBeatProcessor, DBNBeatTrackingProcessor

        beat_activations = RNNBeatProcessor()(audio_path)

        beat_tracker = DBNBeatTrackingProcessor(
            fps=100
        )

        beat_times = beat_tracker(beat_activations)

        result["beats_madmom"] = limit_list(
            normalize_times(beat_times),
            max_markers
        )

        result["available"] = True

    except Exception as e:
        result["errors"]["madmom_beats_error"] = str(e)

    try:
        from madmom.features.downbeats import RNNDownBeatProcessor, DBNDownBeatTrackingProcessor

        downbeat_activations = RNNDownBeatProcessor()(audio_path)

        downbeat_tracker = DBNDownBeatTrackingProcessor(
            beats_per_bar=[3, 4],
            fps=100
        )

        downbeat_result = downbeat_tracker(downbeat_activations)

        bar_positions = []

        for i, row in enumerate(downbeat_result):
            try:
                time_value = round_float(row[0])
                beat_number = int(row[1])

                bar_positions.append({
                    "index": i,
                    "time": time_value,
                    "beat_number": beat_number,
                    "is_downbeat": beat_number == 1,
                    "source": "madmom"
                })

            except Exception:
                continue

        result["bar_positions_madmom"] = limit_list(bar_positions, max_markers)
        result["true_downbeats_madmom"] = [
            {
                "index": i,
                "time": item["time"],
                "source": "madmom"
            }
            for i, item in enumerate(result["bar_positions_madmom"])
            if item.get("is_downbeat") is True
        ]

        result["available"] = True

    except Exception as e:
        result["errors"]["madmom_downbeats_error"] = str(e)

    result["bpm_madmom_estimate"] = estimate_tempo_from_beats(
        result["beats_madmom"]
    )

    return result


def approximate_bar_positions_from_beats(beat_times, beats_per_bar=4):
    """
    Fallback when madmom downbeats fail.
    This is not true musical downbeat detection.
    It simply marks every Nth beat.
    """

    if not beat_times:
        return []

    bar_positions = []

    for i, t in enumerate(beat_times):
        beat_number = (i % beats_per_bar) + 1

        bar_positions.append({
            "index": i,
            "time": round_float(t),
            "beat_number": beat_number,
            "is_downbeat": beat_number == 1,
            "source": "approx_every_4th_beat"
        })

    return bar_positions


def true_downbeats_from_bar_positions(bar_positions, source):
    downbeats = []

    for item in bar_positions:
        if item.get("is_downbeat") is True:
            downbeats.append({
                "index": len(downbeats),
                "time": item.get("time"),
                "source": source
            })

    return downbeats


def build_beat_markers(beat_times, source):
    markers = []

    for i, t in enumerate(beat_times):
        markers.append({
            "index": i,
            "time": round_float(t),
            "source": source
        })

    return markers


def estimate_rhythm_confidence(
    selected_beats,
    downbeats,
    strong_onsets,
    duration,
    madmom_errors
):
    if not duration or duration <= 0:
        return "low"

    beat_density = len(selected_beats) / max(duration, 1)
    has_enough_beats = len(selected_beats) >= 8
    has_downbeats = len(downbeats) >= 2
    has_strong_onsets = len(strong_onsets) >= 8
    madmom_ok = len(madmom_errors) == 0

    if has_enough_beats and has_downbeats and has_strong_onsets and madmom_ok:
        return "high"

    if has_enough_beats and has_strong_onsets and 0.5 <= beat_density <= 4.0:
        return "medium"

    return "low"


def pick_best_beats(librosa_data, madmom_data):
    madmom_beats = madmom_data.get("beats_madmom", [])
    librosa_beats = librosa_data.get("beats_librosa", [])

    if len(madmom_beats) >= 8:
        return madmom_beats, "madmom"

    return librosa_beats, "librosa"


def pick_bpm(librosa_data, madmom_data, selected_source):
    bpm_librosa = librosa_data.get("bpm_librosa")
    bpm_madmom = madmom_data.get("bpm_madmom_estimate")

    if selected_source == "madmom" and bpm_madmom:
        return bpm_madmom

    return bpm_librosa


def build_rhythm_summary(output):
    return {
        "duration": output["duration"],
        "bpm": output["bpm"],
        "beat_source": output["beat_source"],
        "bar_position_source": output["bar_position_source"],
        "rhythm_confidence": output["rhythm_confidence"],
        "beats_count": len(output["beats"]),
        "downbeats_count": len(output["downbeats"]),
        "bar_positions_count": len(output["bar_positions"]),
        "strong_onsets_count": len(output["strong_onsets"]),
        "major_energy_peaks_count": len(output["major_energy_peaks"])
    }


def compact_output(output):
    """
    This is what the next unified analysis layer should consume.
    It intentionally avoids dumping hundreds of micro-onsets.
    """

    return {
        "success": output["success"],
        "analysis_version": output["analysis_version"],
        "audio_path": output["audio_path"],
        "duration": output["duration"],
        "bpm": output["bpm"],
        "rhythm_confidence": output["rhythm_confidence"],
        "beat_source": output["beat_source"],
        "bar_position_source": output["bar_position_source"],
        "rhythm_summary": output["rhythm_summary"],
        "summary": output["rhythm_summary"],
        "beats": output["beats"],
        "downbeats": output["downbeats"],
        "bar_positions": output["bar_positions"],
        "strong_onsets": output["strong_onsets"],
        "major_energy_peaks": output["major_energy_peaks"],
        "debug": output["debug"],
        "errors": output["errors"]
    }


def run(
    audio_path,
    output_json,
    output_mode,
    max_markers,
    max_strong_onsets,
    max_energy_peaks,
    energy_min_strength,
    approximate_downbeats
):
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    output_dir = os.path.dirname(output_json)

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    librosa_data = analyze_with_librosa(
        audio_path=audio_path,
        max_markers=max_markers,
        max_strong_onsets=max_strong_onsets,
        max_energy_peaks=max_energy_peaks,
        energy_min_strength=energy_min_strength
    )

    madmom_data = analyze_with_madmom(
        audio_path=audio_path,
        max_markers=max_markers
    )

    selected_beats, beat_source = pick_best_beats(librosa_data, madmom_data)

    bpm = pick_bpm(librosa_data, madmom_data, beat_source)

    madmom_bar_positions = madmom_data.get("bar_positions_madmom", [])
    madmom_true_downbeats = madmom_data.get("true_downbeats_madmom", [])

    if madmom_bar_positions:
        bar_positions = madmom_bar_positions
        downbeats = madmom_true_downbeats
        bar_position_source = "madmom"
    elif approximate_downbeats:
        bar_positions = approximate_bar_positions_from_beats(selected_beats)
        downbeats = true_downbeats_from_bar_positions(
            bar_positions,
            source="approximation"
        )
        bar_position_source = "approximation"
    else:
        bar_positions = []
        downbeats = []
        bar_position_source = "none"

    strong_onsets = librosa_data.get("strong_onsets", [])
    major_energy_peaks = librosa_data.get("major_energy_peaks", [])

    rhythm_confidence = estimate_rhythm_confidence(
        selected_beats=selected_beats,
        downbeats=downbeats,
        strong_onsets=strong_onsets,
        duration=librosa_data.get("duration"),
        madmom_errors=madmom_data.get("errors", {})
    )

    output = {
        "success": True,
        "analysis_version": ANALYSIS_VERSION,
        "audio_path": audio_path,
        "duration": librosa_data.get("duration"),
        "sample_rate": librosa_data.get("sample_rate"),
        "bpm": bpm,
        "bpm_librosa": librosa_data.get("bpm_librosa"),
        "bpm_madmom_estimate": madmom_data.get("bpm_madmom_estimate"),
        "beat_source": beat_source,
        "bar_position_source": bar_position_source,
        "rhythm_confidence": rhythm_confidence,
        "beats": build_beat_markers(selected_beats, beat_source),
        "downbeats": downbeats,
        "bar_positions": bar_positions,
        "strong_onsets": strong_onsets,
        "major_energy_peaks": major_energy_peaks,
        "beats_librosa": build_beat_markers(
            librosa_data.get("beats_librosa", []),
            "librosa"
        ),
        "beats_madmom": build_beat_markers(
            madmom_data.get("beats_madmom", []),
            "madmom"
        ),
        "all_onsets": librosa_data.get("all_onsets", []),
        "debug": {
            "output_mode": output_mode,
            "max_markers": max_markers,
            "max_strong_onsets": max_strong_onsets,
            "max_energy_peaks": max_energy_peaks,
            "energy_min_strength": energy_min_strength,
            "madmom_available": madmom_data.get("available", False),
            "librosa_counts": librosa_data.get("librosa_counts", {}),
            "madmom_errors_count": len(madmom_data.get("errors", {}))
        },
        "errors": madmom_data.get("errors", {})
    }

    output["rhythm_summary"] = build_rhythm_summary(output)

    if output_mode == "compact":
        final_output = compact_output(output)

    elif output_mode == "full":
        final_output = output

    else:
        final_output = compact_output(output)

        full_debug_path = output_json.replace(".json", "_full_debug.json")

        with open(full_debug_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        final_output["debug"]["full_debug_json"] = full_debug_path

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(final_output, f, ensure_ascii=False, indent=2)

    print(json.dumps({
        "success": True,
        "analysis_version": ANALYSIS_VERSION,
        "output_json": output_json,
        "duration": output["duration"],
        "bpm": output["bpm"],
        "beat_source": output["beat_source"],
        "bar_position_source": output["bar_position_source"],
        "beats_count": output["rhythm_summary"]["beats_count"],
        "downbeats_count": output["rhythm_summary"]["downbeats_count"],
        "bar_positions_count": output["rhythm_summary"]["bar_positions_count"],
        "strong_onsets_count": output["rhythm_summary"]["strong_onsets_count"],
        "major_energy_peaks_count": output["rhythm_summary"]["major_energy_peaks_count"],
        "rhythm_confidence": output["rhythm_confidence"],
        "errors_count": len(output["errors"]),
        "output_mode": output_mode
    }, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("--audio", required=True)
    parser.add_argument("--output", required=True)

    parser.add_argument(
        "--output-mode",
        choices=["compact", "full", "both"],
        default="compact"
    )

    parser.add_argument(
        "--max-markers",
        type=int,
        default=500
    )

    parser.add_argument(
        "--max-strong-onsets",
        type=int,
        default=50
    )

    parser.add_argument(
        "--max-energy-peaks",
        type=int,
        default=50
    )

    parser.add_argument(
        "--energy-min-strength",
        type=float,
        default=0.25
    )

    parser.add_argument(
        "--approximate-downbeats",
        action="store_true",
        help="If madmom downbeats fail, approximate downbeats as every 4th beat."
    )

    args = parser.parse_args()

    run(
        audio_path=args.audio,
        output_json=args.output,
        output_mode=args.output_mode,
        max_markers=args.max_markers,
        max_strong_onsets=args.max_strong_onsets,
        max_energy_peaks=args.max_energy_peaks,
        energy_min_strength=args.energy_min_strength,
        approximate_downbeats=args.approximate_downbeats
    )
