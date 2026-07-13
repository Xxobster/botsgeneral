# Testing

## Unit

```bash
cd C:\projects\botsgeneral
pytest tests -q
```

Covers: timeframe normalize, DB upsert, parsers against local project trees when present.

## Manual / VPS

```bash
python -m botsgeneral --vps 212.73.150.178 discover
python -m botsgeneral --vps 212.73.150.178 sitrep
python -m botsgeneral --keys /etc/botsgeneral/bybit_keys.txt pnl
journalctl -u botsgeneral-collector@212.73.150.178 -n 50 --no-pager
```

Same for `94.156.189.76`.

## After bot migration

- Logs must not show kline bootstrap/WS upsert from the trading bot.
- Shared DB `candle_freshness` lag within ~2.5× timeframe.
- Bot still evaluates / can open trades on its account.
