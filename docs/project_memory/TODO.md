# TODO

## tradesim Phase 3 — migration, one repository per session

Each migration is complete only when the parity diff is explained line by line, not merely
small. An unexplained difference is a defect in one of the two engines and the point of the
exercise is to find out which.

- [ ] **TSM-VPA** — replace `vpa.engine.run_backtest` with tradesim; parity diff on a real
      campaign; explain every difference against a named identifier
- [ ] **xgb** — replace `utils.audit_v4.execution_sim`; expect fee-model and same-bar
      funding differences
- [ ] **LLM1** — replace `simulate_path_exits`; the largest change, because it must move
      from return units into quantity space
- [ ] After each migration, re-run `tradesim-conformance` in that repository and update
      `ENGINE_CONFORMANCE_BASELINE.md`
- [ ] Commit `packages/tradesim` so the stamp stops reading `UNKNOWN_DIRTY`
- [ ] Add LIVE-001..004 (live-versus-backtest reconciliation) to the registry's required
      set once a bot is running on tradesim; they are registered but not yet required

## Now

- [ ] Finish / verify first full research candle download → `D:\projectsdata\candles\coverage.csv`
- [ ] Export TradingView CRYPTOCAP:BTC.D (1h/4h/1d) into `D:\projectsdata\candles\imports\btcd\`
- [ ] Point local research scripts at `ResearchCandleDB` instead of per-project re-downloads
- [ ] User runs `AGENT_PROMPTS.md` migrations on: crypthor2, karmaa_mp, divergences, news, W.I.P
- [ ] Verify each migrated bot: no local kline WS/REST write; reads `SHARED_CANDLES_DB`
- [ ] Free disk on both VPS (<80% target)
- [ ] Confirm keys file present on 94 and `pnl` works there

## Later

- [ ] Optional Binance WS for news pairs (today REST poll; WS preferred per RULES)
- [ ] Richer sitrep: per-bot trade-log summary when bots expose shared trade DBs
- [ ] Alerting when candle lag stale or bot DOWN
- [ ] W.I.P GitHub remote if missing
- [ ] Scheduled incremental refresh of research candles (Windows task)

## Won’t do unless asked

- Migrate xgb off self-fetch
- Run strategy backtests inside botsgeneral
