"""Research defaults for strategy backtests on tradesim.

Frozen wallet: **10_000 USDT**. Chosen so min-exchange size at **1× leverage** never
fails margin on BTC/ETH (0.001 BTC ≈ $100+ notional; default
``max_margin_utilisation=0.60`` would reject a $100 wallet). Absolute dollar PnL and
**return on invested notional** are the headline money metrics — not wallet %.
"""

from __future__ import annotations

from ..contracts import (
    CostConfig,
    InstrumentSpec,
    MarginConfig,
    MarginMode,
    SimConfig,
    SizingConfig,
    SizingMode,
)

# Wallet every research backtest starts with unless the caller overrides.
# Must stay large enough that 1× + venue min qty is never margin-bound for majors.
RESEARCH_STARTING_EQUITY_USDT = 10_000.0

# Bybit non-VIP taker; entry slip only (TP/SL are limits with no exit slip).
RESEARCH_TAKER_RATE = 0.00055
RESEARCH_ENTRY_SLIPPAGE = 0.0005  # 0.05% default; freeze per project if measured

# Canonical research artifacts (Windows research machine).
RESEARCH_STORE_PATH = r"D:\projectsdata\backtests\tradesim_runs.sqlite"
RESEARCH_REPORTS_DIR = r"D:\projectsdata\backtests\reports"


def research_starting_equity(
    *,
    price: float,
    qty: float | None = None,
    instrument: InstrumentSpec | None = None,
    leverage: float = 1.0,
    utilisation: float = 0.60,
    safety: float = 2.0,
) -> float:
    """Smallest wallet that can open ``qty`` (or venue min) at ``leverage`` without a skip.

    Uses ``margin ≈ notional / leverage`` and the research utilisation cap. Result is
    never below ``RESEARCH_STARTING_EQUITY_USDT``.
    """
    if qty is None:
        if instrument is None:
            qty = 1.0
        else:
            # max(min_qty, min_notional/price)
            q_min = float(instrument.min_qty)
            if instrument.min_notional > 0 and price > 0:
                q_min = max(q_min, float(instrument.min_notional) / float(price))
            qty = q_min
    notional = abs(float(qty) * float(price))
    lev = max(float(leverage), 1e-9)
    util = min(max(float(utilisation), 1e-6), 1.0)
    need = (notional / lev) / util * float(safety)
    return float(max(RESEARCH_STARTING_EQUITY_USDT, need))


def research_sim(*, starting_equity: float = RESEARCH_STARTING_EQUITY_USDT, **kw) -> SimConfig:
    return SimConfig(
        starting_equity=float(starting_equity),
        take_profit_is_limit=True,
        stop_is_stop_market=False,
        allow_trading_after_ruin=False,
        **kw,
    )


def research_costs(*, entry_slippage: float = RESEARCH_ENTRY_SLIPPAGE, **kw) -> CostConfig:
    return CostConfig(
        taker_rate=RESEARCH_TAKER_RATE,
        maker_rate=RESEARCH_TAKER_RATE,  # unused when every role is taker
        entry_slippage=float(entry_slippage),
        market_exit_slippage=0.0,  # TP/SL limits; timeouts still market but slip 0 by default
        **kw,
    )


def research_sizing() -> SizingConfig:
    """Smallest venue-legal quantity. Strategies should leave ``Signal.qty`` unset."""
    return SizingConfig(mode=SizingMode.MIN_EXCHANGE)


def research_margin(*, leverage: float = 1.0) -> MarginConfig:
    return MarginConfig(mode=MarginMode.ISOLATED, leverage=float(leverage))


def research_instrument(symbol: str, **kw):
    """Load Bybit USDT-perp ``InstrumentSpec`` (min qty / step / notional) for sizing.

    Pulls from the local SQLite cache, refreshing via the Xxobster_local API account
    when missing or stale. See ``python -m tradesim.venue refresh --from-registry``.
    """
    from ..venue import InstrumentCache

    return InstrumentCache().instrument_spec(symbol, **kw)
