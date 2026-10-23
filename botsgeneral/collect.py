from __future__ import annotations

import logging
import os
import signal
import time
from pathlib import Path

from botsgeneral.db import CandleDB
from botsgeneral.discover import detect_vps_id, discover_pairs, load_registry, unique_pairs
from botsgeneral.discover.demand import required_bars_by_pair
from botsgeneral.fetch import binance_rest, bybit_rest
from botsgeneral.fetch.binance_ws import BinanceMultiKlineWS
from botsgeneral.fetch.bybit_ws import BybitMultiKlineWS
from botsgeneral.models import CandlePair, CandleRow, TF_MS

log = logging.getLogger(__name__)

# Legacy research-depth hints only. Live fill uses each bot's min_history_bars.


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
        # Full-history downloads are finite backfill work. They must never block
        # this continuous collector from writing fresh decision tips.
        self._history_deferred: set[tuple[str, str, str]] = set()
        self._stop = False
        self._ws = BybitMultiKlineWS(on_candle=self._on_ws_candle)
        self._binance_ws = BinanceMultiKlineWS(on_candle=self._on_ws_candle)
        self._last_binance_poll = 0.0
        # Tip-poll cadence: keep just-closed bars writable within seconds of the hour.
        self.tip_poll_idle_sec = float(os.environ.get("BOTSGENERAL_TIP_POLL_IDLE_SEC", "3"))
        self.tip_poll_near_close_sec = float(os.environ.get("BOTSGENERAL_TIP_POLL_NEAR_SEC", "1"))
        self.near_close_pre_sec = float(os.environ.get("BOTSGENERAL_NEAR_CLOSE_PRE_SEC", "60"))
        self.near_close_post_sec = float(os.environ.get("BOTSGENERAL_NEAR_CLOSE_POST_SEC", "180"))
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
        self._binance_ws.start()
        signal.signal(signal.SIGINT, self.stop)
        try:
            signal.signal(signal.SIGTERM, self.stop)
        except Exception:
            pass

        while not self._stop:
            # Tip-poll before heavy discovery so hour-close bars are not blocked
            # behind a multi-pair history refresh.
            try:
                self._poll_binance()
            except Exception as exc:
                log.exception("collector tip-poll error")
                self._mark_collector_tip_poll_unsafe(exc)
            try:
                self._discovery_and_bootstrap()
            except Exception:
                log.exception("collector discovery/bootstrap error")
            # Keep tip-polling during the discovery interval so just-closed
            # 1h (and other) bars land within seconds of the boundary instead
            # of waiting for the next full discovery cycle (~60s+).
            deadline = time.time() + max(1, self.discovery_interval)
            while not self._stop and time.time() < deadline:
                try:
                    self._poll_binance()
                except Exception as exc:
                    log.exception("collector tip-poll error")
                    self._mark_collector_tip_poll_unsafe(exc)
                time.sleep(self._tip_sleep_sec())

        self._ws.stop()
        self._binance_ws.stop()
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
        binance_pairs = [p for p in pairs if p.exchange == "binance"]
        self._ws.set_pairs(bybit_pairs)
        self._binance_ws.set_pairs(binance_pairs)
        log.info(
            "collector demand n=%s bybit=%s binance=%s pairs=%s",
            len(pairs),
            len(bybit_pairs),
            len(binance_pairs),
            [str(p) for p in pairs],
        )

        need_map = required_bars_by_pair(items, self.registry)
        for p in pairs:
            count = self.db.candle_count(p)
            need = int(need_map.get(p.key(), 500))
            # Always refresh the small, closed tail first so tips stay fresh.
            try:
                self._refresh_recent(p)
            except Exception as exc:
                log.exception("tip refresh failed for %s", p)
                try:
                    from live_candles.freshness import write_data_unsafe

                    write_data_unsafe(
                        exchange=p.exchange,
                        symbol=p.symbol,
                        timeframe=p.timeframe,
                        reason="COLLECTOR_ERROR",
                        detail={"error": f"{type(exc).__name__}: {exc}"[:400]},
                        db_path=self.db_path,
                    )
                except Exception:
                    log.exception("DATA_UNSAFE write failed for %s", p)
                continue
            if count >= need:
                if p.key() not in self._bootstrapped:
                    log.info(
                        "History meets bot need for %s (have=%s need=%s); tip only",
                        p,
                        count,
                        need,
                    )
                self._bootstrapped.add(p.key())
                continue
            try:
                added = self._ensure_needed_history(p, need)
                have = self.db.candle_count(p)
                log.info(
                    "History filled to bot need for %s have=%s need=%s upserted=%s",
                    p,
                    have,
                    need,
                    added,
                )
                if have >= need:
                    self._bootstrapped.add(p.key())
            except Exception:
                log.exception("needed-history fill failed for %s", p)

        # Defense: never leave mid-bar tips in shared DB (breaks research parity)
        pruned_all = self.db.delete_incomplete_tips(pairs)
        if pruned_all:
            log.info("Pruned %s incomplete tip bar(s) across active pairs", pruned_all)

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
        self.db.delete_incomplete_tips([pair])

    def _ensure_needed_history(self, pair: CandlePair, need: int) -> int:
        """Bounded fill: last ``need`` closed bars only. Never paginate to listing."""
        want = max(int(need), 1)
        if pair.exchange == "bybit":
            rows = bybit_rest.fetch_klines(pair, limit=want)
        else:
            rows = binance_rest.fetch_klines(pair, limit=want)
        if not rows:
            return 0
        return int(self.db.upsert_candles(rows))

    def _near_close(self, timeframe: str, *, now_ms: int | None = None) -> bool:
        step = TF_MS.get(timeframe)
        if not step:
            return False
        now = int(now_ms if now_ms is not None else time.time() * 1000)
        bar_open = (now // step) * step
        since = now - bar_open
        to_close = step - since
        return since <= int(self.near_close_post_sec * 1000) or to_close <= int(
            self.near_close_pre_sec * 1000
        )

    def _any_near_close(self) -> bool:
        now_ms = int(time.time() * 1000)
        for key in self._active:
            if self._near_close(key[2], now_ms=now_ms):
                return True
        return False

    def _tip_sleep_sec(self) -> float:
        return self.tip_poll_near_close_sec if self._any_near_close() else self.tip_poll_idle_sec

    def _poll_priority(self, pair: CandlePair) -> tuple[int, int]:
        """Lower tuple sorts first: near-close pairs, then shorter timeframes."""
        step = int(TF_MS.get(pair.timeframe) or 10**12)
        near = 0 if self._near_close(pair.timeframe) else 1
        return (near, step)

    def _mark_collector_tip_poll_unsafe(self, exc: BaseException) -> None:
        """Fleet-visible collector fault so bots fail closed on new entries."""
        try:
            from live_candles.freshness import write_data_unsafe

            write_data_unsafe(
                exchange="binance",
                symbol="COLLECTOR",
                timeframe="1m",
                reason="COLLECTOR_ERROR",
                detail={"error": f"{type(exc).__name__}: {exc}"[:400]},
                db_path=self.db_path,
            )
        except Exception:
            log.exception("failed to write DATA_UNSAFE after tip-poll error")
            try:
                self.db.set_meta(
                    "data_unsafe:binance:COLLECTOR:1m",
                    f'{{"ok":false,"reason":"COLLECTOR_ERROR","updated_ms":{int(time.time()*1000)}}}',
                )
            except Exception:
                log.exception("fallback DATA_UNSAFE meta write failed")

    def _poll_binance(self) -> None:
        now = time.time()
        min_gap = self.tip_poll_near_close_sec if self._any_near_close() else self.tip_poll_idle_sec
        if now - self._last_binance_poll < min_gap:
            return
        self._last_binance_poll = now
        pairs = [
            CandlePair(*key)
            for key in list(self._active)
            if key[0] == "binance"
        ]
        pairs.sort(key=self._poll_priority)
        any_ok = False
        for pair in pairs:
            # poll near candle close: always keep last few bars fresh
            try:
                rows = binance_rest.poll_recent(pair, limit=5)
                if rows:
                    self.db.upsert_candles(rows)
                self.db.delete_incomplete_tips([pair])
                any_ok = True
                try:
                    from live_candles.freshness import check_series_live_data_001

                    # After dropping forming tips, re-read DB tip vs exchange server time.
                    check_series_live_data_001(
                        exchange=pair.exchange,
                        symbol=pair.symbol,
                        timeframe=pair.timeframe,
                        local_tip_ms=None,
                        db_path=self.db_path,
                        persist_flag=True,
                    )
                except Exception:
                    log.exception("LIVE-DATA-001 tip check failed for %s", pair)
            except Exception as exc:
                log.exception("binance poll failed for %s", pair)
                try:
                    from live_candles.freshness import write_data_unsafe

                    write_data_unsafe(
                        exchange=pair.exchange,
                        symbol=pair.symbol,
                        timeframe=pair.timeframe,
                        reason="COLLECTOR_ERROR",
                        detail={"error": f"{type(exc).__name__}: {exc}"[:400]},
                        db_path=self.db_path,
                    )
                except Exception:
                    log.exception("DATA_UNSAFE write failed for %s", pair)
        if any_ok:
            # Clear fleet-wide tip-poll panic once at least one pair refreshed.
            try:
                from live_candles.freshness import clear_data_unsafe

                clear_data_unsafe(
                    exchange="binance",
                    symbol="COLLECTOR",
                    timeframe="1m",
                    db_path=self.db_path,
                )
            except Exception:
                pass


def run_collect(registry_path: str | None = None, db_path: str | None = None, vps_id: str | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Per-fetch "fetched N bars" INFO lines filled ln1 disk (~225k lines/day).
    # Keep collector heartbeat at INFO; fetch layers log warnings and errors only.
    for name in ("botsgeneral.fetch", "market_data"):
        logging.getLogger(name).setLevel(logging.WARNING)
    Collector(registry_path=registry_path, db_path=db_path, vps_id=vps_id).run()
    return 0
