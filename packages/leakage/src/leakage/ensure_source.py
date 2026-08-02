"""Force every importer onto the botsgeneral leakage package tree."""

from __future__ import annotations

import sys
from pathlib import Path

DEFAULT_BOTSGENERAL_LEAKAGE_SRC = Path(r"C:\projects\botsgeneral\packages\leakage\src")


def prefer_botsgeneral_leakage(
    src: str | Path | None = None,
    *,
    reload: bool = False,
) -> Path:
    """Put botsgeneral ``leakage`` first on ``sys.path`` and verify the import."""
    root = Path(src) if src is not None else DEFAULT_BOTSGENERAL_LEAKAGE_SRC
    root = root.resolve()
    if not (root / "leakage").is_dir():
        raise RuntimeError(f"leakage source not found at {root}")

    cleaned: list[str] = []
    for p in sys.path:
        norm = p.replace("\\", "/").lower()
        if "/leakage" in norm and "botsgeneral" not in norm:
            continue
        if norm.endswith("leakage") and "botsgeneral" not in norm:
            continue
        cleaned.append(p)
    sys.path[:] = cleaned
    s = str(root)
    if s in sys.path:
        sys.path.remove(s)
    sys.path.insert(0, s)

    if "leakage" in sys.modules and reload:
        import importlib

        importlib.reload(sys.modules["leakage"])

    import leakage  # noqa: WPS451 — intentional after path fix

    path = Path(leakage.__file__).resolve()
    if "botsgeneral" not in str(path).replace("\\", "/"):
        raise RuntimeError(
            f"refusing non-botsgeneral leakage at {path}; expected under {root}"
        )
    return path.parent


def assert_botsgeneral_leakage() -> Path:
    """Assert the already-imported ``leakage`` is the botsgeneral copy."""
    import leakage

    path = Path(leakage.__file__).resolve()
    if "botsgeneral" not in str(path).replace("\\", "/"):
        raise RuntimeError(
            f"stale leakage at {path}; call prefer_botsgeneral_leakage() "
            "before import, or: pip install -e "
            r"C:\projects\botsgeneral\packages\leakage"
        )
    return path.parent
