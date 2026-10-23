"""JSON helpers — Bybit metrics can contain inf / nan."""

from __future__ import annotations

import json
import math
from typing import Any


def jsonable(obj: Any) -> Any:
    """Replace NaN / Inf floats so json.dumps never emits invalid JSON."""
    if isinstance(obj, float):
        if math.isnan(obj):
            return None
        if math.isinf(obj):
            return "inf" if obj > 0 else "-inf"
        return obj
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    return obj


def dumps(obj: Any, **kwargs: Any) -> str:
    kwargs.setdefault("separators", (",", ":"))
    return json.dumps(jsonable(obj), **kwargs)
