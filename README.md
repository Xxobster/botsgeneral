# botsgeneral

Shared **candle collector**, **sitrep**, and **PnL** for trading bots on two VPS hosts.

**Project memory:** [`docs/project_memory/`](docs/project_memory/) — start with `CURRENT_STATE.md` and `RULES.md`.  
**Agent prompts for trading bots:** [`AGENT_PROMPTS.md`](AGENT_PROMPTS.md)

## Why

Multiple bots were each pulling the same OHLCV. This service:

1. Discovers which `(exchange, symbol, timeframe)` pairs are needed by reading each bot’s own config
2. Fetches once (Bybit WS + REST, Binance REST as needed)
3. Writes `/var/lib/botsgeneral/shared_candles.db`
4. Trading bots read that DB (after their migration) and keep their own API keys for orders

**xgb** is registered for sitrep/PnL only (`serve_candles: false`) and keeps pulling Binance itself.

## VPS layout

| VPS | Bots served |
|-----|-------------|
| `94.156.189.76` | news (Binance), W.I.P (Bybit); xgb sitrep only |
| `212.73.150.178` | divergences, crypthor2, karmaa_mp (Bybit) |

## Install (on each VPS)

```bash
cd /opt
git clone git@github.com:Xxobster/botsgeneral.git
cd botsgeneral
bash deploy/install_vps.sh <THIS_VPS_IP>
# place keys (never commit):
sudo cp /path/to/bybit_keys.txt /etc/botsgeneral/bybit_keys.txt
sudo chmod 600 /etc/botsgeneral/bybit_keys.txt
```

Enable example:

```bash
systemctl enable --now botsgeneral-collector@94.156.189.76
# or
systemctl enable --now botsgeneral-collector@212.73.150.178
```

## CLI

```bash
python -m botsgeneral --vps 94.156.189.76 discover
python -m botsgeneral --vps 94.156.189.76 sitrep
python -m botsgeneral --keys /etc/botsgeneral/bybit_keys.txt pnl
python -m botsgeneral --vps 94.156.189.76 collect   # long-running (prefer systemd)
```

Env vars:

- `BOTSGENERAL_VPS` — VPS id
- `SHARED_CANDLES_DB` / `BOTSGENERAL_DB` — DB path
- `BOTSGENERAL_REGISTRY` — registry YAML
- `BOTSGENERAL_KEYS` — keys file

## Adding a new coin

Update the **bot’s** config (e.g. W.I.P `config/live_fleet.json`) and deploy that bot. Within ~60s the collector rediscovers and starts fetching. Only edit `config/bots_registry.yaml` when installing a **new bot project** on a VPS.

## Shared DB schema

Table `candles` PK `(exchange, symbol, timeframe, ts_ms)` with OHLCV plus optional Binance fields (`quote_volume`, `trades`, `taker_buy_*`).

Trading bots should set `SHARED_CANDLES_DB=/var/lib/botsgeneral/shared_candles.db`.
