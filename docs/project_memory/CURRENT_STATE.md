# Current State

**Last updated:** 2026-07-13  
**Branch:** `main`  
**Repo:** `git@github.com:Xxobster/botsgeneral.git`

> **Recovery:** Read this file first, then `TODO.md`, `DECISIONS.md`, `RULES.md`, `ARCHITECTURE.md`, `SETUP.md`, `VPS.md`.

## Phase

**Shared candle collector live on both VPS** — trading bots still fetch their own candles until migrated via `AGENT_PROMPTS.md`.

### This session (2026-07-13)

| Area | Status |
|------|--------|
| Collector package | `collect` / `discover` / `sitrep` / `pnl` |
| Auto-discovery | Parses each bot’s config every ~60s; dedupes pairs |
| VPS 212.73.150.178 | `botsgeneral-collector@212.73.150.178` **active** — Bybit for crypthor2 / divergences / karmaa_mp |
| VPS 94.156.189.76 | `botsgeneral-collector@94.156.189.76` **active** — Binance BTC 4h (news) + Bybit 1h/4h (W.I.P); xgb sitrep-only |
| Shared DB | `/var/lib/botsgeneral/shared_candles.db` (WAL SQLite) |
| Keys on VPS | `/etc/botsgeneral/bybit_keys.txt` (not in git) |
| xgb | **Not** migrated — keeps own Binance pull |
| Bot migrations | Pending — user pastes prompts from `AGENT_PROMPTS.md` |

## Sitrep snapshot (2026-07-13)

- **212:** bots UP (divergences, crypthor2, karmaa_mp); ~1000 bars/pair; disk ~88% used (~1.7 GB free)
- **94:** bots UP (news, wip, xgb); collector bootstrapped; disk ~87% used (~2 GB free); load was high during install

## Resume from here

1. Paste `AGENT_PROMPTS.md` into crypthor2 / karmaa_mp / divergences / news / W.I.P agents (skip xgb)
2. After each migration: verify no local kline fetch; signals still fire from shared DB
3. Free disk on both VPS
4. On keyword **sitrep**: run `python -m botsgeneral sitrep` + `pnl` on each VPS and compare live vs expected fleet
