"""Binance USD-M futures kline WebSocket — closed bars only (twin of BybitMultiKlineWS)."""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable

from botsgeneral.models import BINANCE_INTERVAL, CandlePair, CandleRow, normalize_timeframe

log = logging.getLogger(__name__)

# Legacy ``/ws`` was retired 2026-04-23 (ACK still works, market data is silent).
# Kline / aggTrade live on the market path.
WS_FUTURES = "wss://fstream.binance.com/market/ws"
WS_FUTURES_COMBINED = "wss://fstream.binance.com/market/stream"


def stream_name(pair: CandlePair) -> str:
    interval = BINANCE_INTERVAL.get(pair.timeframe)
    if interval is None:
        raise KeyError(pair.timeframe)
    return f"{pair.symbol.lower()}@kline_{interval}"


def candle_from_kline(k: dict[str, Any], *, symbol: str | None = None) -> CandleRow | None:
    """Map a Binance kline payload to a row. Forming bars (x=false) return None."""
    if not k or not k.get("x"):
        return None
    sym = str(symbol or k.get("s") or "").upper()
    tf = normalize_timeframe(str(k.get("i") or ""))
    if not sym or not tf:
        return None
    return CandleRow(
        exchange="binance",
        symbol=sym,
        timeframe=tf,
        ts_ms=int(k["t"]),
        open=float(k["o"]),
        high=float(k["h"]),
        low=float(k["l"]),
        close=float(k["c"]),
        volume=float(k["v"]),
        quote_volume=float(k["q"]) if k.get("q") not in (None, "") else None,
        trades=int(k["n"]) if k.get("n") not in (None, "") else None,
        taker_buy_base=float(k["V"]) if k.get("V") not in (None, "") else None,
        taker_buy_quote=float(k["Q"]) if k.get("Q") not in (None, "") else None,
    )


def parse_ws_message(message: str) -> CandleRow | None:
    """Parse one WS text frame. Ignore pings, subscribe acks, and forming klines."""
    try:
        payload = json.loads(message)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        return None
    k = data.get("k")
    if not isinstance(k, dict):
        return None
    return candle_from_kline(k, symbol=str(data.get("s") or k.get("s") or ""))


class BinanceMultiKlineWS:
    """One public USD-M futures WS; dynamic subscribe for confirmed klines only."""

    def __init__(self, on_candle: Callable[[CandleRow], None]):
        self.on_candle = on_candle
        self._lock = threading.Lock()
        self._topics: set[str] = set()
        self._desired: set[str] = set()
        self._ws: Any = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._pair_by_topic: dict[str, CandlePair] = {}
        self._req_id = 1

    def set_pairs(self, pairs: list[CandlePair]) -> None:
        desired: set[str] = set()
        mapping: dict[str, CandlePair] = {}
        for p in pairs:
            if p.exchange != "binance":
                continue
            if p.timeframe not in BINANCE_INTERVAL:
                log.warning("Skip unsupported Binance TF %s", p)
                continue
            t = stream_name(p)
            desired.add(t)
            mapping[t] = p
        with self._lock:
            self._desired = desired
            self._pair_by_topic = mapping
            self._sync_subs_unlocked()

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def _sync_subs_unlocked(self) -> None:
        if not self._ws or not self._running:
            return
        to_add = self._desired - self._topics
        to_drop = self._topics - self._desired
        if to_add:
            msg = {"method": "SUBSCRIBE", "params": sorted(to_add), "id": self._next_id()}
            try:
                self._ws.send(json.dumps(msg))
                self._topics |= to_add
                log.info("Binance WS subscribe %s", sorted(to_add))
            except Exception as e:
                log.exception("Binance subscribe failed: %s", e)
        if to_drop:
            msg = {"method": "UNSUBSCRIBE", "params": sorted(to_drop), "id": self._next_id()}
            try:
                self._ws.send(json.dumps(msg))
                self._topics -= to_drop
                log.info("Binance WS unsubscribe %s", sorted(to_drop))
            except Exception as e:
                log.exception("Binance unsubscribe failed: %s", e)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name="binance-kline-ws", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

    def _run(self) -> None:
        import websocket

        while self._running:
            try:
                self._ws = websocket.WebSocketApp(
                    WS_FUTURES,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self._ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as e:
                log.exception("Binance WS run_forever error: %s", e)
            if not self._running:
                break
            log.warning("Binance WS disconnected; reconnecting in 3s")
            time.sleep(3)

    def _on_open(self, ws) -> None:
        log.info("Binance WS connected")
        with self._lock:
            self._topics.clear()
            self._sync_subs_unlocked()

    def _on_close(self, ws, status, msg) -> None:
        log.warning("Binance WS closed status=%s msg=%s", status, msg)
        with self._lock:
            self._topics.clear()

    def _on_error(self, ws, err) -> None:
        log.error("Binance WS error: %s", err)

    def _on_message(self, ws, message: str) -> None:
        if isinstance(message, (bytes, bytearray)):
            message = message.decode("utf-8", "replace")
        candle = parse_ws_message(message)
        if candle is None:
            return
        try:
            self.on_candle(candle)
        except Exception:
            log.exception("on_candle failed")
