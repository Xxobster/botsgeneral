# Decisions

## 2026-07-13 — Shared candle architecture

- **One collector per VPS** (not central sync, not Windows-hosted feed).
- **Keep exchange per bot:** Bybit for crypthor2/karmaa_mp/divergences/W.I.P live; **news** and **xgb** use own Binance pulls (`serve_candles: false`).
- **Auto-discovery** from each bot’s config + process/screen/systemd scan every 60s — do not maintain a manual candle list for new coins.
- **Canonical SQLite** `/var/lib/botsgeneral/shared_candles.db` with `exchange,symbol,timeframe,ts_ms` PK.
- **Bybit public WS** for live confirmed klines (multi-topic one connection); Binance REST only for bots that still opt into shared Binance pairs (none on 94.156 after news opt-out).
- **Xxobster** keys for PnL/ops only when needed; market klines are public.
- Trading bots keep **their own** Bybit accounts for orders after migration.
- Standing trading rules live in `RULES.md` (shared across the stack).

## 2026-07-13 — news discarded shared candles

- **news** set `serve_candles: false`; live restored own Binance REST into `/home/crypto_alpha` SQLite (needs taker fields for vol_imb; matches backtest).

## Non-goals for botsgeneral

- No strategy optimization or ML training in this repo.
- No placing orders.
- No replacing xgb **or news** candle fetch until explicitly requested.
