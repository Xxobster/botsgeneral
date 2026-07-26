"""Result stamping.

A number produced without a green conformance stamp is not quotable evidence, in any
report, at any readiness level (standard section 24.0). ``assert_quotable`` is the
mechanical form of that sentence: a report writer calls it and cannot proceed with a
result whose engine was never graded, or was graded and failed.

The stamp deliberately records ``UNKNOWN_DIRTY`` for a dirty working tree. A commit hash
that does not describe the code that actually ran is worse than no hash at all.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .fixture_loader import fixture_pack_hash
from .registry import registry_digest

UNKNOWN_DIRTY = "UNKNOWN_DIRTY"
UNKNOWN_NO_GIT = "UNKNOWN_NO_GIT"


class NotQuotableError(RuntimeError):
    """Raised when a result without a green conformance stamp is about to be quoted."""


@dataclass(frozen=True)
class ConformanceStamp:
    engine_name: str
    engine_version: str
    engine_commit: str
    fixture_pack_hash: str
    registry_digest: str
    contract: str
    checked_at_ms: int
    passed: bool
    required_count: int
    satisfied_count: int
    unsatisfied: tuple[str, ...] = ()
    checker_version: str = "1"
    detail: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True)

    @property
    def is_green(self) -> bool:
        return bool(self.passed) and self.satisfied_count >= self.required_count

    def one_line(self) -> str:
        state = "GREEN" if self.is_green else "NOT GREEN"
        return (
            f"{self.engine_name} {self.engine_version} @ {self.engine_commit} "
            f"| contract {self.contract} | fixtures {self.fixture_pack_hash[:12]} "
            f"| {self.satisfied_count}/{self.required_count} identifiers | {state}"
        )


def git_commit(repo: str | Path | None = None) -> str:
    """Short commit of the working tree, or ``UNKNOWN_DIRTY`` when it has changes."""
    root = Path(repo) if repo else Path(__file__).resolve().parents[4]
    try:
        rev = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if rev.returncode != 0:
            return UNKNOWN_NO_GIT
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if status.returncode != 0:
            return UNKNOWN_NO_GIT
        if status.stdout.strip():
            return UNKNOWN_DIRTY
        return rev.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return UNKNOWN_NO_GIT


def build_stamp(
    *,
    engine_name: str,
    engine_version: str,
    contract: str,
    passed: bool,
    required: int,
    satisfied: int,
    unsatisfied: tuple[str, ...] = (),
    repo: str | Path | None = None,
    detail: Mapping[str, Any] | None = None,
) -> ConformanceStamp:
    return ConformanceStamp(
        engine_name=engine_name,
        engine_version=engine_version,
        engine_commit=git_commit(repo),
        fixture_pack_hash=fixture_pack_hash(),
        registry_digest=registry_digest(),
        contract=contract,
        checked_at_ms=int(time.time() * 1000),
        passed=bool(passed),
        required_count=int(required),
        satisfied_count=int(satisfied),
        unsatisfied=tuple(unsatisfied),
        detail=dict(detail or {}),
    )


def ungraded_stamp(
    *, engine_name: str, engine_version: str, contract: str
) -> ConformanceStamp:
    """The stamp a simulation carries when no checker has run in this process.

    It is deliberately red. A caller that wants a green stamp must run the checker and
    attach its result; a simulation cannot certify itself.
    """
    return build_stamp(
        engine_name=engine_name,
        engine_version=engine_version,
        contract=contract,
        passed=False,
        required=0,
        satisfied=0,
        unsatisfied=("NOT_CHECKED_IN_THIS_PROCESS",),
        detail={"reason": "no conformance checker run recorded for this result"},
    )


#: Values of ``SimResult.liquidation_status`` that Gate A treats as a critical UNKNOWN.
#: A leveraged perpetual result that cannot say where liquidation was is not evidence,
#: because the one outcome that ends the account was never simulated.
CRITICAL_UNKNOWN_LIQUIDATION = ("UNKNOWN",)


def assert_quotable(
    stamp: ConformanceStamp | Mapping[str, Any] | None,
    *,
    result: Any = None,
) -> None:
    """Raise unless the stamp is green and the result carries no critical UNKNOWN.

    Report writers call this before printing. Passing ``result`` additionally enforces the
    Gate A rule that a critical UNKNOWN blocks the number regardless of engine grade: a
    green engine can still produce an ungradable run if the inputs left liquidation
    unmodelled.
    """
    if stamp is None:
        raise NotQuotableError(
            "result carries no conformance stamp; it is not quotable evidence "
            "(standard section 24.0)"
        )
    if isinstance(stamp, Mapping):
        stamp = ConformanceStamp(
            **{
                **{k: v for k, v in stamp.items() if k in ConformanceStamp.__annotations__},
            }
        )
    if not stamp.is_green:
        raise NotQuotableError(
            "conformance stamp is not green: "
            f"{stamp.satisfied_count}/{stamp.required_count} required identifiers "
            f"satisfied, unsatisfied={list(stamp.unsatisfied)}. "
            "This number is not quotable evidence (standard section 24.0)."
        )

    status = getattr(result, "liquidation_status", None)
    if status in CRITICAL_UNKNOWN_LIQUIDATION:
        raise NotQuotableError(
            f"liquidation_status is {status!r}, which is a critical UNKNOWN under Gate A. "
            "Supply maintenance tiers and a margin mode, or state explicitly that this "
            "product cannot be liquidated. This number is not quotable evidence."
        )


# The most recent checker run in this interpreter, so a simulation launched after a
# checker run can carry the real stamp instead of the red placeholder.
_LAST_STAMP: ConformanceStamp | None = None


def record_stamp(stamp: ConformanceStamp) -> None:
    global _LAST_STAMP
    _LAST_STAMP = stamp


def last_stamp() -> ConformanceStamp | None:
    return _LAST_STAMP
