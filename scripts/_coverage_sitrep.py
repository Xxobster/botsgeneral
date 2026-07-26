"""One-shot coverage sitrep for 5m/15m/1h/4h across research warehouse."""

from __future__ import annotations

from botsgeneral.research_candles.db import ResearchCandleDB
from botsgeneral.research_candles.universe import BINANCE_FUTURES_SYMBOLS, DUKASCOPY, YAHOO

WANTED = ("5m", "15m", "1h", "4h")


def matrix(cov, source: str, expected: list[str]) -> None:
    sub = cov[cov["source"] == source]
    print(f"\n=== {source} ===")
    complete: list[str] = []
    incomplete: dict[str, list[str]] = {}
    absent: list[str] = []
    for sym in expected:
        tfs = sorted(sub.loc[sub["symbol"] == sym, "timeframe"].unique().tolist())
        missing = [t for t in WANTED if t not in tfs]
        if not tfs:
            absent.append(sym)
        elif missing:
            incomplete[sym] = missing
            bars = {
                str(r.timeframe): int(r.bars)
                for r in sub.loc[sub["symbol"] == sym].itertuples()
            }
            print(f"  PARTIAL {sym}: have {tfs} bars={bars} missing={missing}")
        else:
            complete.append(sym)
            bars = {
                str(r.timeframe): int(r.bars)
                for r in sub.loc[sub["symbol"] == sym].itertuples()
            }
            print(f"  OK {sym}: {bars}")
    print(f"  complete={len(complete)} incomplete={len(incomplete)} absent={len(absent)}")
    if absent:
        print(f"  absent: {absent}")


def main() -> None:
    db = ResearchCandleDB()
    cov = db.coverage()
    db.close()
    cov = cov[cov["timeframe"].isin(WANTED)].copy()
    print("Wanted TFs:", ",".join(WANTED))
    print("Sources in DB for these TFs:", sorted(cov["source"].unique().tolist()))
    matrix(cov, "binance", list(BINANCE_FUTURES_SYMBOLS))
    matrix(cov, "binance_mark", list(BINANCE_FUTURES_SYMBOLS))
    matrix(cov, "dukascopy", [d.symbol for d in DUKASCOPY])
    matrix(cov, "yahoo", [y.symbol for y in YAHOO])


if __name__ == "__main__":
    main()
