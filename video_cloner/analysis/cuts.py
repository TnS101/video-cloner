import json
import sys
from pathlib import Path

from scenedetect import open_video, SceneManager
from scenedetect.detectors import ContentDetector


def frame_to_dict(index, start, end):
    start_seconds = round(start.seconds, 6)
    end_seconds = round(end.seconds, 6)

    return {
        "scene_index": index,
        "start_time": start.get_timecode(),
        "end_time": end.get_timecode(),
        "start_seconds": start_seconds,
        "end_seconds": end_seconds,
        "duration_seconds": round(end_seconds - start_seconds, 6),
        "start_ms": round(start_seconds * 1000),
        "end_ms": round(end_seconds * 1000),
        "duration_ms": round((end_seconds - start_seconds) * 1000),
        "start_frame": start.frame_num,
        "end_frame": end.frame_num,
    }


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "Missing input video path"}))
        sys.exit(1)

    video_path = sys.argv[1]
    threshold = float(sys.argv[2]) if len(sys.argv) > 2 else 27.0

    if not Path(video_path).exists():
        print(json.dumps({
            "ok": False,
            "error": "Video file does not exist",
            "video_path": video_path
        }))
        sys.exit(1)

    try:
        video = open_video(video_path)

        scene_manager = SceneManager()
        scene_manager.add_detector(ContentDetector(threshold=threshold))
        scene_manager.detect_scenes(video)

        scenes = scene_manager.get_scene_list(start_in_scene=True)

        cuts = [
            frame_to_dict(i + 1, start, end)
            for i, (start, end) in enumerate(scenes)
        ]

        result = {
            "ok": True,
            "video_path": video_path,
            "threshold": threshold,
            "scene_count": len(cuts),
            "cuts": cuts
        }

        print(json.dumps(result, ensure_ascii=False))

    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "video_path": video_path
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()
