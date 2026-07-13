# Changelog

## 2026-07-13 (evening)

- Max candle history (`history_bars: 0` + `history_schema: 3`) — paginate until exchange empty.
- Phone report: `bots` / `bots trades <account|bot> [SYMBOL]`; since date in `/etc/botsgeneral/report.yaml`.
- Disk cleanup script `deploy/cleanup_disk.sh`.
- Confirmed architecture: botsgeneral = OHLCV only; each trading bot computes its own indicators and decides.
