"""Fail-closed engine version assertion.

Runtime ``pip install -e`` was removed: auto-reinstalling the engine mid-run made
old results unreproducible. Strategies must install ``tradesim`` into their venv
(editable or pinned) and call :func:`assert_engine_version` at process start.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any


def tradesim_package_dir() -> Path:
    import tradesim

    return Path(tradesim.__file__).resolve().parent


def assert_engine_version(
    *,
    require_under: str | Path | None = None,
    min_version: str | None = None,
) -> dict[str, Any]:
    """Assert the imported ``tradesim`` is the expected engine.

    Parameters
    ----------
    require_under:
        If set, ``tradesim.__file__`` must live under this directory
        (typically ``C:\\projects\\botsgeneral\\packages\\tradesim``).
    min_version:
        If set, compare against ``tradesim.__version__`` (string equality or
        packaging-style parse when available).
    """
    import tradesim

    path = Path(tradesim.__file__).resolve()
    version = getattr(tradesim, "__version__", "?")
    info: dict[str, Any] = {
        "ok": True,
        "version": version,
        "file": str(path),
        "package_dir": str(path.parent),
    }

    if require_under is not None:
        root = Path(require_under).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise RuntimeError(
                f"refusing tradesim at {path}; expected under {root}. "
                "Install with: pip install -e "
                r"C:\projects\botsgeneral\packages\tradesim"
            ) from exc

    if min_version is not None and str(version) != str(min_version):
        # Prefer packaging comparison when available.
        try:
            from packaging.version import Version

            if Version(str(version)) < Version(str(min_version)):
                raise RuntimeError(
                    f"tradesim {version} < required {min_version} ({path})"
                )
        except ImportError:
            if str(version) != str(min_version):
                raise RuntimeError(
                    f"tradesim {version} != required {min_version} ({path})"
                ) from None

    return info


# Back-compat aliases used by older strategy bootstraps.
def prefer_botsgeneral_tradesim(*_a, **_k) -> Path:
    """Deprecated: use editable install + assert_engine_version()."""
    info = assert_engine_version(
        require_under=Path(r"C:\projects\botsgeneral\packages\tradesim")
    )
    return Path(info["package_dir"])


def assert_botsgeneral_tradesim() -> Path:
    return prefer_botsgeneral_tradesim()


def ensure_latest_tradesim(*, update: bool = False, **_k) -> dict[str, Any]:
    """Deprecated: ``update=True`` no longer runs pip. Asserts only."""
    if update:
        # Explicit no-op with a clear message for callers still passing update=True.
        pass
    return assert_engine_version(
        require_under=Path(r"C:\projects\botsgeneral\packages\tradesim")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tradesim-assert-version",
        description="Fail closed if the imported tradesim is not the botsgeneral engine",
    )
    parser.add_argument(
        "--require-under",
        default=str(Path(r"C:\projects\botsgeneral\packages\tradesim")),
        help="directory that must contain tradesim.__file__",
    )
    parser.add_argument("--min-version", default=None)
    args = parser.parse_args(argv)
    info = assert_engine_version(
        require_under=args.require_under, min_version=args.min_version
    )
    print(f"tradesim {info['version']}  from {info['file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
