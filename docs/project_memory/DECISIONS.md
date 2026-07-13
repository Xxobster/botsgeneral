# Decisions

## 2026-07-13 — Shared candle architecture

- **One collector per VPS** (not central sync, not Windows-hosted feed).
- **Keep exchange per bot:** Bybit for crypthor2/karmaa_mp/divergences/W.I.P live; Binance OHLCV for news; **xgb unchanged** (own Binance pull).
- **Auto-discovery** from each bot’s config + process/screen/systemd scan every 60s — do not maintain a manual candle list for new coins.
- **Canonical SQLite** `/var/lib/botsgeneral/shared_candles.db` with `exchange,symbol,timeframe,ts_ms` PK.
- **Bybit public WS** for live confirmed klines (multi-topic one connection); Binance REST poll for news pairs.
- **Xxobster** keys for PnL/ops only when needed; market klines are public.
- Trading bots keep **their own** Bybit accounts for orders after migration.
- Standing trading rules live in `RULES.md` (shared across the stack).

## Non-goals for botsgeneral

- No strategy optimization or ML training in this repo.
- No placing orders.
- No replacing xgb candle fetch until explicitly requested.
