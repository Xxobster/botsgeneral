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
        self.history_bars = int(self.registry.get("history_bars") or 1000)
        self._active: set[tuple[str, str, str]] = set()
        self._bootstrapped: set[tuple[str, str, str]] = set()
        self._stop = False
        self._ws = BybitMultiKlineWS(on_candle=self._on_ws_candle)
        self._last_binance_poll = 0.0

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
            if p.key() in self._bootstrapped and self.db.candle_count(p) > 10:
                # light refresh of recent bars
                try:
                    self._refresh_recent(p)
                except Exception:
                    log.exception("refresh failed for %s", p)
                continue
            try:
                log.info("Bootstrapping %s (%s bars)", p, self.history_bars)
                if p.exchange == "bybit":
                    n = bybit_rest.upsert_pair(self.db, p, limit=self.history_bars)
                else:
                    n = binance_rest.upsert_pair(self.db, p, limit=self.history_bars)
                log.info("Bootstrapped %s -> %s rows", p, n)
                self._bootstrapped.add(p.key())
            except Exception:
                log.exception("bootstrap failed for %s", p)

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
