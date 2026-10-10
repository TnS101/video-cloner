"""Editor-independent caption animation recipe contract."""
from __future__ import annotations

import math
from typing import Any


SCHEMA = "video_cloner.caption_animation_recipe"
SCHEMA_VERSION = 1


def validate_recipe(recipe: dict[str, Any]) -> dict[str, Any]:
    if recipe.get("schema") != SCHEMA or recipe.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("recipe_schema")
    duration = int(recipe.get("duration") or 0)
    start_frame = recipe.get("start_frame")
    if duration < 1 or not isinstance(start_frame, int) or isinstance(start_frame, bool) or start_frame < 0 or not str(recipe.get("caption_id") or ""):
        raise ValueError("recipe_identity")
    channels = recipe.get("channels")
    if not isinstance(channels, dict) or not channels:
        raise ValueError("recipe_channels")
    for name, keys in channels.items():
        if name not in {"position", "scale", "opacity"} or not isinstance(keys, list) or not keys:
            raise ValueError(f"recipe_channel:{name}")
        frames = []
        for key in keys:
            frame = int(key.get("frame"))
            value = key.get("value")
            if frame < 0 or frame >= duration or key.get("interpolation") not in {"linear", "hold"}:
                raise ValueError(f"recipe_key:{name}")
            frames.append(frame)
            values = value if isinstance(value, list) else [value]
            if not values or any(not math.isfinite(float(part)) for part in values):
                raise ValueError(f"recipe_value:{name}")
            if name in {"position", "scale"} and len(values) != 2:
                raise ValueError(f"recipe_arity:{name}")
            if name == "scale" and any(float(part) <= 0 for part in values):
                raise ValueError("recipe_scale")
            if name == "opacity" and (len(values) != 1 or not 0.0 <= float(values[0]) <= 1.0):
                raise ValueError("recipe_opacity")
        if frames != sorted(set(frames)):
            raise ValueError(f"recipe_frame_order:{name}")
    return recipe
