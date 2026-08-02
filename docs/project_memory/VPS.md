# VPS map

| Alias | IP | Legacy SSH alias | Role |
|-------|-----|------------------|------|
| `ln1` | 94.156.189.76 | `eventactivities-vps` | tsm_vpa (Bybit); xgb sitrep; collector `@94…` |
| `ln2` | 212.73.150.178 | `poly-vps` / `news-vps` | divergences, crypthor2, karmaa_mp, news; collector `@212.73.150.178` |
| `ln3` | 185.203.119.52 | `ld-vps` | LD fleet (Xxobster9/10/11); collector `@185…` |
| `sm` | 212.73.150.149 | — | Separate host (hostname `vps-LIVENET`) |

## PuTTY / OpenSSH keys (per host)

One dedicated Ed25519 keypair per alias (not committed; live under `%USERPROFILE%\.ssh\`):

| Alias | OpenSSH private | PuTTY private | Public |
|-------|-----------------|---------------|--------|
| ln1 | `~\.ssh\ln1` | `~\.ssh\ln1.ppk` | `~\.ssh\ln1.pub` |
| ln2 | `~\.ssh\ln2` | `~\.ssh\ln2.ppk` | `~\.ssh\ln2.pub` |
| ln3 | `~\.ssh\ln3` | `~\.ssh\ln3.ppk` | `~\.ssh\ln3.pub` |
| sm | `~\.ssh\sm` | `~\.ssh\sm.ppk` | `~\.ssh\sm.pub` |

- OpenSSH: `ssh ln2` (IdentityFile set in `~\.ssh\config`).
- PuTTY / Plink: use the matching `.ppk` (PPK version 3).
- Regenerate/convert helpers: `scripts/_gen_putty_keys.py`, `scripts/_openssh_to_ppk_gui.py`.
- All four public keys are in root `authorized_keys` and verified with the matching private key (2026-08-02).

Legacy shared key `~\.ssh\id_ed25519` still works on ln1–ln3 aliases (`eventactivities-vps`, `poly-vps`, `ld-vps`). `sm` was bootstrapped with `~\.ssh\orderbook_vps`.

## Bot install paths

| Bot | Path | Account | VPS |
|-----|------|---------|-----|
| news | `/home/crypto_alpha` | Xxobster6 | ln2 |
| xgb | `/home/xgb` | Xxobster2 | ln1 |
| tsm_vpa | `/opt/tsm-vpa` | Xxobster5 | ln1 |
| divergences | `/opt/divergences` | Xxobster3 + Xxobster6 | ln2 |
| crypthor2 | `/opt/crypthor` | Xxobster4 | ln2 |
| karmaa_mp | `/root/karmaa_mp` | Xxobster5 | ln2 |
| botsgeneral | `/opt/botsgeneral` | ops | ln1 / ln2 / ln3 |

## Ops notes

- Prefer **systemd** for collector auto-restart on reboot (enabled).
- Trading bots: **screen** with explicit names + systemd where already used.
- Disk was ~87–88% on both hosts (2026-07-13) — clean logs/old DBs soon.
- ln1 SSH can hang on banner under high load — retry until done.
