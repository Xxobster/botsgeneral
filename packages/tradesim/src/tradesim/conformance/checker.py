"""The conformance checker.

It does four things, in this order:

1. reads the identifier set the declared contract makes mandatory;
2. discovers which tests in the target suite *declare* which identifiers, by parsing the
   source rather than by running anything;
3. runs those tests;
4. replays the golden fixture pack against the declared engine.

It exits non-zero when a required identifier has no binding, when a bound test is
skipped, when a bound test fails, or when a fixture fails.

The first of those is the one that matters most. A missing test fails exactly like a
failing test. The entry-bar defect survived for the lifetime of a project behind a fully
green suite, because nothing in that suite claimed to cover the entry bar and nothing
objected to the silence.
"""

from __future__ import annotations

import argparse
import ast
import importlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import registry
from .adapter import EngineAdapter, FixtureOutcome, grade
from .fixture_loader import fixture_pack_hash, load_fixtures
from .stamp import ConformanceStamp, build_stamp, record_stamp

CHECKER_VERSION = "1"


# --------------------------------------------------------------------------------------
# Binding discovery
# --------------------------------------------------------------------------------------


@dataclass
class Binding:
    identifier: str
    node_id: str
    file: str
    line: int
    source: str  # "name" | "docstring" | "decorator"


def _decorator_text(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - very old ast
        return ""


def _identifiers_from_function(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for ident in registry.extract_identifiers(fn.name):
        found.append((ident, "name"))
    doc = ast.get_docstring(fn) or ""
    for ident in registry.extract_identifiers(doc):
        found.append((ident, "docstring"))
    for dec in fn.decorator_list:
        for ident in registry.extract_identifiers(_decorator_text(dec)):
            found.append((ident, "decorator"))
    # De-duplicate while keeping the strongest source first.
    order = {"decorator": 0, "name": 1, "docstring": 2}
    seen: dict[str, str] = {}
    for ident, src in found:
        if ident not in seen or order[src] < order[seen[ident]]:
            seen[ident] = src
    return sorted(seen.items(), key=lambda kv: kv[0])


def discover_bindings(test_paths: Sequence[Path]) -> list[Binding]:
    """Parse the suite and record every identifier a test declares.

    A test that exercises a behaviour without declaring its identifier does not satisfy
    it. That is intentional: the declaration is the contract, and it is what makes the
    absence of a test detectable.
    """
    bindings: list[Binding] = []
    files: list[Path] = []
    for p in test_paths:
        if p.is_dir():
            files.extend(sorted(p.rglob("test_*.py")))
        elif p.is_file():
            files.append(p)
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            raise RuntimeError(f"cannot parse test file {path}: {exc}") from exc
        _walk_module(tree, path, bindings)
    return bindings


def _walk_module(tree: ast.Module, path: Path, out: list[Binding]) -> None:
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test"):
                _emit(node, path, None, out)
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            class_ids = registry.extract_identifiers(
                node.name + "\n" + (ast.get_docstring(node) or "")
            )
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name.startswith(
                    "test"
                ):
                    _emit(sub, path, node.name, out, extra=class_ids)


def _emit(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
    path: Path,
    class_name: str | None,
    out: list[Binding],
    extra: Iterable[str] = (),
) -> None:
    node_id = f"{path.as_posix()}::{class_name}::{fn.name}" if class_name else f"{path.as_posix()}::{fn.name}"
    pairs = _identifiers_from_function(fn)
    for ident in extra:
        if ident not in dict(pairs):
            pairs.append((ident, "decorator"))
    for ident, source in pairs:
        out.append(
            Binding(
                identifier=ident,
                node_id=node_id,
                file=str(path),
                line=fn.lineno,
                source=source,
            )
        )


# --------------------------------------------------------------------------------------
# Running the bound tests
# --------------------------------------------------------------------------------------


@dataclass
class TestOutcome:
    node_id: str
    status: str  # PASSED | FAILED | SKIPPED | ERROR | NOT_COLLECTED
    detail: str = ""
    file: str = ""


def _report_file(report: Any) -> str:  # noqa: ANN401
    """Absolute path of the file a report came from.

    ``report.nodeid`` is relative to the pytest rootdir and its path component comes out
    empty when the suite and the invocation directory sit on different Windows drives,
    so the file is carried separately rather than parsed back out of the node id.
    """
    path = getattr(report, "path", None)
    if path is not None:
        return str(path)
    fspath = getattr(report, "fspath", None)
    return str(fspath) if fspath else ""


class _Collector:
    """pytest plugin that records the final outcome of every test it sees."""

    def __init__(self) -> None:
        self.results: dict[str, TestOutcome] = {}

    def pytest_runtest_logreport(self, report: Any) -> None:  # noqa: ANN401
        nodeid = report.nodeid
        file = _report_file(report)
        if report.when == "call":
            if report.passed:
                self._set(nodeid, file, "PASSED")
            elif report.skipped:
                self._set(nodeid, file, "SKIPPED", str(getattr(report, "longrepr", "")))
            else:
                self._set(nodeid, file, "FAILED", _short(report))
        elif report.when == "setup":
            if report.skipped:
                self._set(nodeid, file, "SKIPPED", str(getattr(report, "longrepr", "")))
            elif report.failed:
                self._set(nodeid, file, "ERROR", _short(report))
        elif report.when == "teardown" and report.failed:
            self._set(nodeid, file, "ERROR", _short(report))

    def _set(self, nodeid: str, file: str, status: str, detail: str = "") -> None:
        rank = {"PASSED": 0, "SKIPPED": 1, "FAILED": 2, "ERROR": 3}
        key = f"{file}|{nodeid}"
        prev = self.results.get(key)
        if prev is None or rank[status] >= rank[prev.status]:
            self.results[key] = TestOutcome(nodeid, status, detail, file)


def _short(report: Any) -> str:  # noqa: ANN401
    text = str(getattr(report, "longrepr", "") or "")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return " / ".join(lines[-3:])[:500]


def run_tests(test_paths: Sequence[Path], extra_args: Sequence[str] = ()) -> dict[str, TestOutcome]:
    try:
        import pytest
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "the conformance checker needs pytest; install with "
            "`pip install 'tradesim[conformance]'`"
        ) from exc
    collector = _Collector()
    args = [str(p) for p in test_paths] + ["-q", "-p", "no:cacheprovider", *extra_args]
    pytest.main(args, plugins=[collector])
    return collector.results


def _match_outcomes(
    node_id: str, outcomes: Mapping[str, TestOutcome]
) -> list[TestOutcome]:
    """Map an ast-derived node id onto the pytest outcomes it produced.

    pytest reports paths relative to its rootdir and appends ``[params]`` to
    parametrised cases, so matching is done on the trailing components. The file is taken
    from the recorded absolute path rather than from the node id, because the node id's
    path component is empty whenever pytest cannot express the file relative to its
    rootdir.
    """
    parts = node_id.split("::")
    file_tail = Path(parts[0]).name
    suffix = "::".join(parts[1:])
    hits: list[TestOutcome] = []
    for outcome in outcomes.values():
        p_parts = outcome.node_id.split("::")
        reported_file = outcome.file or p_parts[0]
        if Path(reported_file).name != file_tail:
            continue
        p_suffix = "::".join(p_parts[1:])
        base = p_suffix.split("[", 1)[0]
        if base == suffix or p_suffix == suffix:
            hits.append(outcome)
    return hits


# --------------------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------------------


@dataclass
class IdentifierRow:
    identifier: str
    required: bool
    behaviour: str
    bindings: list[str] = field(default_factory=list)
    test_status: str = "NO_BINDING"
    fixture_status: str = "NO_FIXTURE"
    problems: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.problems:
            return "FAIL"
        if not self.required:
            return "PASS" if self.bindings or self.fixture_status == "PASS" else "N/A"
        return "PASS"


@dataclass
class CheckReport:
    engine: str
    engine_version: str
    contract: str
    rows: list[IdentifierRow]
    fixture_outcomes: list[FixtureOutcome]
    fixture_pack_hash: str
    ok: bool
    required: int
    satisfied: int
    unsatisfied: list[str]
    stamp: ConformanceStamp

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "engine_version": self.engine_version,
            "contract": self.contract,
            "ok": self.ok,
            "required": self.required,
            "satisfied": self.satisfied,
            "unsatisfied": self.unsatisfied,
            "fixture_pack_hash": self.fixture_pack_hash,
            "stamp": self.stamp.as_dict(),
            "identifiers": [
                {
                    "identifier": r.identifier,
                    "required": r.required,
                    "test_status": r.test_status,
                    "fixture_status": r.fixture_status,
                    "bindings": r.bindings,
                    "problems": r.problems,
                }
                for r in self.rows
            ],
            "fixtures": [
                {
                    "fixture": f.fixture,
                    "ids": list(f.ids),
                    "status": f.status,
                    "failures": list(f.failures),
                    "detail": f.detail,
                }
                for f in self.fixture_outcomes
            ],
        }


def check(
    *,
    adapter: EngineAdapter,
    test_paths: Sequence[Path],
    contract: str,
    run_bound_tests: bool = True,
    pytest_args: Sequence[str] = (),
) -> CheckReport:
    required_ids = set(registry.required_for(contract))

    bindings = discover_bindings(test_paths) if test_paths else []
    by_id: dict[str, list[Binding]] = {}
    for b in bindings:
        by_id.setdefault(b.identifier, []).append(b)

    unknown = sorted(set(by_id) - {i.identifier for i in registry.all_items()})

    outcomes: dict[str, TestOutcome] = {}
    if run_bound_tests and test_paths:
        outcomes = run_tests(test_paths, pytest_args)

    fixture_outcomes = [grade(adapter, fx) for fx in load_fixtures()]
    fixture_by_id: dict[str, list[FixtureOutcome]] = {}
    for fo in fixture_outcomes:
        for ident in fo.ids:
            fixture_by_id.setdefault(ident, []).append(fo)

    rows: list[IdentifierRow] = []
    for item in registry.all_items():
        if item.retired:
            continue
        req = item.identifier in required_ids
        row = IdentifierRow(
            identifier=item.identifier,
            required=req,
            behaviour=item.behaviour,
        )
        my_bindings = by_id.get(item.identifier, [])
        row.bindings = [b.node_id for b in my_bindings]

        if not my_bindings:
            row.test_status = "NO_BINDING"
            if req:
                row.problems.append(
                    "no test declares this identifier — a missing binding is a hard "
                    "failure, exactly like a failing test"
                )
        elif not run_bound_tests:
            row.test_status = "NOT_RUN"
        else:
            statuses: list[str] = []
            for b in my_bindings:
                matched = _match_outcomes(b.node_id, outcomes)
                if not matched:
                    statuses.append("NOT_COLLECTED")
                    row.problems.append(
                        f"{b.node_id} declares {item.identifier} but pytest never ran it"
                    )
                for m in matched:
                    statuses.append(m.status)
                    if m.status == "SKIPPED":
                        row.problems.append(
                            f"{m.node_id} is bound to {item.identifier} but was skipped; "
                            "a skipped conformance test is a failure"
                        )
                    elif m.status in ("FAILED", "ERROR"):
                        row.problems.append(f"{m.node_id} {m.status}: {m.detail}")
            row.test_status = _worst(statuses)

        my_fixtures = fixture_by_id.get(item.identifier, [])
        if not my_fixtures:
            row.fixture_status = "NO_FIXTURE"
            if req and item.fixture_computable:
                row.problems.append(
                    "the registry declares this identifier exactly computable but the "
                    "fixture pack has no case for it"
                )
        else:
            fstat = [fo.status for fo in my_fixtures]
            row.fixture_status = _worst_fixture(fstat)
            for fo in my_fixtures:
                if fo.status == "FAIL":
                    for msg in fo.failures:
                        row.problems.append(f"fixture {fo.fixture}: {msg}")
                elif fo.status == "ERROR":
                    row.problems.append(f"fixture {fo.fixture} raised: {fo.detail}")
                elif fo.status == "UNSUPPORTED" and req:
                    row.problems.append(
                        f"fixture {fo.fixture} is unsupported by this engine: {fo.detail}"
                    )
        rows.append(row)

    satisfied = [r.identifier for r in rows if r.required and not r.problems]
    unsatisfied = [r.identifier for r in rows if r.required and r.problems]

    # Fixtures that fail while covering only non-required identifiers still fail the run:
    # the pack is an arbiter, not a suggestion.
    stray_fixture_failures = [
        fo for fo in fixture_outcomes if fo.status in ("FAIL", "ERROR")
    ]

    ok = not unsatisfied and not stray_fixture_failures and not unknown
    stamp = build_stamp(
        engine_name=adapter.name,
        engine_version=adapter.version,
        contract=contract,
        passed=ok,
        required=len(satisfied) + len(unsatisfied),
        satisfied=len(satisfied),
        unsatisfied=tuple(unsatisfied),
        detail={
            "checker_version": CHECKER_VERSION,
            "unknown_identifiers_in_tests": unknown,
            "n_fixtures": len(fixture_outcomes),
        },
    )
    record_stamp(stamp)

    report = CheckReport(
        engine=adapter.name,
        engine_version=adapter.version,
        contract=contract,
        rows=rows,
        fixture_outcomes=fixture_outcomes,
        fixture_pack_hash=fixture_pack_hash(),
        ok=ok,
        required=len(satisfied) + len(unsatisfied),
        satisfied=len(satisfied),
        unsatisfied=unsatisfied,
        stamp=stamp,
    )
    setattr(report, "unknown_identifiers", unknown)
    return report


def _worst(statuses: Sequence[str]) -> str:
    if not statuses:
        return "NO_BINDING"
    rank = {"PASSED": 0, "NOT_COLLECTED": 1, "SKIPPED": 2, "FAILED": 3, "ERROR": 4}
    return max(statuses, key=lambda s: rank.get(s, 5))


def _worst_fixture(statuses: Sequence[str]) -> str:
    if not statuses:
        return "NO_FIXTURE"
    rank = {"PASS": 0, "UNSUPPORTED": 1, "FAIL": 2, "ERROR": 3}
    return max(statuses, key=lambda s: rank.get(s, 4))


# --------------------------------------------------------------------------------------
# Printing
# --------------------------------------------------------------------------------------


def print_report(report: CheckReport, *, stream: Any = None, verbose: bool = True) -> None:  # noqa: ANN401
    out = stream or sys.stdout
    w = out.write

    w("\n")
    w("=" * 100 + "\n")
    w(f"tradesim conformance — engine {report.engine} {report.engine_version} — contract {report.contract}\n")
    w(f"fixture pack {report.fixture_pack_hash[:16]}  ({len(report.fixture_outcomes)} fixtures)\n")
    w("=" * 100 + "\n")
    header = f"{'IDENTIFIER':<11} {'REQ':<4} {'TESTS':<14} {'FIXTURES':<11} {'STATUS':<7} BOUND TEST\n"
    w(header)
    w("-" * 100 + "\n")
    for row in report.rows:
        bound = row.bindings[0].split("::", 1)[-1] if row.bindings else "-"
        if len(row.bindings) > 1:
            bound += f" (+{len(row.bindings) - 1})"
        status = "FAIL" if row.problems else ("PASS" if row.required else "ok")
        w(
            f"{row.identifier:<11} {'yes' if row.required else 'no':<4} "
            f"{row.test_status:<14} {row.fixture_status:<11} {status:<7} {bound}\n"
        )
    w("-" * 100 + "\n")

    problems = [r for r in report.rows if r.problems]
    if problems:
        w("\nPROBLEMS\n")
        for row in problems:
            w(f"\n  {row.identifier} — {row.behaviour}\n")
            for p in row.problems:
                w(f"      - {p}\n")

    unknown = getattr(report, "unknown_identifiers", [])
    if unknown:
        w("\nUNKNOWN IDENTIFIERS DECLARED BY TESTS (identifiers are permanent; do not invent):\n")
        for ident in unknown:
            w(f"      - {ident}\n")

    unsupported = [f for f in report.fixture_outcomes if f.status == "UNSUPPORTED"]
    if unsupported and verbose:
        w(f"\nUNSUPPORTED FIXTURES ({len(unsupported)}) — capability gaps, not passes:\n")
        for fo in unsupported:
            w(f"      - {fo.fixture} [{', '.join(fo.ids)}]: {fo.detail}\n")

    w("\n")
    w(f"required identifiers : {report.required}\n")
    w(f"satisfied            : {report.satisfied}\n")
    if report.unsatisfied:
        w(f"UNSATISFIED          : {', '.join(report.unsatisfied)}\n")
    missing_entry_bar = [
        i for i in registry.NON_NEGOTIABLE_ENTRY_BAR if i in report.unsatisfied
    ]
    if missing_entry_bar:
        w(
            "\n*** The jointly non-negotiable entry-bar identifiers are not all satisfied: "
            f"{', '.join(missing_entry_bar)}.\n"
            "*** This engine may not declare execution parity, and no number it produced "
            "is quotable evidence.\n"
        )
    w("\n" + ("RESULT: PASS" if report.ok else "RESULT: FAIL") + "\n")
    w(f"stamp: {report.stamp.one_line()}\n\n")


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def _load_adapter(spec: str, contract: str) -> EngineAdapter:
    if spec == "tradesim":
        from .adapter import TradesimAdapter

        return TradesimAdapter(contract=contract)
    if ":" not in spec:
        raise SystemExit(
            f"--engine must be 'tradesim' or 'module.path:factory', got {spec!r}"
        )
    module_name, factory_name = spec.split(":", 1)
    module = importlib.import_module(module_name)
    factory = getattr(module, factory_name)
    return factory()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tradesim-conformance",
        description=(
            "Grade a trade-execution engine against the shared conformance identifier "
            "registry and golden fixture pack. Exits non-zero when a required "
            "identifier has no binding, when a bound test is skipped or fails, or when "
            "a fixture fails."
        ),
    )
    parser.add_argument(
        "--engine",
        default="tradesim",
        help="'tradesim' or 'module.path:adapter_factory' for a foreign engine",
    )
    parser.add_argument(
        "--tests",
        nargs="*",
        default=[],
        help="test files or directories to scan for identifier bindings and to run",
    )
    parser.add_argument(
        "--contract",
        default=registry.CONTRACT_BRACKET_PORTFOLIO,
        choices=list(registry.CONTRACTS),
        help="which identifier set is mandatory for this engine",
    )
    parser.add_argument("--json", default=None, help="write the full report to this path")
    parser.add_argument(
        "--no-run-tests",
        action="store_true",
        help="discover bindings and replay fixtures without executing the test suite",
    )
    parser.add_argument(
        "--pytest-arg",
        action="append",
        default=[],
        help="extra argument forwarded to pytest (repeatable)",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    adapter = _load_adapter(args.engine, args.contract)
    test_paths = [Path(p).resolve() for p in args.tests]
    for p in test_paths:
        if not p.exists():
            raise SystemExit(f"test path does not exist: {p}")

    report = check(
        adapter=adapter,
        test_paths=test_paths,
        contract=args.contract,
        run_bound_tests=not args.no_run_tests,
        pytest_args=args.pytest_arg,
    )
    print_report(report, verbose=not args.quiet)

    if args.json:
        Path(args.json).write_text(
            json.dumps(report.to_dict(), indent=2), encoding="utf-8"
        )

    return 0 if report.ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
