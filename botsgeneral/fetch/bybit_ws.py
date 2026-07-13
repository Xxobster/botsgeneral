from __future__ import annotations

import json
import logging
import threading
import time
from typing import Callable

import websocket

from botsgeneral.models import BYBIT_INTERVAL, BYBIT_INTERVAL_REV, CandlePair, CandleRow

log = logging.getLogger(__name__)

WS_PUBLIC = "wss://stream.bybit.com/v5/public/linear"


class BybitMultiKlineWS:
    """One public WS connection; dynamic subscribe/unsubscribe for confirmed klines."""

    def __init__(self, on_candle: Callable[[CandleRow], None]):
        self.on_candle = on_candle
        self._lock = threading.Lock()
        self._topics: set[str] = set()
        self._desired: set[str] = set()
        self._ws: websocket.WebSocketApp | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._pair_by_topic: dict[str, CandlePair] = {}

    @staticmethod
    def topic_for(pair: CandlePair) -> str:
        iv = BYBIT_INTERVAL[pair.timeframe]
        return f"kline.{iv}.{pair.symbol}"

    def set_pairs(self, pairs: list[CandlePair]) -> None:
        desired = set()
        mapping = {}
        for p in pairs:
            if p.exchange != "bybit":
                continue
            if p.timeframe not in BYBIT_INTERVAL:
                log.warning("Skip unsupported Bybit TF %s", p)
                continue
            t = self.topic_for(p)
            desired.add(t)
            mapping[t] = p
        with self._lock:
            self._desired = desired
            self._pair_by_topic = mapping
            self._sync_subs_unlocked()

    def _sync_subs_unlocked(self) -> None:
        if not self._ws or not self._running:
            return
        to_add = self._desired - self._topics
        to_drop = self._topics - self._desired
        if to_add:
            msg = {"op": "subscribe", "args": sorted(to_add)}
            try:
                self._ws.send(json.dumps(msg))
                self._topics |= to_add
                log.info("Bybit WS subscribe %s", sorted(to_add))
            except Exception as e:
                log.exception("subscribe failed: %s", e)
        if to_drop:
            msg = {"op": "unsubscribe", "args": sorted(to_drop)}
            try:
                self._ws.send(json.dumps(msg))
                self._topics -= to_drop
                log.info("Bybit WS unsubscribe %s", sorted(to_drop))
            except Exception as e:
                log.exception("unsubscribe failed: %s", e)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name="bybit-kline-ws", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

    def _run(self) -> None:
        while self._running:
            try:
                self._ws = websocket.WebSocketApp(
                    WS_PUBLIC,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self._ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as e:
                log.exception("WS run_forever error: %s", e)
            if not self._running:
                break
            log.warning("Bybit WS disconnected; reconnecting in 3s")
            time.sleep(3)

    def _on_open(self, ws) -> None:
        log.info("Bybit WS connected")
        with self._lock:
            self._topics.clear()
            self._sync_subs_unlocked()

    def _on_close(self, ws, status, msg) -> None:
        log.warning("Bybit WS closed status=%s msg=%s", status, msg)
        with self._lock:
            self._topics.clear()

    def _on_error(self, ws, err) -> None:
        log.error("Bybit WS error: %s", err)

    def _on_message(self, ws, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            return
        topic = payload.get("topic") or ""
        if not topic.startswith("kline."):
            return
        data = payload.get("data") or []
        if not data:
            return
        row = data[0] if isinstance(data, list) else data
        if not row.get("confirm"):
            return
        with self._lock:
            pair = self._pair_by_topic.get(topic)
        if pair is None:
            # parse topic kline.{interval}.{symbol}
            parts = topic.split(".")
            if len(parts) >= 3:
                iv, sym = parts[1], parts[2]
                tf = BYBIT_INTERVAL_REV.get(iv, iv)
                pair = CandlePair("bybit", sym, tf)
            else:
                return
        candle = CandleRow(
            exchange="bybit",
            symbol=pair.symbol,
            timeframe=pair.timeframe,
            ts_ms=int(row["start"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
        )
        try:
            self.on_candle(candle)
        except Exception:
            log.exception("on_candle failed")
