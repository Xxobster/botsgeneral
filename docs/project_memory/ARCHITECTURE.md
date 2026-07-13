# Architecture

## Components

```
bots_registry.yaml  →  discover (parsers + process scan)
                         ↓
              unique (exchange, symbol, tf)
                         ↓
         ┌───────────────┴───────────────┐
         ▼                               ▼
   Bybit WS + REST                 Binance REST
         └───────────────┬───────────────┘
                         ▼
              shared_candles.db (SQLite WAL)
                         ▲
         trading bots (post-migration) read-only
```

## CLI

| Command | Role |
|---------|------|
| `collect` | Long-running writer + discovery (systemd) |
| `discover` | One-shot print of demanded pairs |
| `sitrep` | Disk/mem/load, bot UP/DOWN, pair freshness |
| `pnl` | Unified wallet + positions across Bybit accounts |

## Parsers

| Bot | Parser | Notes |
|-----|--------|-------|
| news | `news_yaml` | `config/default.yaml` → binance |
| wip | `wip_fleet` | `live_fleet.json` + also 1h |
| divergences | `divergences_launch` | `launch_all_bybit.sh` |
| crypthor2 | `crypthor_services` | active process/systemd → config SYMBOL/SOURCE_INTERVAL |
| karmaa_mp | `karmaa_config` | `btcusdt_mp.py` |
| xgb | `none` | `serve_candles: false` |

## Deploy paths

| Host | Path | Unit |
|------|------|------|
| both | `/opt/botsgeneral` | `botsgeneral-collector@<VPS_IP>.service` |
| both | `/var/lib/botsgeneral/shared_candles.db` | data |
| both | `/etc/botsgeneral/bybit_keys.txt` | secrets |
