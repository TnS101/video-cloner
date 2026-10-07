from __future__ import annotations

import sys
import types


if "paddleocr" not in sys.modules:
    paddleocr = types.ModuleType("paddleocr")
    paddleocr.PaddleOCR = object
    sys.modules["paddleocr"] = paddleocr

from video_cloner.analysis.caption_style import choose_fill_stroke_shadow


def _cluster(hex_color: str, ratio: float, brightness: float, saturation: float) -> dict:
    return {
        "hex": hex_color,
        "ratio": ratio,
        "brightness": brightness,
        "saturation": saturation,
    }


def _resolve(clusters: list[dict]) -> dict:
    return choose_fill_stroke_shadow(
        clusters,
        dark_ratio=0.4,
        bright_ratio=0.2,
        saturated_ratio=0.4,
        font_ratio=0.07,
        width_ratio=0.4,
    )


def test_we_dont_prefers_recorded_orange_cream_foreground_over_teal_crop():
    result = _resolve([
        _cluster("#071717", 0.4423, 23, 177),
        _cluster("#f3ca9a", 0.2043, 243, 93),
        _cluster("#18636b", 0.1705, 107, 198),
        _cluster("#e4814b", 0.1522, 228, 171),
        _cluster("#f6f6f9", 0.0307, 249, 3),
    ])

    assert result["fill"] in {"#f3ca9a", "#e4814b"}
    assert result["fill"] != "#18636b"
    assert result["stroke"] == "#071717"


def test_before_sign_prefers_recorded_gold_foreground_over_crop_and_highlight():
    result = _resolve([
        _cluster("#20221c", 0.2507, 34, 45),
        _cluster("#dcb999", 0.2472, 220, 78),
        _cluster("#b48d6e", 0.2237, 180, 99),
        _cluster("#5c4c3c", 0.1963, 92, 89),
        _cluster("#eceae6", 0.0822, 236, 6),
    ])

    assert result["fill"] == "#dcb999"
    assert result["stroke"] == "#20221c"


def test_6000_promotes_recorded_gold_to_fill_instead_of_stroke():
    result = _resolve([
        _cluster("#061312", 0.4978, 19, 174),
        _cluster("#f6d09d", 0.2130, 246, 92),
        _cluster("#0c6177", 0.1320, 119, 229),
        _cluster("#d09a70", 0.0985, 208, 118),
        _cluster("#533f31", 0.0587, 83, 104),
    ])

    assert result["fill"] == "#f6d09d"
    assert result["fill"] != "#0c6177"
    assert result["stroke"] == "#061312"
