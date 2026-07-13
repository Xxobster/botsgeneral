# VPS map

| IP | SSH alias | Collector unit | Bots (candles) |
|----|-----------|----------------|----------------|
| 94.156.189.76 | `eventactivities-vps` | `botsgeneral-collector@94.156.189.76` | news (binance), W.I.P (bybit); xgb no-candles |
| 212.73.150.178 | `poly-vps` | `botsgeneral-collector@212.73.150.178` | divergences, crypthor2, karmaa_mp (bybit) |

## Bot install paths

| Bot | Path | Account |
|-----|------|---------|
| news | `/home/crypto_alpha` | Xxobster6 |
| W.I.P | `/opt/wip` | Xxobster7 |
| xgb | `/home/xgb` | Xxobster2 / Xxobster13 |
| divergences | `/opt/divergences` | Xxobster3 |
| crypthor2 | `/opt/crypthor` | Xxobster4 |
| karmaa_mp | `/root/karmaa_mp` | Xxobster5 |
| botsgeneral | `/opt/botsgeneral` | ops / Xxobster for market if needed |

## Ops notes

- Prefer **systemd** for collector auto-restart on reboot (enabled).
- Trading bots: **screen** with explicit names + systemd where already used.
- Disk was ~87–88% on both hosts (2026-07-13) — clean logs/old DBs soon.
- 94 SSH can hang on banner under high load — retry until done.
