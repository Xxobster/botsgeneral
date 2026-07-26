"""VALD-001 .. VALD-006 — the conformance machinery graded by itself.

The pack only earns its keep if a missing test fails as loudly as a failing one. These
tests build small throwaway suites in a temporary directory and check that the checker
reaches the verdict the standard requires, including the two verdicts that are easiest to
get wrong: silence about an identifier nobody tested, and a skip dressed up as a pass.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from conftest import QUIET_BAR_1, SIGNAL_BAR, TF, long_signal, run
from tradesim import NotQuotableError, assert_quotable, simulate_portfolio
from tradesim.conformance import registry, stamp as stamp_mod
from tradesim.conformance.adapter import TradesimAdapter
from tradesim.conformance.checker import check
from tradesim.conformance.fixture_loader import fixture_pack_hash
from tradesim.conformance.stamp import UNKNOWN_DIRTY, build_stamp
from tradesim.engine import SymbolStream


def _row(report, identifier):
    return next(r for r in report.rows if r.identifier == identifier)


def _mini_suite(tmp_path: Path, name: str, body: str) -> Path:
    """Write a throwaway suite for the checker to grade.

    The file name has to be unique across the session: these run under a nested pytest,
    and two modules with the same basename outside a package collide on import.
    """
    path = tmp_path / f"test_mini_{name}.py"
    path.write_text(body, encoding="utf-8")
    return path


@pytest.mark.conformance("VALD-001")
def test_vald_001_every_result_carries_a_stamp(instrument, costs, margin, sizing, sim):
    """VALD-001: a simulation stamps itself, and it stamps itself RED by default.

    A run that no checker has graded in this process cannot certify itself. The stamp is
    present so the absence of grading is visible, rather than being a missing field that
    a report writer can forget to look for.
    """
    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.5, 111.0, 100.0, 110.0]],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
        attach_stamp=True,
    )

    assert result.stamp is not None
    assert result.stamp["engine_name"] == "tradesim"
    assert result.stamp["fixture_pack_hash"] == fixture_pack_hash()


@pytest.mark.conformance("VALD-001")
def test_vald_001_assert_quotable_refuses_absent_and_red_stamps():
    """VALD-001: the mechanical form of "not quotable evidence"."""
    with pytest.raises(NotQuotableError, match="no conformance stamp"):
        assert_quotable(None)

    red = build_stamp(
        engine_name="tradesim",
        engine_version="1.0.0",
        contract=registry.CONTRACT_BRACKET_PORTFOLIO,
        passed=False,
        required=62,
        satisfied=61,
        unsatisfied=("EXEC-014",),
    )
    with pytest.raises(NotQuotableError, match="EXEC-014"):
        assert_quotable(red)
    with pytest.raises(NotQuotableError):
        assert_quotable(red.as_dict())

    green = build_stamp(
        engine_name="tradesim",
        engine_version="1.0.0",
        contract=registry.CONTRACT_BRACKET_PORTFOLIO,
        passed=True,
        required=62,
        satisfied=62,
    )
    assert green.is_green
    assert_quotable(green)
    assert_quotable(green.as_dict())


@pytest.mark.conformance("VALD-001")
def test_vald_001_a_critical_unknown_blocks_a_green_engine(
    instrument, costs, margin, sizing, sim
):
    """VALD-001: Gate A's "no critical UNKNOWN" outranks the engine's own grade.

    A green engine can still produce a run that is not evidence. If liquidation was never
    modelled for a leveraged perpetual, the one outcome that ends the account is missing
    from the simulation, and the profit and loss is a number about a different product.
    """
    green = build_stamp(
        engine_name="tradesim",
        engine_version="1.0.0",
        contract=registry.CONTRACT_BRACKET_PORTFOLIO,
        passed=True,
        required=62,
        satisfied=62,
    )

    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.5, 111.0, 100.0, 110.0]],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )
    # This run does model liquidation, so it passes with the same stamp.
    assert result.liquidation_status in ("MODELLED", "SIMPLIFIED")
    assert_quotable(green, result=result)

    class _Ungradable:
        liquidation_status = "UNKNOWN"

    with pytest.raises(NotQuotableError, match="critical UNKNOWN"):
        assert_quotable(green, result=_Ungradable())


@pytest.mark.conformance("VALD-002")
def test_vald_002_a_missing_binding_fails_the_check(tmp_path):
    """VALD-002: an identifier no test declares is a failure, not a gap in coverage.

    This is the single most important behaviour in the package. The original defect
    survived for the lifetime of a project behind a fully green suite, because no test
    claimed to cover the entry bar and nothing objected to the silence.
    """
    suite = _mini_suite(
        tmp_path,
        "missing_binding",
        '''
import pytest


@pytest.mark.conformance("EXEC-010")
def test_only_one_identifier_is_declared():
    assert True
''',
    )
    report = check(
        adapter=TradesimAdapter(contract=registry.CONTRACT_BRACKET_PORTFOLIO),
        test_paths=[suite],
        contract=registry.CONTRACT_BRACKET_PORTFOLIO,
        run_bound_tests=True,
    )

    assert report.ok is False
    assert _row(report, "EXEC-010").test_status == "PASSED"
    assert _row(report, "EXEC-010").problems == []
    missing = _row(report, "EXEC-014")
    assert missing.test_status == "NO_BINDING"
    assert any("missing binding is a hard failure" in p for p in missing.problems)
    assert "EXEC-014" in report.unsatisfied
    assert report.stamp.is_green is False


@pytest.mark.conformance("VALD-002")
def test_vald_002_an_unknown_identifier_in_a_test_fails_the_check(tmp_path):
    """VALD-002: identifiers are permanent and centrally registered, not invented locally.

    A test that declares an identifier the registry has never heard of is claiming
    coverage that nobody can interpret, and it is how two repositories end up using one
    identifier for two different behaviours. The throwaway suite below declares one, and
    the checker refuses the whole run.

    The invented identifier is only ever written inside that generated file: the binding
    scanner reads names, docstrings and decorators, so spelling it here would make this
    very test declare it.
    """
    suite = _mini_suite(
        tmp_path,
        "unknown_identifier",
        '''
import pytest


@pytest.mark.conformance("EXEC-999")
def test_invented_identifier():
    assert True
''',
    )
    report = check(
        adapter=TradesimAdapter(contract=registry.CONTRACT_BRACKET_PORTFOLIO),
        test_paths=[suite],
        contract=registry.CONTRACT_BRACKET_PORTFOLIO,
        run_bound_tests=False,
    )

    assert report.ok is False
    assert getattr(report, "unknown_identifiers") == ["EXEC-999"]


@pytest.mark.conformance("VALD-003")
def test_vald_003_the_fixture_pack_is_content_hashed(tmp_path):
    """VALD-003: change one byte of one fixture and every stamp that quoted it is stale.

    The hash is what ties a reported number to the arbiter that graded the engine which
    produced it. Without it, "the engine passed conformance" is a claim about a pack that
    may since have been edited.
    """
    pack = tmp_path / "fixtures"
    pack.mkdir()
    (pack / "a.json").write_text('{"ids": ["EXEC-010"], "expect": {}}', encoding="utf-8")
    before = fixture_pack_hash(str(pack))

    (pack / "a.json").write_text('{"ids": ["EXEC-010"], "expect": {"x": 1}}', encoding="utf-8")
    after = fixture_pack_hash(str(pack))

    assert before != after
    assert len(before) == 64

    (pack / "b.json").write_text('{"ids": ["EXEC-011"], "expect": {}}', encoding="utf-8")
    assert fixture_pack_hash(str(pack)) != after, "adding a case changes the pack too"


@pytest.mark.conformance("VALD-004")
def test_vald_004_a_dirty_working_tree_stamps_unknown_dirty(monkeypatch):
    """VALD-004: a commit hash that does not describe the code that ran is worse than none.

    With uncommitted changes present the stamp records UNKNOWN_DIRTY, so a result can
    never be attributed to a commit whose contents differ from what produced it.
    """
    class _Result:
        def __init__(self, stdout: str) -> None:
            self.returncode = 0
            self.stdout = stdout

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "rev-parse" in cmd:
            return _Result("abc1234\n")
        return _Result(" M packages/tradesim/src/tradesim/engine.py\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert stamp_mod.git_commit() == UNKNOWN_DIRTY
    assert any("status" in c for c in calls), "the tree is actually inspected"

    def clean_run(cmd, **kwargs):
        return _Result("abc1234\n" if "rev-parse" in cmd else "")

    monkeypatch.setattr(subprocess, "run", clean_run)
    assert stamp_mod.git_commit() == "abc1234"


@pytest.mark.conformance("VALD-005")
def test_vald_005_a_skipped_bound_test_is_a_failure(tmp_path):
    """VALD-005: skipping is how a suite stays green while covering nothing.

    A skip on a bound conformance test means the identifier was not exercised, which is
    the same evidential position as having no test at all.
    """
    suite = _mini_suite(
        tmp_path,
        "skipped",
        '''
import pytest


@pytest.mark.conformance("EXEC-010")
@pytest.mark.skip(reason="temporarily disabled, which must not read as a pass")
def test_bound_but_skipped():
    assert True
''',
    )
    report = check(
        adapter=TradesimAdapter(contract=registry.CONTRACT_BRACKET_PORTFOLIO),
        test_paths=[suite],
        contract=registry.CONTRACT_BRACKET_PORTFOLIO,
        run_bound_tests=True,
    )

    row = _row(report, "EXEC-010")
    assert row.test_status == "SKIPPED"
    assert any("a skipped conformance test is a failure" in p for p in row.problems)
    assert "EXEC-010" in report.unsatisfied
    assert report.ok is False


@pytest.mark.conformance("VALD-005")
def test_vald_005_a_failing_bound_test_is_reported_against_its_identifier(tmp_path):
    """VALD-005: and an outright failure is attributed to the identifier it was bound to."""
    suite = _mini_suite(
        tmp_path,
        "failing",
        '''
import pytest


@pytest.mark.conformance("EXEC-011")
def test_bound_and_failing():
    assert 1 == 2
''',
    )
    report = check(
        adapter=TradesimAdapter(contract=registry.CONTRACT_BRACKET_PORTFOLIO),
        test_paths=[suite],
        contract=registry.CONTRACT_BRACKET_PORTFOLIO,
        run_bound_tests=True,
    )

    row = _row(report, "EXEC-011")
    assert row.test_status == "FAILED"
    assert any("FAILED" in p for p in row.problems)


@pytest.mark.conformance("VALD-006")
def test_vald_006_run_id_is_accepted_and_propagated(
    instrument, costs, margin, sizing, sim
):
    """VALD-006: every public entry point takes a run identifier and returns it.

    Without it a stored result cannot be tied back to the configuration, the data slice
    and the code that produced it, and reproducing a number becomes an archaeology
    exercise.
    """
    from conftest import bars

    single = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.5, 111.0, 100.0, 110.0]],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
        run_id="exp-2026-07-25-a",
    )
    assert single.run_id == "exp-2026-07-25-a"

    portfolio = simulate_portfolio(
        streams=[
            SymbolStream(
                symbol="TESTUSDT",
                instrument=instrument,
                bars=bars([SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.5, 111.0, 100.0, 110.0]]),
                signals=(long_signal(),),
            )
        ],
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
        run_id="exp-2026-07-25-b",
        attach_stamp=False,
    )
    assert portfolio.run_id == "exp-2026-07-25-b"


@pytest.mark.conformance("VALD-006")
def test_vald_006_the_config_digest_travels_with_the_result(
    instrument, costs, margin, sizing, sim
):
    """VALD-006: two runs that differ only in configuration have different digests.

    The run identifier says which run it was; the digest says what it was configured to
    do. A result carrying both can be reproduced without trusting anyone's notes.
    """
    from dataclasses import replace

    rows = [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.5, 111.0, 100.0, 110.0]]
    kw = dict(instrument=instrument, margin=margin, sizing=sizing, sim=sim)

    a = run(rows, [long_signal()], costs=costs, run_id="x", **kw)
    b = run(rows, [long_signal()], costs=costs, run_id="y", **kw)
    c = run(rows, [long_signal()], costs=replace(costs, taker_rate=0.002), run_id="x", **kw)

    assert a.config_digest == b.config_digest
    assert a.config_digest != c.config_digest
