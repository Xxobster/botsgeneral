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
| `sitrep` | Disk/mem/load/CPU, bot UP/DOWN, pair freshness |
| `pnl` | Unified wallet + positions across Bybit accounts |
| `report` / `bots` | Phone report: health + PnL by account/coin |
| `hmi-snapshot` | JSON snapshot for the web Human-Machine Interface |
| `hmi-agent` / `hmi-hub` | Localhost agent / site-root aggregator |

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
| trading VPS | `127.0.0.1:8788` | `botsgeneral-hmi-agent.service` |
| ln1 `94.156.189.76` | `127.0.0.1:8787` + nginx `/` | `botsgeneral-hmi-hub.service` |
| both | `/var/lib/botsgeneral/shared_candles.db` | data |
| both | `/etc/botsgeneral/bybit_keys.txt` | secrets |
