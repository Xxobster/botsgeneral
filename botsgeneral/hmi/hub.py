"""Hub: fan-out to every VPS agent, merge by Xxobster account, serve at /."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from botsgeneral.hmi.jsonutil import dumps, jsonable
from botsgeneral.hmi.aliases import vps_alias

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
STATIC_DIR = Path(__file__).resolve().parent / "static"

DEFAULT_AGENTS = [
    {"id": "ln1", "host": "94.156.189.76", "ssh": "root@94.156.189.76"},
    {"id": "ln2", "host": "212.73.150.178", "ssh": "root@212.73.150.178"},
]

# Hidden from the public fleet page (still may run agents elsewhere).
HIDDEN_AGENT_IDS = frozenset({"sm", "ln3"})
HIDDEN_HOSTS = frozenset({"212.73.150.149", "185.203.119.52"})


def _agent_id_of(obj: dict[str, Any]) -> str:
    return str(obj.get("id") or obj.get("_agent_id") or obj.get("alias") or "").strip().lower()


def _host_of(obj: dict[str, Any]) -> str:
    return str(obj.get("host") or obj.get("vps") or "").strip()


def is_hidden_agent(obj: dict[str, Any]) -> bool:
    """True for SM / LN3 — do not fetch or show them on the public Human-Machine Interface."""
    if _agent_id_of(obj) in HIDDEN_AGENT_IDS:
        return True
    if _host_of(obj) in HIDDEN_HOSTS:
        return True
    return False


def visible_agents(agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [a for a in agents if not is_hidden_agent(a)]


def visible_snaps(snaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [s for s in snaps if not is_hidden_agent(s)]


def _pf_sort_key(row: dict[str, Any]) -> tuple[int, float, int, float]:
    """Best profit factor first; inf ranks above finite; missing last. Then more trades, then PnL."""
    pf = row.get("profit_factor")
    n = int(row.get("n_trades") or 0)
    try:
        pnl = float(row.get("realized_pnl") or 0)
    except (TypeError, ValueError):
        pnl = 0.0
    if pf in ("inf", float("inf")):
        return (0, 0.0, -n, -pnl)
    try:
        v = float(pf)
    except (TypeError, ValueError):
        return (2, 0.0, -n, -pnl)
    if v != v:  # NaN
        return (2, 0.0, -n, -pnl)
    return (1, -v, -n, -pnl)


def _trades_per_day(n_trades: int, days_active: Any) -> float | None:
    try:
        days = float(days_active)
    except (TypeError, ValueError):
        return None
    if days <= 0:
        return None
    return round(float(n_trades) / days, 3)


def _bot_label_map(account: dict[str, Any]) -> dict[str, str]:
    ids = [str(x) for x in (account.get("bot_ids") or []) if x]
    labs = [str(x) for x in (account.get("bots") or []) if x]
    out: dict[str, str] = {}
    for i, bid in enumerate(ids):
        out[bid] = labs[i] if i < len(labs) else bid
    if not out and labs:
        for lab in labs:
            out[lab] = lab
    return out


def _symbols_for_bot(account: dict[str, Any], bot_id: str) -> set[str]:
    mapping = account.get("bot_symbols") or {}
    if isinstance(mapping, dict) and mapping.get(bot_id) is not None:
        return {str(s).upper() for s in (mapping.get(bot_id) or []) if s}
    ids = [str(x) for x in (account.get("bot_ids") or []) if x]
    if len(ids) == 1 and ids[0] == bot_id:
        live = account.get("live_symbols") or []
        coins = [c.get("symbol") for c in (account.get("per_coin") or [])]
        return {str(s).upper() for s in list(live) + coins if s}
    return set()


def pair_winners_from_snaps(snaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per Virtual Private Server + bot + pair, ranked by profit factor."""
    rows: list[dict[str, Any]] = []
    for snap in visible_snaps(snaps):
        if not snap.get("_ok", snap.get("ok")):
            continue
        alias = str(snap.get("alias") or "")
        vps = str(snap.get("vps") or "")
        for a in snap.get("accounts") or []:
            labels = _bot_label_map(a)
            bot_ids = list(labels.keys()) or [str(x) for x in (a.get("bot_ids") or a.get("bots") or []) if x]
            coins = list(a.get("per_coin") or [])
            by_sym = {str(c.get("symbol") or "").upper(): c for c in coins if c.get("symbol")}
            assigned: set[str] = set()
            for bid in bot_ids:
                for sym in sorted(_symbols_for_bot(a, bid)):
                    c = by_sym.get(sym)
                    if not c:
                        continue
                    n = int(c.get("n_trades") or 0)
                    if n < 1:
                        continue
                    assigned.add(sym)
                    days = c.get("days_active")
                    if days in (None, ""):
                        days = a.get("days_active")
                    rows.append(
                        {
                            "vps": vps,
                            "vps_alias": alias or a.get("vps_alias"),
                            "account": a.get("account"),
                            "bot": labels.get(bid) or bid,
                            "bot_id": bid,
                            "pair": sym,
                            "n_trades": n,
                            "wins": c.get("wins"),
                            "losses": c.get("losses"),
                            "realized_pnl": c.get("realized_pnl"),
                            "winrate": c.get("winrate"),
                            "profit_factor": c.get("profit_factor"),
                            "recovery_factor": c.get("recovery_factor"),
                            "max_drawdown": c.get("max_drawdown"),
                            "max_dd_pct": c.get("max_dd_pct"),
                            "payoff": c.get("payoff"),
                            "avg_pnl": c.get("avg_pnl"),
                            "total_equity": a.get("total_equity"),
                            "days_active": days,
                            "trades_per_day": _trades_per_day(n, days),
                            "since": c.get("since") or a.get("since"),
                        }
                    )
            if len(bot_ids) != 1:
                leftover_bot = "—"
            else:
                leftover_bot = labels.get(bot_ids[0]) or bot_ids[0]
            leftover_id = bot_ids[0] if len(bot_ids) == 1 else ""
            for sym, c in by_sym.items():
                if sym in assigned:
                    continue
                n = int(c.get("n_trades") or 0)
                if n < 1:
                    continue
                days = c.get("days_active")
                if days in (None, ""):
                    days = a.get("days_active")
                rows.append(
                    {
                        "vps": vps,
                        "vps_alias": alias or a.get("vps_alias"),
                        "account": a.get("account"),
                        "bot": leftover_bot,
                        "bot_id": leftover_id,
                        "pair": sym,
                        "n_trades": n,
                        "wins": c.get("wins"),
                        "losses": c.get("losses"),
                        "realized_pnl": c.get("realized_pnl"),
                        "winrate": c.get("winrate"),
                        "profit_factor": c.get("profit_factor"),
                        "recovery_factor": c.get("recovery_factor"),
                        "max_drawdown": c.get("max_drawdown"),
                        "max_dd_pct": c.get("max_dd_pct"),
                        "payoff": c.get("payoff"),
                        "avg_pnl": c.get("avg_pnl"),
                        "total_equity": a.get("total_equity"),
                        "days_active": days,
                        "trades_per_day": _trades_per_day(n, days),
                        "since": c.get("since") or a.get("since"),
                    }
                )
    rows.sort(key=_pf_sort_key)
    return rows


def load_token() -> str:
    env = os.environ.get("BOTSGENERAL_HMI_TOKEN")
    if env:
        return env.strip()
    for p in (Path("/etc/botsgeneral/hmi_token"), Path.home() / ".botsgeneral" / "hmi_token"):
        if p.exists():
            return p.read_text(encoding="utf-8", errors="ignore").strip()
    return ""


def load_hub_config() -> dict[str, Any]:
    path = os.environ.get("BOTSGENERAL_HMI_CFG") or "/etc/botsgeneral/hmi.yaml"
    p = Path(path)
    if not p.exists():
        return {"agents": DEFAULT_AGENTS}
    try:
        import yaml

        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            return {"agents": DEFAULT_AGENTS}
        data.setdefault("agents", DEFAULT_AGENTS)
        return data
    except Exception:
        return {"agents": DEFAULT_AGENTS}


def _ssh_identity() -> list[str]:
    ident = os.environ.get("BOTSGENERAL_HMI_SSH_KEY") or "/root/.ssh/hmi_hub"
    if Path(ident).exists():
        return ["-i", ident]
    return []


def _fetch_url(url: str, token: str, timeout: int = 90) -> dict[str, Any]:
    req = Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8"))


def fetch_agent(agent: dict[str, Any], token: str, path: str = "/v1/snapshot") -> dict[str, Any]:
    t0 = time.time()
    aid = str(agent.get("id") or agent.get("host") or "agent")
    try:
        if agent.get("url"):
            url = str(agent["url"]).rstrip("/") + path
            data = _fetch_url(url, token)
        else:
            ssh_target = str(agent.get("ssh") or f"root@{agent['host']}")
            inner = (
                "curl -sf --max-time 75 "
                "-H \"Authorization: Bearer $(tr -d '\\n' </etc/botsgeneral/hmi_token)\" "
                f"http://127.0.0.1:8788{path}"
            )
            cmd = [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=8",
                "-o",
                "StrictHostKeyChecking=accept-new",
                *_ssh_identity(),
                ssh_target,
                inner,
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=95, check=False)
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout or "").strip()[-1500:]
                raise RuntimeError(f"ssh {aid} exit {proc.returncode}: {err}")
            data = json.loads(proc.stdout)
        data["_agent_id"] = aid
        data["_fetch_ms"] = int((time.time() - t0) * 1000)
        data["_ok"] = bool(data.get("ok", True))
        return data
    except Exception as e:
        return {
            "ok": False,
            "_ok": False,
            "_agent_id": aid,
            "alias": agent.get("id") or vps_alias(str(agent.get("host") or "")),
            "vps": agent.get("host"),
            "error": str(e),
            "_fetch_ms": int((time.time() - t0) * 1000),
            "host": {"vps": agent.get("host"), "alias": agent.get("id"), "error": str(e)},
            "accounts": [],
        }


def _merge_accounts(snaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for snap in snaps:
        if not snap.get("_ok", snap.get("ok")):
            continue
        vps = snap.get("vps")
        alias = snap.get("alias")
        for a in snap.get("accounts") or []:
            name = str(a.get("account") or "")
            if not name:
                continue
            if name not in by:
                row = dict(a)
                row["vps_list"] = [vps] if vps else []
                row["alias_list"] = [alias] if alias else []
                by[name] = row
                order.append(name)
                continue
            cur = by[name]
            if vps and vps not in cur.get("vps_list", []):
                cur.setdefault("vps_list", []).append(vps)
            if alias and alias not in cur.get("alias_list", []):
                cur.setdefault("alias_list", []).append(alias)
            for bid in a.get("bot_ids") or []:
                if bid not in (cur.get("bot_ids") or []):
                    cur.setdefault("bot_ids", []).append(bid)
            for lab in a.get("bots") or []:
                if lab not in (cur.get("bots") or []):
                    cur.setdefault("bots", []).append(lab)
            for st in a.get("strategies") or []:
                cur.setdefault("strategies", [])
                if not any(x.get("bot") == st.get("bot") for x in cur["strategies"]):
                    cur["strategies"].append(st)
            seen = {
                (t.get("order_id"), t.get("updated_ms"), t.get("symbol"), t.get("pnl"))
                for t in (cur.get("trades") or [])
            }
            for t in a.get("trades") or []:
                key = (t.get("order_id"), t.get("updated_ms"), t.get("symbol"), t.get("pnl"))
                if key in seen:
                    continue
                seen.add(key)
                cur.setdefault("trades", []).append(t)
            # Keep the wallet row with more equity if one side failed.
            try:
                if float(a.get("total_equity") or 0) >= float(cur.get("total_equity") or 0):
                    for k in (
                        "total_equity",
                        "total_wallet_balance",
                        "total_perp_upl",
                        "positions",
                        "closed_all",
                        "per_coin",
                        "equity_curve",
                        "equity_curve_by_symbol",
                        "last_open",
                        "live_symbols",
                        "days_active",
                        "since",
                        "n_open_positions",
                        "closed_leg_count",
                        "closed_roundtrip_count",
                    ):
                        if a.get(k) is not None:
                            cur[k] = a.get(k)
            except (TypeError, ValueError):
                pass
    for row in by.values():
        trades = row.get("trades") or []
        trades.sort(key=lambda t: int(t.get("updated_ms") or 0), reverse=True)
        row["trades"] = trades
        if row.get("n_open_positions") is None:
            row["n_open_positions"] = len(
                [
                    p
                    for p in (row.get("positions") or [])
                    if float(p.get("size") or p.get("qty") or 0) > 0
                ]
            )
        row["closed_raw_count"] = int(
            row.get("closed_roundtrip_count")
            or row.get("closed_leg_count")
            or len(trades)
        )
    return [by[n] for n in order]


def assemble_fleet(snaps: list[dict[str, Any]]) -> dict[str, Any]:
    snaps = visible_snaps(snaps)
    hosts = []
    for s in snaps:
        h = dict(s.get("host") or {})
        h["alias"] = s.get("alias") or h.get("alias")
        h["vps"] = s.get("vps") or h.get("vps")
        h["ok"] = bool(s.get("_ok", s.get("ok")))
        h["error"] = s.get("error")
        h["fetch_ms"] = s.get("_fetch_ms")
        h["agent_id"] = s.get("_agent_id")
        h["sitrep"] = s.get("sitrep") or {}
        hosts.append(h)
    accounts = _merge_accounts(snaps)
    total_real = 0.0
    total_upl = 0.0
    total_eq = 0.0
    n_trades = 0
    n_open = 0
    for a in accounts:
        m = a.get("closed_all") or {}
        try:
            total_real += float(m.get("realized_pnl") or 0)
        except (TypeError, ValueError):
            pass
        try:
            total_upl += float(a.get("total_perp_upl") or 0)
        except (TypeError, ValueError):
            pass
        try:
            total_eq += float(a.get("total_equity") or 0)
        except (TypeError, ValueError):
            pass
        n_trades += int(m.get("n_trades") or 0)
        try:
            n_open += int(a.get("n_open_positions") or 0)
        except (TypeError, ValueError):
            n_open += len(
                [
                    p
                    for p in (a.get("positions") or [])
                    if float(p.get("size") or p.get("qty") or 0) > 0
                ]
            )
    return jsonable(
        {
            "ok": True,
            "generated_ms": int(time.time() * 1000),
            "hosts": hosts,
            "accounts": accounts,
            "pair_winners": pair_winners_from_snaps(snaps),
            "totals": {
                "n_accounts": len(accounts),
                "n_trades": n_trades,
                "n_open_positions": n_open,
                "realized_pnl": total_real,
                "open_upl": total_upl,
                "combined": total_real + total_upl,
                "equity": total_eq,
            },
            "errors": [
                {"agent": s.get("_agent_id"), "error": s.get("error")}
                for s in snaps
                if not s.get("_ok", s.get("ok"))
            ],
        }
    )


class HubState:
    def __init__(self) -> None:
        self.cfg = load_hub_config()
        self.token = load_token()
        self.lock = threading.Lock()
        self.inflight: threading.Event | None = None
        self.latest: dict[str, Any] | None = None
        self.latest_hosts: dict[str, Any] | None = None


HUB = HubState()


def refresh_fleet() -> dict[str, Any]:
    agents = visible_agents(list(HUB.cfg.get("agents") or DEFAULT_AGENTS))
    snaps: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, len(agents))) as pool:
        futs = {pool.submit(fetch_agent, a, HUB.token, "/v1/snapshot"): a for a in agents}
        for fut in as_completed(futs):
            snaps.append(fut.result())
    fleet = assemble_fleet(snaps)
    with HUB.lock:
        HUB.latest = fleet
    return fleet


def refresh_hosts() -> dict[str, Any]:
    agents = visible_agents(list(HUB.cfg.get("agents") or DEFAULT_AGENTS))
    hosts = []
    with ThreadPoolExecutor(max_workers=max(1, len(agents))) as pool:
        futs = {pool.submit(fetch_agent, a, HUB.token, "/v1/host"): a for a in agents}
        for fut in as_completed(futs):
            snap = fut.result()
            h = dict(snap.get("host") or {})
            h["ok"] = bool(snap.get("_ok", snap.get("ok")))
            h["error"] = snap.get("error")
            h["alias"] = snap.get("alias") or h.get("alias")
            hosts.append(h)
    payload = jsonable({"ok": True, "generated_ms": int(time.time() * 1000), "hosts": hosts})
    with HUB.lock:
        HUB.latest_hosts = payload
    return payload


MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".json": "application/json; charset=utf-8",
}


def _send(handler: BaseHTTPRequestHandler, code: int, body: bytes, content_type: str) -> None:
    handler.send_response(code)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        # Legacy /bots/ → root (301) so old bookmarks still work.
        if path == "/bots" or path.startswith("/bots/"):
            rest = path[len("/bots") :] or "/"
            if not rest.startswith("/"):
                rest = "/" + rest
            self.send_response(301)
            self.send_header("Location", rest)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path in ("/", "/index.html"):
            self._static("index.html")
            return
        if path.startswith("/api/"):
            self._api(path)
            return
        if path == "/health":
            _send(self, 200, dumps({"ok": True, "role": "hub"}).encode("utf-8"), MIME[".json"])
            return
        # Static assets at root (style.css, app.js, …)
        rel = path.lstrip("/")
        if rel:
            self._static(rel)
            return
        _send(self, 404, b"not found", "text/plain; charset=utf-8")

    def _api(self, path: str) -> None:
        try:
            if path.endswith("/health"):
                payload = {"ok": True, "role": "hub"}
            elif path.endswith("/host") or path.endswith("/hosts"):
                payload = refresh_hosts()
            elif path.endswith("/fleet") or path.endswith("/snapshot"):
                payload = refresh_fleet()
            else:
                _send(self, 404, dumps({"ok": False, "error": "not found"}).encode(), MIME[".json"])
                return
            _send(self, 200, dumps(payload).encode("utf-8"), MIME[".json"])
        except Exception as e:
            _send(self, 500, dumps({"ok": False, "error": str(e)}).encode("utf-8"), MIME[".json"])

    def _static(self, rel: str) -> None:
        rel = rel.lstrip("/")
        if not rel:
            rel = "index.html"
        target = (STATIC_DIR / rel).resolve()
        if STATIC_DIR not in target.parents and target != STATIC_DIR:
            _send(self, 403, b"forbidden", "text/plain")
            return
        if not target.is_file():
            _send(self, 404, b"not found", "text/plain")
            return
        data = target.read_bytes()
        _send(self, 200, data, MIME.get(target.suffix, "application/octet-stream"))


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    httpd = ThreadingHTTPServer((host, int(port)), Handler)
    print(json.dumps({"ok": True, "role": "hub", "listen": f"{host}:{port}"}), flush=True)
    httpd.serve_forever()


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="botsgeneral hmi-hub")
    p.add_argument("--host", default=os.environ.get("BOTSGENERAL_HMI_HUB_HOST", DEFAULT_HOST))
    p.add_argument("--port", type=int, default=int(os.environ.get("BOTSGENERAL_HMI_HUB_PORT", DEFAULT_PORT)))
    args = p.parse_args(argv)
    serve(args.host, args.port)
    return 0
