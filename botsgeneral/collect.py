from __future__ import annotations

import logging
import os
import signal
import time
from pathlib import Path

from botsgeneral.db import CandleDB
from botsgeneral.discover import detect_vps_id, discover_pairs, load_registry, unique_pairs
from botsgeneral.fetch import binance_rest, bybit_rest
from botsgeneral.fetch.bybit_ws import BybitMultiKlineWS
from botsgeneral.models import CandlePair, CandleRow, TF_MS

log = logging.getLogger(__name__)

# Min bars before we treat history as "deep enough" (else re-backfill)
MIN_BARS_OK = {
    "1m": 50_000,
    "5m": 50_000,
    "15m": 30_000,
    "1h": 10_000,
    "2h": 8_000,
    "4h": 5_000,
}


def default_db_path(registry: dict) -> str:
    env = os.environ.get("SHARED_CANDLES_DB") or os.environ.get("BOTSGENERAL_DB")
    if env:
        return env
    # local/dev fallback
    local = Path(__file__).resolve().parents[1] / "data" / "shared_candles.db"
    if os.name == "nt" or not Path("/var/lib/botsgeneral").exists():
        return str(local)
    return registry.get("default_db_path") or "/var/lib/botsgeneral/shared_candles.db"


class Collector:
    def __init__(self, registry_path: str | None = None, db_path: str | None = None, vps_id: str | None = None):
        self.registry = load_registry(registry_path)
        self.vps_id = vps_id or detect_vps_id(self.registry)
        self.db_path = db_path or default_db_path(self.registry)
        self.db = CandleDB(self.db_path)
        self.discovery_interval = int(self.registry.get("discovery_interval_sec") or 60)
        # 0 = fetch all available history from the exchange
        self.history_bars = int(self.registry.get("history_bars") if self.registry.get("history_bars") is not None else 0)
        self.history_schema = str(self.registry.get("history_schema") or "3")
        self._active: set[tuple[str, str, str]] = set()
        self._bootstrapped: set[tuple[str, str, str]] = set()
        self._stop = False
        self._ws = BybitMultiKlineWS(on_candle=self._on_ws_candle)
        self._last_binance_poll = 0.0
        if self.db.get_meta("history_schema") != self.history_schema:
            log.warning(
                "history_schema %s -> %s: will full backfill all pairs",
                self.db.get_meta("history_schema"),
                self.history_schema,
            )
            self._bootstrapped.clear()
            self._need_schema_bump = True
        else:
            self._need_schema_bump = False
        if os.environ.get("BOTSGENERAL_FORCE_BACKFILL") == "1":
            log.warning("BOTSGENERAL_FORCE_BACKFILL=1: full backfill")
            self._bootstrapped.clear()
            self._need_schema_bump = True

    def _on_ws_candle(self, candle: CandleRow) -> None:
        n = self.db.upsert_candles([candle])
        log.info("WS candle upserted %s %s %s ts=%s n=%s", candle.exchange, candle.symbol, candle.timeframe, candle.ts_ms, n)

    def stop(self, *_args) -> None:
        self._stop = True

    def run(self) -> None:
        log.info(
            "Collector starting vps=%s db=%s discovery_every=%ss",
            self.vps_id,
            self.db_path,
            self.discovery_interval,
        )
        self.db.set_meta("collector_started_ms", str(int(time.time() * 1000)))
        if self.vps_id:
            self.db.set_meta("vps_id", self.vps_id)
        self._ws.start()
        signal.signal(signal.SIGINT, self.stop)
        try:
            signal.signal(signal.SIGTERM, self.stop)
        except Exception:
            pass

        while not self._stop:
            try:
                self._discovery_and_bootstrap()
                self._poll_binance()
            except Exception:
                log.exception("collector loop error")
            for _ in range(self.discovery_interval):
                if self._stop:
                    break
                time.sleep(1)

        self._ws.stop()
        self.db.set_meta("collector_stopped_ms", str(int(time.time() * 1000)))
        self.db.close()
        log.info("Collector stopped")

    def _discovery_and_bootstrap(self) -> None:
        items, warnings = discover_pairs(self.registry, self.vps_id)
        for w in warnings:
            log.warning("discover: %s", w)
        self.db.replace_discovered(items)
        pairs = unique_pairs(items)
        keys = {p.key() for p in pairs}
        added = keys - self._active
        removed = self._active - keys
        if added:
            log.info("New pairs: %s", sorted(str(CandlePair(*k)) for k in added))
        if removed:
            log.info("Removed pairs: %s", sorted(str(CandlePair(*k)) for k in removed))
        self._active = keys

        bybit_pairs = [p for p in pairs if p.exchange == "bybit"]
        self._ws.set_pairs(bybit_pairs)

        for p in pairs:
            count = self.db.candle_count(p)
            # Min bars hint: if far below typical deep history, re-backfill
            min_ok = MIN_BARS_OK.get(p.timeframe, 5_000)
            need_full = (
                p.key() not in self._bootstrapped
                or self._need_schema_bump
                or count < min_ok
            )
            if not need_full:
                try:
                    self._refresh_recent(p)
                except Exception:
                    log.exception("refresh failed for %s", p)
                continue
            try:
                target = "MAX" if self.history_bars <= 0 else str(self.history_bars)
                log.info("Bootstrapping %s (target=%s bars, have=%s)", p, target, count)
                if p.exchange == "bybit":
                    n = bybit_rest.upsert_pair(self.db, p, limit=self.history_bars)
                else:
                    n = binance_rest.upsert_pair(self.db, p, limit=self.history_bars)
                log.info("Bootstrapped %s -> upserted %s (db now %s)", p, n, self.db.candle_count(p))
                self._bootstrapped.add(p.key())
            except Exception:
                log.exception("bootstrap failed for %s", p)

        if self._need_schema_bump and pairs and all(p.key() in self._bootstrapped for p in pairs):
            self.db.set_meta("history_schema", self.history_schema)
            self._need_schema_bump = False
            log.info("history_schema set to %s", self.history_schema)

    def _refresh_recent(self, pair: CandlePair) -> None:
        if pair.exchange == "bybit":
            rows = bybit_rest.fetch_klines(pair, limit=5)
        else:
            rows = binance_rest.fetch_klines(pair, limit=5)
        if rows:
            self.db.upsert_candles(rows)

    def _poll_binance(self) -> None:
        now = time.time()
        if now - self._last_binance_poll < 15:
            return
        self._last_binance_poll = now
        for key in list(self._active):
            pair = CandlePair(*key)
            if pair.exchange != "binance":
                continue
            # poll near candle close: always keep last few bars fresh
            try:
                rows = binance_rest.poll_recent(pair, limit=3)
                if rows:
                    self.db.upsert_candles(rows)
            except Exception:
                log.exception("binance poll failed for %s", pair)


def run_collect(registry_path: str | None = None, db_path: str | None = None, vps_id: str | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    Collector(registry_path=registry_path, db_path=db_path, vps_id=vps_id).run()
    return 0
