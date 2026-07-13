# Current State

**Last updated:** 2026-07-13 (evening)

## Phase

Collectors live; phone `bots` report + max history backfill shipping.

### Architecture (confirmed)

**botsgeneral** writes shared OHLCV only. Each trading bot **reads** that DB, computes **its own** indicators/features, then decides to trade with **its own** Bybit keys.

### Resume

1. Deploy report + history_schema bump; wait for full backfill (5m pairs take a while)
2. From `/root`: `bots` and `bots trades crypthor2 BTCUSDT`
3. Edit `/etc/botsgeneral/report.yaml` `since_date` as needed
4. Keep migrating remaining bots via AGENT_PROMPTS.md

