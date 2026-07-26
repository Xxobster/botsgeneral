# VPS map

| IP | SSH alias | Collector unit | Bots (candles) |
|----|-----------|----------------|----------------|
| 94.156.189.76 | `eventactivities-vps` | `botsgeneral-collector@94.156.189.76` | tsm_vpa (Bybit 1d); xgb sitrep only |
| 212.73.150.178 | `poly-vps` | `botsgeneral-collector@212.73.150.178` | divergences, crypthor2, karmaa_mp (bybit); news (Binance) |

## Bot install paths

| Bot | Path | Account | VPS |
|-----|------|---------|-----|
| news | `/home/crypto_alpha` | Xxobster6 | 212.73.150.178 |
| xgb | `/home/xgb` | Xxobster2 | 94.156.189.76 |
| tsm_vpa | `/opt/tsm-vpa` | Xxobster5 | 94.156.189.76 |
| divergences | `/opt/divergences` | Xxobster3 | 212.73.150.178 |
| crypthor2 | `/opt/crypthor` | Xxobster4 | 212.73.150.178 |
| karmaa_mp | `/root/karmaa_mp` | Xxobster5 | 212.73.150.178 |
| botsgeneral | `/opt/botsgeneral` | ops | both |

## Ops notes

- Prefer **systemd** for collector auto-restart on reboot (enabled).
- Trading bots: **screen** with explicit names + systemd where already used.
- Disk was ~87–88% on both hosts (2026-07-13) — clean logs/old DBs soon.
- 94 SSH can hang on banner under high load — retry until done.
