"""HMI cache, metrics, hub merge, strategy catalog."""

from __future__ import annotations

import json
import math
from pathlib import Path

from botsgeneral.discover import running_accounts_for_bot
from botsgeneral.hmi.cache import ClosedPnlCache
from botsgeneral.hmi.hub import _merge_accounts, assemble_fleet, pair_winners_from_snaps
from botsgeneral.hmi.jsonutil import jsonable
from botsgeneral.hmi.strategy import load_catalog, summaries_for_bots
from botsgeneral.metrics import days_active, equity_curve_from_closed, trade_metrics
from botsgeneral.report import normalize_closed_trades


def test_closed_pnl_cache_incremental(tmp_path, monkeypatch):
    db = tmp_path / "c.sqlite"
    cache = ClosedPnlCache(db)
    calls: list[tuple[int, int]] = []

    def fetch(a, b):
        calls.append((a, b))
        return [
            {
                "orderId": "1",
                "updatedTime": "1010",
                "symbol": "ETHUSDT",
                "closedPnl": "1.25",
                "qty": "0.01",
            }
        ]

    monkeypatch.setattr("botsgeneral.hmi.cache.time.time", lambda: 1_800_000.5)
    rows = cache.get_or_fetch("Xxobster7", 1_000, fetch)
    assert len(rows) == 1
    assert len(calls) == 1
    rows2 = cache.get_or_fetch("Xxobster7", 1_000, fetch)
    assert len(rows2) == 1
    assert calls[-1][0] > 1_000
    cache.close()


def test_jsonable_inf():
    out = jsonable({"pf": math.inf, "wr": 0.5, "bad": math.nan})
    assert out["pf"] == "inf"
    assert out["wr"] == 0.5
    assert out["bad"] is None
    json.dumps(out)


def test_equity_curve_and_days():
    closed = [
        {"updatedTime": "100", "closedPnl": "1"},
        {"updatedTime": "200", "closedPnl": "-0.4"},
        {"updatedTime": "300", "closedPnl": "2"},
    ]
    c = equity_curve_from_closed(closed)
    assert c["n"] == 3
    assert abs(c["final"] - 2.6) < 1e-9
    assert c["points"][-1]["cum"] == c["final"]
    assert days_active(0, now_ms=86_400_000) == 1.0
    m = trade_metrics(closed)
    assert m["n_trades"] == 3
    assert m["n_legs"] == 3


def test_scale_out_legs_count_as_one_roundtrip():
    from botsgeneral.metrics import group_closed_legs_to_roundtrips

    legs = [
        {
            "orderId": "a",
            "symbol": "SOLUSDT",
            "side": "Sell",
            "qty": "0.1",
            "closedSize": "0.1",
            "avgEntryPrice": "103.74",
            "avgExitPrice": "104.63",
            "closedPnl": "0.0848",
            "updatedTime": "1000",
            "createdTime": "900",
        },
        {
            "orderId": "b",
            "symbol": "SOLUSDT",
            "side": "Sell",
            "qty": "0.1",
            "closedSize": "0.1",
            "avgEntryPrice": "103.74",
            "avgExitPrice": "104.63",
            "closedPnl": "0.0848",
            "updatedTime": "1001",
            "createdTime": "901",
        },
        {
            "orderId": "c",
            "symbol": "SOLUSDT",
            "side": "Sell",
            "qty": "0.1",
            "closedSize": "0.1",
            "avgEntryPrice": "103.74",
            "avgExitPrice": "104.63",
            "closedPnl": "0.0848",
            "updatedTime": "1002",
            "createdTime": "902",
        },
    ]
    rt = group_closed_legs_to_roundtrips(legs)
    assert len(rt) == 1
    assert rt[0]["leg_count"] == 3
    assert abs(float(rt[0]["qty"]) - 0.3) < 1e-9
    m = trade_metrics(legs)
    assert m["n_trades"] == 1
    assert m["n_legs"] == 3
    assert m["wins"] == 1


def test_soft_match_partial_scale_exit_qty(tmp_path):
    from botsgeneral.hmi.decide_enrich import enrich_trades_and_positions

    root = tmp_path / "llm2-ema-sol-1h"
    state = root / "state"
    state.mkdir(parents=True)
    db = state / "ema_live_state.sqlite"
    import sqlite3

    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE pivot_decisions (bar_ts_ms INTEGER PRIMARY KEY, payload_json TEXT, created_utc TEXT)"
    )
    payload = {
        "action": "ENTER_LIMIT",
        "symbol": "SOLUSDT",
        "side": "Buy",
        "qty": 0.3,
        "avg_price": 103.74,
        "confidence_pct": 12.6,
        "actual_risk_pct": 1.48,
        "sizing_mode": "CONFIDENCE_RISK",
        "order_result": {
            "ok": True,
            "filled": True,
            "order_id": "entry-sol",
            "stage": "filled_tpsl",
            "tpsl": {
                "tp": [
                    {"result": {"orderId": "tp1"}},
                    {"result": {"orderId": "tp2"}},
                ],
                "sl": {"result": {"orderId": "sl1"}},
            },
        },
    }
    con.execute(
        "INSERT INTO pivot_decisions(bar_ts_ms, payload_json, created_utc) VALUES (?,?,?)",
        (1_000_000, json.dumps(payload), "2026-01-01T00:00:00Z"),
    )
    con.commit()
    con.close()
    registry = {"bots": {"llm2_ema_sol_1h": {"path": str(root)}}}
    trades = [
        {
            "order_id": "ghost",
            "symbol": "SOLUSDT",
            "side": "Sell",
            "qty": 0.1,
            "entry": 103.74,
            "created_ms": 1_000_000 + 60_000,
            "pnl": "0.08",
        }
    ]
    enrich_trades_and_positions(
        trades=trades, positions=None, registry=registry, bot_ids=["llm2_ema_sol_1h"]
    )
    assert trades[0]["confidence_pct"] == 12.6
    assert trades[0]["display_risk_pct"] == 1.48


def test_normalize_trades_newest_first():
    rows = normalize_closed_trades(
        [
            {"orderId": "a", "symbol": "BTCUSDT", "updatedTime": "10", "avgEntryPrice": "1", "closedPnl": "0.1"},
            {"orderId": "b", "symbol": "ETHUSDT", "updatedTime": "20", "avgEntryPrice": "2", "closedPnl": "-0.2"},
        ]
    )
    assert rows[0]["order_id"] == "b"
    assert rows[0]["entry"] == "2"


def test_running_accounts_prefers_live_flag_over_single_registry():
    bcfg = {
        "account": "Xxobster7",
        "path": "/opt/llm2-pivot-sol-geo-p75-w4",
        "process_match": ["pivot_runner"],
        "systemd_match": ["llm2-pivot-sol-geo-p75-w4"],
        "screen_match": [],
    }
    proc = (
        "/opt/llm2-pivot-sol-geo-p75-w4/venv/bin/python -m llm2.live.pivot_runner "
        "--account Xxobster8 --pack /opt/llm2-pivot-sol-geo-p75-w4/pack\n"
    )
    live = running_accounts_for_bot(
        bcfg, screens=[], systemd_lines=[], proc_blob=proc, running=True
    )
    assert live == ["Xxobster8"]


def test_merge_same_account_across_vps():
    snaps = [
        {
            "ok": True,
            "_ok": True,
            "vps": "94.156.189.76",
            "alias": "ln1",
            "host": {"cpu": {"cpu_pct": 10}},
            "accounts": [
                {
                    "account": "Xxobster6",
                    "bot_ids": ["tsm_chandelier"],
                    "bots": ["tsm_chandelier"],
                    "total_equity": 100.0,
                    "total_perp_upl": 1.0,
                    "closed_all": {"realized_pnl": 2.0, "n_trades": 2},
                    "trades": [
                        {"order_id": "1", "updated_ms": 10, "symbol": "BTCUSDT", "pnl": "1"},
                    ],
                }
            ],
        },
        {
            "ok": True,
            "_ok": True,
            "vps": "212.73.150.178",
            "alias": "ln2",
            "host": {"cpu": {"cpu_pct": 20}},
            "accounts": [
                {
                    "account": "Xxobster6",
                    "bot_ids": ["news"],
                    "bots": ["news"],
                    "total_equity": 100.0,
                    "total_perp_upl": 1.0,
                    "closed_all": {"realized_pnl": 2.0, "n_trades": 2},
                    "trades": [
                        {"order_id": "1", "updated_ms": 10, "symbol": "BTCUSDT", "pnl": "1"},
                        {"order_id": "2", "updated_ms": 20, "symbol": "ETHUSDT", "pnl": "0.5"},
                    ],
                }
            ],
        },
    ]
    merged = _merge_accounts(snaps)
    assert len(merged) == 1
    row = merged[0]
    assert set(row["bot_ids"]) == {"tsm_chandelier", "news"}
    assert {t["order_id"] for t in row["trades"]} == {"1", "2"}
    fleet = assemble_fleet(snaps)
    assert fleet["totals"]["n_accounts"] == 1
    assert len(fleet["hosts"]) == 2


def test_assemble_fleet_hides_sm_and_ln3():
    snaps = [
        {
            "ok": True,
            "_ok": True,
            "_agent_id": "ln1",
            "alias": "ln1",
            "vps": "94.156.189.76",
            "host": {"alias": "ln1"},
            "accounts": [
                {
                    "account": "Xxobster6",
                    "bot_ids": ["tsm_vpa"],
                    "bots": ["tsm_vpa"],
                    "total_equity": 50.0,
                    "closed_all": {"realized_pnl": 1.0, "n_trades": 1},
                    "per_coin": [
                        {
                            "symbol": "VETUSDT",
                            "n_trades": 4,
                            "realized_pnl": 1.0,
                            "profit_factor": 1.5,
                            "days_active": 10,
                        }
                    ],
                }
            ],
        },
        {
            "ok": True,
            "_ok": True,
            "_agent_id": "ln3",
            "alias": "ln3",
            "vps": "185.203.119.52",
            "host": {"alias": "ln3"},
            "accounts": [
                {
                    "account": "Xxobster9",
                    "bot_ids": ["llm2"],
                    "bots": ["llm2"],
                    "total_equity": 80.0,
                    "closed_all": {"realized_pnl": 9.0, "n_trades": 20},
                    "per_coin": [{"symbol": "SOLUSDT", "n_trades": 20, "profit_factor": 3.0, "days_active": 5}],
                }
            ],
        },
        {
            "ok": True,
            "_ok": True,
            "_agent_id": "sm",
            "alias": "sm",
            "vps": "212.73.150.149",
            "host": {"alias": "sm"},
            "accounts": [
                {
                    "account": "Xxobster1",
                    "bot_ids": ["news"],
                    "bots": ["news"],
                    "total_equity": 10.0,
                    "closed_all": {"realized_pnl": 2.0, "n_trades": 3},
                }
            ],
        },
    ]
    fleet = assemble_fleet(snaps)
    aliases = {h.get("alias") for h in fleet["hosts"]}
    accounts = {a.get("account") for a in fleet["accounts"]}
    assert aliases == {"ln1"}
    assert accounts == {"Xxobster6"}
    assert fleet["totals"]["n_accounts"] == 1
    winners = fleet["pair_winners"]
    assert len(winners) == 1
    assert winners[0]["pair"] == "VETUSDT"
    assert winners[0]["bot"] == "tsm_vpa"


def test_pair_winners_sorted_by_profit_factor():
    snaps = [
        {
            "ok": True,
            "_ok": True,
            "alias": "ln2",
            "vps": "212.73.150.178",
            "accounts": [
                {
                    "account": "Xxobster4",
                    "bot_ids": ["crypthor2", "karmaa_mp"],
                    "bots": ["crypthor2", "karmaa_mp"],
                    "bot_symbols": {"crypthor2": ["BTCUSDT"], "karmaa_mp": ["ETHUSDT"]},
                    "days_active": 20,
                    "total_equity": 1234.56,
                    "per_coin": [
                        {
                            "symbol": "BTCUSDT",
                            "n_trades": 10,
                            "realized_pnl": 5.0,
                            "profit_factor": 1.2,
                            "recovery_factor": 0.8,
                            "winrate": 0.5,
                            "days_active": 10,
                        },
                        {
                            "symbol": "ETHUSDT",
                            "n_trades": 8,
                            "realized_pnl": 12.0,
                            "profit_factor": "inf",
                            "recovery_factor": "inf",
                            "winrate": 1.0,
                            "days_active": 4,
                        },
                    ],
                }
            ],
        }
    ]
    rows = pair_winners_from_snaps(snaps)
    assert [r["pair"] for r in rows] == ["ETHUSDT", "BTCUSDT"]
    assert rows[0]["bot"] == "karmaa_mp"
    assert rows[0]["trades_per_day"] == 2.0
    assert rows[1]["trades_per_day"] == 1.0
    assert rows[1]["bot"] == "crypthor2"
    assert rows[0]["total_equity"] == 1234.56
    assert rows[1]["total_equity"] == 1234.56


def test_decide_enrich_matches_tp_order_id(tmp_path):
    from botsgeneral.hmi.decide_enrich import enrich_trades_and_positions

    root = tmp_path / "llm2-ema-sol-1h"
    state = root / "state"
    state.mkdir(parents=True)
    db = state / "ema_live_state.sqlite"
    import sqlite3

    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE pivot_decisions (bar_ts_ms INTEGER PRIMARY KEY, payload_json TEXT, created_utc TEXT)"
    )
    payload = {
        "action": "ENTER_LIMIT",
        "symbol": "SOLUSDT",
        "side": "Buy",
        "qty": 1.1,
        "confidence_pct": 70.0,
        "risk_pct": 4.5,
        "actual_risk_pct": 4.2,
        "sizing_mode": "CONFIDENCE_RISK",
        "order_result": {
            "ok": True,
            "filled": True,
            "order_id": "entry-aaa",
            "stage": "filled_tpsl",
            "tpsl": {
                "tp": {"result": {"orderId": "tp-bbb"}},
                "sl": {"result": {"orderId": "sl-ccc"}},
            },
        },
    }
    con.execute(
        "INSERT INTO pivot_decisions(bar_ts_ms, payload_json, created_utc) VALUES (?,?,?)",
        (1_000, json.dumps(payload), "2026-01-01T00:00:00Z"),
    )
    con.commit()
    con.close()
    registry = {"bots": {"llm2_ema_sol_1h": {"path": str(root)}}}
    trades = [
        {"order_id": "tp-bbb", "symbol": "SOLUSDT", "side": "Sell", "qty": 1.1, "pnl": "0.5"},
        {"order_id": "other", "symbol": "BTCUSDT", "side": "Buy", "qty": 0.01, "pnl": "1"},
    ]
    positions = [{"symbol": "SOLUSDT", "side": "Buy", "size": 1.1, "unrealisedPnl": 0.1}]
    enrich_trades_and_positions(
        trades=trades, positions=positions, registry=registry, bot_ids=["llm2_ema_sol_1h"]
    )
    assert trades[0]["confidence_pct"] == 70.0
    assert trades[0]["display_risk_pct"] == 4.2
    assert "confidence_pct" not in trades[1]
    assert positions[0]["confidence_pct"] == 70.0


def test_strategy_catalog_has_live_units():
    cat = load_catalog()
    assert "llm2_hilbert_sol_1h" in (cat.get("bots") or {})
    rows = summaries_for_bots(["llm2_hilbert_sol_1h", "tsm_vpa"], {"bots": {}})
    assert rows[0]["bot"] == "llm2_hilbert_sol_1h"
    assert "Hilbert" in (rows[0]["title"] + rows[0]["summary"])
    assert rows[1]["family"] == "tsm_vpa"
