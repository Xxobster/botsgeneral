# TODO

## Now

- [ ] User runs `AGENT_PROMPTS.md` migrations on: crypthor2, karmaa_mp, divergences, news, W.I.P
- [ ] Verify each migrated bot: no local kline WS/REST write; reads `SHARED_CANDLES_DB`
- [ ] Free disk on both VPS (<80% target)
- [ ] Confirm keys file present on 94 and `pnl` works there

## Later

- [ ] Optional Binance WS for news pairs (today REST poll; WS preferred per RULES)
- [ ] Richer sitrep: per-bot trade-log summary when bots expose shared trade DBs
- [ ] Alerting when candle lag stale or bot DOWN
- [ ] W.I.P GitHub remote if missing

## Won’t do unless asked

- Migrate xgb off self-fetch
- Run strategy backtests inside botsgeneral
