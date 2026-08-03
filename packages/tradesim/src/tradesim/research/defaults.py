"""Research defaults for strategy backtests on tradesim.

Frozen wallet: **10_000 USDT**. Chosen so min-exchange size at **1× leverage** never
fails margin on BTC/ETH (0.001 BTC ≈ $100+ notional; default
``max_margin_utilisation=0.60`` would reject a $100 wallet). Absolute dollar PnL and
**return on invested notional** are the headline money metrics — not wallet %.
"""

from __future__ import annotations

from ..contracts import (
    CostConfig,
    EntryOrder,
    InstrumentSpec,
    Liquidity,
    MarginConfig,
    MarginMode,
    SimConfig,
    SizingConfig,
    SizingMode,
    default_role_liquidity,
)

# Wallet every research backtest starts with unless the caller overrides.
# Must stay large enough that 1× + venue min qty is never margin-bound for majors.
RESEARCH_STARTING_EQUITY_USDT = 10_000.0

# Bybit non-VIP (verify on account fee page).
RESEARCH_TAKER_RATE = 0.00055
RESEARCH_MAKER_RATE = 0.0002
# Entry slip only for *market* entries (TP/SL are limits with no exit slip).
RESEARCH_ENTRY_SLIPPAGE = 0.0005  # 0.05% default; freeze per project if measured

# Canonical research artifacts (override with TRADING_DATA_ROOT).
from tradesim.paths import tradesim_reports_dir, tradesim_store_path

RESEARCH_STORE_PATH = str(tradesim_store_path())
RESEARCH_REPORTS_DIR = str(tradesim_reports_dir())


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


def research_costs(
    *,
    entry_slippage: float = RESEARCH_ENTRY_SLIPPAGE,
    entry_liquidity: Liquidity = Liquidity.TAKER,
    take_profit_liquidity: Liquidity = Liquidity.TAKER,
    stop_liquidity: Liquidity = Liquidity.TAKER,
    **kw,
) -> CostConfig:
    """Default all-taker schedule. Maker rates are real Bybit non-VIP values.

    Use :func:`research_limit_entry_costs` (or ``entry_liquidity=Liquidity.MAKER`` plus
    ``SimConfig.entry_order=EntryOrder.LIMIT``) when the live bot posts a resting entry.
    """
    roles = kw.pop("role_liquidity", None)
    if roles is None:
        roles = default_role_liquidity(
            entry=entry_liquidity,
            take_profit=take_profit_liquidity,
            stop=stop_liquidity,
        )
    return CostConfig(
        taker_rate=RESEARCH_TAKER_RATE,
        maker_rate=RESEARCH_MAKER_RATE,
        entry_slippage=float(entry_slippage),
        market_exit_slippage=0.0,  # TP/SL limits; timeouts still market but slip 0 by default
        role_liquidity=roles,
        **kw,
    )


def research_limit_entry_costs(
    *,
    take_profit_liquidity: Liquidity = Liquidity.TAKER,
    stop_liquidity: Liquidity = Liquidity.TAKER,
    **kw,
) -> CostConfig:
    """Maker entry, **zero** entry slippage; exits stay taker unless overridden.

    Pair with :func:`research_sim_limit_entry` (or ``Signal.entry_order="limit"``).
    Label results as assuming proven Post-Only / resting fills — do not use this to
    rescue a failing all-taker baseline without maker evidence.
    """
    return research_costs(
        entry_slippage=0.0,
        entry_liquidity=Liquidity.MAKER,
        take_profit_liquidity=take_profit_liquidity,
        stop_liquidity=stop_liquidity,
        **kw,
    )


def research_sim_limit_entry(
    *, starting_equity: float = RESEARCH_STARTING_EQUITY_USDT, **kw
) -> SimConfig:
    """``entry_order=LIMIT``: fill at limit when touched, maker fee, no entry slip."""
    return research_sim(
        starting_equity=float(starting_equity),
        entry_order=EntryOrder.LIMIT,
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
