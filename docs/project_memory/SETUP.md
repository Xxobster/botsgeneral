# Setup

## Local (Windows)

```bash
cd C:\projects\botsgeneral
pip install -e .
# or: pip install -r requirements.txt  + PYTHONPATH=.
```

Discover against local project trees:

```bash
python -m botsgeneral --registry config/bots_registry.local.yaml --vps local discover
python -m botsgeneral --registry config/bots_registry.local.yaml --vps local --db data/shared_candles.db sitrep
python -m botsgeneral pnl
# Keys resolve from %USERPROFILE%\.trading\secrets.env (see RULES.md)
```

Binance / Bybit keys: `%USERPROFILE%\.trading\secrets.env` (env-style).  
Legacy plaintext copies (fallback only): `%USERPROFILE%\.trading\legacy\`

## VPS install

```bash
# preferred (GitHub SSH key on VPS)
cd /opt && git clone git@github.com:Xxobster/botsgeneral.git
cd botsgeneral && bash deploy/install_vps.sh <VPS_IP>

# if clone/SSH flaky: scp tree then
bash deploy/finish_install.sh <VPS_IP>
```

Place keys:

```bash
cp /path/to/bybit_keys.txt /etc/botsgeneral/bybit_keys.txt
chmod 600 /etc/botsgeneral/bybit_keys.txt
```

## Tests

```bash
pytest tests -q
```

## SSH hosts (local config)

- `eventactivities-vps` → 94.156.189.76
- `poly-vps` → 212.73.150.178
- `185.203.119.52` → LD live (+ optional xgb trees); `serve_candles: false` for all bots on this host
