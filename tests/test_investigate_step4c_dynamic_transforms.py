import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/analysis/investigate_step4c_dynamic_transforms.py"
SPEC = importlib.util.spec_from_file_location("step4c_investigation", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(MODULE)


def test_rotation_gate_distinguishes_static_tilt_from_dynamic_rotation():
    static = [{"source_frame": frame, "angle_degrees": angle} for frame, angle in zip((1, 4, 7, 10), (-3.70, -3.68, -3.72, -3.69))]
    dynamic = [{"source_frame": frame, "angle_degrees": angle} for frame, angle in zip((1, 4, 7, 10), (-4.0, -4.8, -5.6, -6.4))]
    assert MODULE.classify_rotation(MODULE.rotation_metrics(static)) == "STATIC_TILT_ONLY"
    assert MODULE.classify_rotation(MODULE.rotation_metrics(dynamic)) == "DYNAMIC_ROTATION_SUPPORTED"


def test_mask_angle_is_translation_invariant():
    mask = np.zeros((60, 120), np.uint8)
    points = np.asarray([[10, 35], [105, 20], [108, 27], [13, 42]], np.int32)
    import cv2
    cv2.fillConvexPoly(mask, points, 1)
    flat = mask.reshape(-1); runs=[]; start=None
    for index,value in enumerate(np.append(flat,0)):
        if value and start is None: start=index
        elif not value and start is not None: runs.append([start,index-start]); start=None
    angle = MODULE.mask_angle_degrees(list(mask.shape), runs)
    shifted = np.zeros_like(mask); shifted[5:, 7:] = mask[:-5, :-7]
    flat = shifted.reshape(-1); runs=[]; start=None
    for index,value in enumerate(np.append(flat,0)):
        if value and start is None: start=index
        elif not value and start is not None: runs.append([start,index-start]); start=None
    assert abs(angle - MODULE.mask_angle_degrees(list(shifted.shape), runs)) < 0.01
