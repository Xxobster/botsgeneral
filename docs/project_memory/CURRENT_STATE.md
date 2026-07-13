# Current State

**Last updated:** 2026-07-13 (news left shared candles)

## Phase

Collectors live for bots that opted in. **news** reverted to own Binance REST (`serve_candles: false`, like xgb).

### Architecture (confirmed)

**botsgeneral** writes shared OHLCV for migrated bots. Each trading bot that opted in **reads** that DB. **news** and **xgb** keep independent Binance pulls.

### Resume

1. news: no longer a candle consumer — collector should stop binance BTCUSDT 4h for news after registry reload
2. Keep migrating remaining bots via AGENT_PROMPTS.md (except news/xgb)

