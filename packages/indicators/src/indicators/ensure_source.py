"""Force every importer onto the botsgeneral indicators package tree."""

from __future__ import annotations

import sys
from pathlib import Path

DEFAULT_BOTSGENERAL_INDICATORS_SRC = Path(r"C:\projects\botsgeneral\packages\indicators\src")


def prefer_botsgeneral_indicators(
    src: str | Path | None = None,
    *,
    reload: bool = False,
) -> Path:
    """Put botsgeneral ``indicators`` first on ``sys.path`` and verify the import."""
    root = Path(src) if src is not None else DEFAULT_BOTSGENERAL_INDICATORS_SRC
    root = root.resolve()
    if not (root / "indicators").is_dir():
        raise RuntimeError(f"indicators source not found at {root}")

    cleaned: list[str] = []
    for p in sys.path:
        norm = p.replace("\\", "/").lower()
        if "/indicators" in norm and "botsgeneral" not in norm:
            continue
        if norm.endswith("indicators") and "botsgeneral" not in norm:
            continue
        cleaned.append(p)
    sys.path[:] = cleaned
    s = str(root)
    if s in sys.path:
        sys.path.remove(s)
    sys.path.insert(0, s)

    if "indicators" in sys.modules and reload:
        import importlib

        importlib.reload(sys.modules["indicators"])

    import indicators  # noqa: WPS451 — intentional after path fix

    path = Path(indicators.__file__).resolve()
    if "botsgeneral" not in str(path).replace("\\", "/"):
        raise RuntimeError(
            f"refusing non-botsgeneral indicators at {path}; expected under {root}"
        )
    return path.parent


def assert_botsgeneral_indicators() -> Path:
    """Assert the already-imported ``indicators`` is the botsgeneral copy."""
    import indicators

    path = Path(indicators.__file__).resolve()
    if "botsgeneral" not in str(path).replace("\\", "/"):
        raise RuntimeError(
            f"stale indicators at {path}; call prefer_botsgeneral_indicators() "
            "before import, or: pip install -e "
            r"C:\projects\botsgeneral\packages\indicators"
        )
    return path.parent
