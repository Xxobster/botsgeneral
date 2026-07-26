from __future__ import annotations

from botsgeneral.report import _CLOSED_PNL_MAX_WINDOW_MS, fetch_closed_pnl


def test_closed_pnl_chunks_over_7_days(monkeypatch):
    calls: list[tuple[int, int]] = []

    def fake_window(api_key, api_secret, start_ms, end_ms, symbol=None):
        calls.append((start_ms, end_ms))
        return [
            {
                "orderId": f"{start_ms}-{end_ms}",
                "updatedTime": str(end_ms),
                "symbol": "ETHUSDT",
                "closedPnl": "1.5",
                "qty": "0.01",
            }
        ]

    monkeypatch.setattr("botsgeneral.report._fetch_closed_pnl_window", fake_window)
    monkeypatch.setattr("botsgeneral.report.time.time", lambda: 1_800_000_000.0)
    monkeypatch.setattr("botsgeneral.report.time.sleep", lambda *_a, **_k: None)

    # ~16 days before "now"
    start = int(1_800_000_000.0 * 1000) - 16 * 24 * 60 * 60 * 1000
    rows = fetch_closed_pnl("k", "s", start, symbol="ETHUSDT")
    assert len(calls) >= 3
    assert all((e - s) <= _CLOSED_PNL_MAX_WINDOW_MS for s, e in calls)
    assert len(rows) == len(calls)
