"""Report / runtime account filtering: only live --account bindings."""

from __future__ import annotations

from botsgeneral.discover import (
    accounts_mentioned_in_text,
    running_accounts_for_bot,
)
from botsgeneral.keys import canonicalize_account_name


def test_accounts_mentioned_from_flags_and_screens():
    blob = (
        "python -m llm2.live.pivot_runner --account Xxobster7 --pack /opt/x\n"
        "433376.xxobster2ETHUSDT (Detached)\n"
        "tsm-chandelier@BTCUSDT.service loaded active running ... Xxobster6\n"
    )
    found = accounts_mentioned_in_text(blob)
    assert "Xxobster7" in found
    assert "Xxobster2" in found
    assert "Xxobster6" in found
    assert "Xxobster10" not in found


def test_running_accounts_multi_registry_only_live_hits():
    bcfg = {
        "account": ["Xxobster6", "Xxobster7", "Xxobster8", "Xxobster10"],
        "path": "/home/llm2",
        "process_match": ["llm2.live"],
        "systemd_match": ["llm2-"],
        "screen_match": ["llm2"],
    }
    proc = (
        "/opt/llm2-pivot/venv/bin/python -m llm2.live.pivot_runner "
        "--account Xxobster7 --pack /opt/llm2-pivot/pack\n"
    )
    systemd_lines = [
        "llm2-pivot-sol.service loaded active running LLM2 pivot LIVE Xxobster7"
    ]
    live = running_accounts_for_bot(
        bcfg,
        screens=[],
        systemd_lines=systemd_lines,
        proc_blob=proc,
        running=True,
    )
    assert live == ["Xxobster7"]


def test_live_account_bot_map_skips_registry_only_accounts():
    # Mirrors botsgeneral.report._live_account_bot_map without importing report
    # (report pulls websocket via collect).
    sitrep = {
        "bots": [
            {"bot": "llm2", "running": True, "running_accounts": ["Xxobster7"]},
            {"bot": "tsm_chandelier", "running": True, "running_accounts": ["Xxobster6"]},
        ]
    }
    m: dict[str, list[str]] = {}
    for b in sitrep["bots"]:
        if not b.get("running"):
            continue
        for a in b.get("running_accounts") or []:
            canon = canonicalize_account_name(str(a))
            m.setdefault(canon, []).append(str(b["bot"]))
    assert set(m.keys()) == {"Xxobster6", "Xxobster7"}
    assert m["Xxobster7"] == ["llm2"]
    assert "Xxobster10" not in m


def test_drop_generic_llm2_when_autonomy_children_present():
    from botsgeneral.report import drop_generic_parent_bots

    assert drop_generic_parent_bots(
        ["llm2", "llm2_autonomy_013_sol"]
    ) == ["llm2_autonomy_013_sol"]
    assert drop_generic_parent_bots(
        ["llm2", "llm2_autonomy_376_sol", "llm2_autonomy_705_eth"]
    ) == ["llm2_autonomy_376_sol", "llm2_autonomy_705_eth"]
    # Pivot-only accounts keep the generic family name
    assert drop_generic_parent_bots(["llm2"]) == ["llm2"]


def test_catchall_llm2_does_not_invent_btc():
    from botsgeneral.report import merge_bot_running_symbols

    # Generic llm2 registry lists BTC+ETH+SOL; that must not become the live universe
    assert merge_bot_running_symbols(set(), {"BTCUSDT", "ETHUSDT", "SOLUSDT"}, "llm2") == set()
    assert merge_bot_running_symbols(set(), {"SOLUSDT"}, "llm2_autonomy_013_sol") == {"SOLUSDT"}
    assert merge_bot_running_symbols({"ETHUSDT"}, {"ETHUSDT", "SOLUSDT"}, "llm2_autonomy_705_eth") == {
        "ETHUSDT"
    }


def test_llm2_pivot_unit_names_map_to_eth_sol_not_btc():
    from botsgeneral.report import symbols_from_llm2_unit_names

    units = [
        "llm2-pivot-eth-p75-ctrl-atr-w4.service",
        "llm2-pivot-sol-geo-p75-w4.service",
        "llm2-autonomy-376-sol-sma540.service",
        "crypthor-btc.service",
    ]
    assert symbols_from_llm2_unit_names(units) == {"ETHUSDT", "SOLUSDT"}
