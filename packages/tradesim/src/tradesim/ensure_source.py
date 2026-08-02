"""Keep every strategy environment on the latest botsgeneral tradesim.

Typical program bootstrap (before other tradesim imports)::

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(r"C:\\projects\\botsgeneral\\packages\\tradesim\\src")))
    from tradesim.ensure_source import ensure_latest_tradesim
    ensure_latest_tradesim(update=True)  # pip -e refresh + path pin

CLI::

    tradesim-update
    python -m tradesim.ensure_source --update
"""

from __future__ import annotations

import argparse
import importlib
import subprocess
import sys
from pathlib import Path
from typing import Any

# Canonical editable package root and its ``src`` layout (Windows research machine).
DEFAULT_BOTSGENERAL_TRADESIM_PKG = Path(r"C:\projects\botsgeneral\packages\tradesim")
DEFAULT_BOTSGENERAL_TRADESIM_SRC = DEFAULT_BOTSGENERAL_TRADESIM_PKG / "src"


def prefer_botsgeneral_tradesim(
    src: str | Path | None = None,
    *,
    reload: bool = False,
) -> Path:
    """Put botsgeneral ``tradesim`` first on ``sys.path`` and verify the import.

    Returns the resolved ``tradesim`` package directory that will be (or was) imported.
    Raises ``RuntimeError`` if the active module is not under botsgeneral.
    """
    root = Path(src) if src is not None else DEFAULT_BOTSGENERAL_TRADESIM_SRC
    root = root.resolve()
    if not (root / "tradesim").is_dir():
        raise RuntimeError(f"tradesim source not found at {root}")

    # Drop other tradesim path entries so site-packages cannot win.
    cleaned: list[str] = []
    for p in sys.path:
        norm = p.replace("\\", "/").lower()
        if "tradesim" in norm and "botsgeneral" not in norm:
            continue
        cleaned.append(p)
    sys.path[:] = cleaned
    s = str(root)
    if s in sys.path:
        sys.path.remove(s)
    sys.path.insert(0, s)

    if reload:
        _reload_tradesim_modules()

    import tradesim  # noqa: WPS451 — intentional after path fix

    path = Path(tradesim.__file__).resolve()
    if "botsgeneral" not in str(path).replace("\\", "/"):
        raise RuntimeError(
            f"refusing non-botsgeneral tradesim at {path}; "
            f"expected under {root}"
        )
    return path.parent


def assert_botsgeneral_tradesim() -> Path:
    """Assert the already-imported ``tradesim`` is the botsgeneral copy."""
    import tradesim

    path = Path(tradesim.__file__).resolve()
    if "botsgeneral" not in str(path).replace("\\", "/"):
        raise RuntimeError(
            f"stale tradesim at {path}; call ensure_latest_tradesim(update=True) "
            "or: pip install -e C:\\projects\\botsgeneral\\packages\\tradesim"
        )
    return path.parent


def update_tradesim(
    *,
    extras: str = "conformance,plot",
    pkg: str | Path | None = None,
    quiet: bool = False,
) -> dict[str, Any]:
    """Re-install the editable botsgeneral tradesim into *this* Python environment.

    Equivalent to::

        pip install -e C:\\projects\\botsgeneral\\packages\\tradesim[conformance,plot]

    Returns a small status dict (``ok``, ``returncode``, ``path``, ``version``).
    """
    package = Path(pkg) if pkg is not None else DEFAULT_BOTSGENERAL_TRADESIM_PKG
    package = package.resolve()
    if not (package / "pyproject.toml").is_file():
        raise RuntimeError(f"tradesim package not found at {package}")

    target = str(package)
    if extras:
        target = f"{package}[{extras}]"
    cmd = [sys.executable, "-m", "pip", "install", "-e", target]
    if quiet:
        cmd.append("-q")
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            "tradesim update failed:\n"
            f"cmd={' '.join(cmd)}\n"
            f"stdout={proc.stdout[-2000:]}\n"
            f"stderr={proc.stderr[-2000:]}"
        )

    path = prefer_botsgeneral_tradesim(package / "src", reload=True)
    import tradesim

    return {
        "ok": True,
        "returncode": proc.returncode,
        "path": str(path),
        "package": str(package),
        "version": getattr(tradesim, "__version__", "?"),
        "file": str(Path(tradesim.__file__).resolve()),
    }


def ensure_latest_tradesim(
    *,
    update: bool = True,
    extras: str = "conformance,plot",
    quiet: bool = True,
) -> dict[str, Any]:
    """Pin to botsgeneral tradesim; optionally ``pip install -e`` to refresh.

    Parameters
    ----------
    update:
        If True (default), run editable reinstall so the current venv picks up
        any edits under ``C:\\projects\\botsgeneral\\packages\\tradesim``.
        If False, only reorder ``sys.path`` / assert location.
    """
    info: dict[str, Any] = {"updated": False}
    if update:
        info.update(update_tradesim(extras=extras, quiet=quiet))
        info["updated"] = True
    else:
        path = prefer_botsgeneral_tradesim(reload=False)
        import tradesim

        info.update(
            {
                "ok": True,
                "path": str(path),
                "version": getattr(tradesim, "__version__", "?"),
                "file": str(Path(tradesim.__file__).resolve()),
            }
        )
    assert_botsgeneral_tradesim()
    return info


def _reload_tradesim_modules() -> None:
    """Drop cached tradesim modules so the next import sees disk edits."""
    doomed = [name for name in list(sys.modules) if name == "tradesim" or name.startswith("tradesim.")]
    for name in doomed:
        del sys.modules[name]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tradesim-update",
        description="Install/refresh editable botsgeneral tradesim in this environment",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        default=True,
        help="pip install -e the botsgeneral package (default)",
    )
    parser.add_argument(
        "--no-update",
        action="store_true",
        help="only pin sys.path / assert location (no pip)",
    )
    parser.add_argument(
        "--extras",
        default="conformance,plot",
        help="optional extras for pip -e (default: conformance,plot)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    do_update = bool(args.update) and not bool(args.no_update)
    info = ensure_latest_tradesim(
        update=do_update, extras=args.extras, quiet=not args.verbose
    )
    print(
        f"tradesim {info.get('version')}  "
        f"updated={info.get('updated')}  "
        f"from {info.get('file')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
