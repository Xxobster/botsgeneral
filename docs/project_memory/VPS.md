# VPS map

| Alias | IP | Legacy SSH alias | Role |
|-------|-----|------------------|------|
| `ln1` | 94.156.189.76 | `eventactivities-vps` | Trading + **fleet HMI hub** (`https://bots94.duckdns.org/`); hostname `vps-LIVENET` |
| `ln2` | 212.73.150.178 | `poly-vps` / `news-vps` | divergences, crypthor2, karmaa_mp, news; collector `@212.73.150.178` |
| `ln3` | 185.203.119.52 | `ld-vps` | LLM2 live (Binance structure candles); collector `@185…` |
| `sm` | 212.73.150.149 | — | HMI **agent only** (no public HMI; hub on ln1) |

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
| xgb (removed 2026-08-25) | `/home/xgb` leftover tree | Xxobster2 | ln1 — not in `bots` host list |
| tsm_vpa (stopped 2026-10-22) | `/opt/tsm-vpa` | Xxobster5 | ln1 — unit disabled |
| divergences | `/opt/divergences` | Xxobster3 + Xxobster6 | ln2 |
| crypthor2 | `/opt/crypthor` | Xxobster4 | ln2 |
| karmaa_mp | `/root/karmaa_mp` | Xxobster5 | ln2 |
| llm2 | `/home/llm2` / `/opt/llm2-structure*` | multi (Bybit accounts per cert) | ln1 (units often disabled) / ln3 |
| tsm_chandelier | `/opt/tsm-chandelier` | Xxobster6 (BTC/ETH/SOL 1h min-size) | ln1 |
| botsgeneral | `/opt/botsgeneral` | ops | ln1 / ln2 / ln3 |

## Ops notes

- Prefer **systemd** for collector auto-restart on reboot (enabled).
- Trading bots: **screen** with explicit names + systemd where already used.
- Disk was ~87–88% on both hosts (2026-07-13) — clean logs/old DBs soon.
- ln1 SSH can hang on banner under high load — retry until done.

## One version everywhere (since 2026-10-24)

`/opt/botsgeneral` on ln1 and ln2 is a byte-identical copy of this repo's committed tree
(300 files: `botsgeneral/`, `packages/`, `deploy/`, `scripts/`, `config/bots_registry*.yaml`,
`pyproject.toml`, `requirements.txt`, `README.md`). Do not edit files on a VPS: edit here,
commit, push, then release. Host-local files that are NOT released: `config/report.yaml`
(and `/etc/botsgeneral/report.yaml`), `/etc/botsgeneral/bybit_keys.txt`, the venv, the DB.

`config/bots_registry.yaml` is one file for every host; each host reads only its own `vps:` section.

Release (from Git Bash, repo root, on the committed HEAD):

```bash
git archive -o /tmp/bg.tar HEAD botsgeneral packages deploy scripts config/bots_registry.yaml \
  config/bots_registry.local.yaml pyproject.toml requirements.txt README.md
for h in ln1 ln2; do
  ssh $h 'cd /opt/botsgeneral && tar czf backups/pre-release-$(date -u +%Y%m%dT%H%MZ).tgz --exclude=venv --exclude=backups --exclude=__pycache__ .'
  ssh $h 'cd /opt/botsgeneral && tar xf - --no-same-owner' < /tmp/bg.tar
done
# verify: every released file identical on both hosts
mkdir -p /tmp/bgrel && tar --force-local -xf /tmp/bg.tar -C /tmp/bgrel && (cd /tmp/bgrel && find . -type f | sort | xargs md5sum) > /tmp/bg.md5
for h in ln1 ln2; do ssh $h 'cd /opt/botsgeneral && md5sum -c --quiet -' < /tmp/bg.md5 && echo "$h identical"; done
# restart the botsgeneral services (not the trading bots)
for h in ln1 ln2; do ssh $h 'systemctl restart "botsgeneral-collector@*" botsgeneral-hmi-agent; systemctl is-active --quiet botsgeneral-hmi-hub && systemctl restart botsgeneral-hmi-hub; bots sitrep | head -40'; done
```

Trading bots import `packages/{live_candles,indicators,tradesim,leakage}` through `PYTHONPATH`
and only pick up a release when they restart. Restart them one by one while flat, then
run the live parity audit (LLM2 `scripts/live_parity.py`).
