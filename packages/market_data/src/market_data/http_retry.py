"""Bounded 429/5xx retry for Binance REST + deterministic per-unit start jitter.

Why: ln2 saw ~1800 ``HTTP Error 429`` LOAD_FAILs at the hourly close because a dozen
units and the collector call klines in the same ~3 s with no Retry-After handling.
See LLM2 docs/reports/live/live_dumps_2026-11-10/ln2_candle_load_diag.md.

Both helpers are bounded by ``deadline_sec`` (callers must keep it well below the
120 s confirm window of the live runners) and never sleep past it.
"""

from __future__ import annotations

import hashlib
import logging
import random
import time
from typing import Any, Callable

log = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
WEIGHT_HEADER = "X-MBX-USED-WEIGHT-1M"
DEFAULT_DEADLINE_SEC = 20.0
BASE_BACKOFF_SEC = 0.5
MAX_BACKOFF_SEC = 8.0


def unit_jitter_sec(unit_name: str, max_sec: float = 4.0) -> float:
    """Stable offset in [0, max_sec) derived from the unit name (same value every start)."""
    h = int(hashlib.sha256(unit_name.encode("utf-8")).hexdigest()[:8], 16)
    return (h / 0xFFFFFFFF) * float(max_sec)


def backoff_delay(attempt: int, retry_after: float | None, *, rng: random.Random | None = None) -> float:
    """Retry-After when given, else 0.5*2**attempt capped at 8 s, plus 0-1 s jitter."""
    r = rng or random
    base = min(MAX_BACKOFF_SEC, BASE_BACKOFF_SEC * (2**attempt))
    if retry_after is not None and retry_after > 0:
        base = max(base, float(retry_after))
    return base + r.random()


def _retry_after(headers: Any) -> float | None:
    try:
        v = headers.get("Retry-After") if headers is not None else None
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _log_weight(headers: Any, what: str) -> None:
    try:
        w = headers.get(WEIGHT_HEADER) if headers is not None else None
    except Exception:  # noqa: BLE001
        w = None
    if w:
        log.info("BINANCE_WEIGHT_1M %s used=%s", what, w)


def requests_get_retry(
    session: Any,
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: float = 45,
    deadline_sec: float = DEFAULT_DEADLINE_SEC,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
):
    """``session.get`` retrying only 429/5xx within ``deadline_sec``. Returns the response.

    Non-retryable statuses (418/403/451/400...) are returned as-is so the caller keeps
    its existing handling. After the deadline the last response is returned (the caller's
    ``raise_for_status`` then fails closed exactly as before).
    """
    t0 = now()
    attempt = 0
    while True:
        r = session.get(url, params=params, headers=headers, timeout=timeout)
        _log_weight(getattr(r, "headers", None), url.rsplit("/", 1)[-1])
        if r.status_code not in RETRYABLE_STATUS:
            return r
        delay = backoff_delay(attempt, _retry_after(getattr(r, "headers", None)))
        if now() - t0 + delay > deadline_sec:
            log.warning("BINANCE_RETRY_GIVE_UP status=%s attempts=%d", r.status_code, attempt + 1)
            return r
        log.warning("BINANCE_RETRY status=%s attempt=%d sleep=%.2fs", r.status_code, attempt + 1, delay)
        sleep(delay)
        attempt += 1


def urlopen_json_retry(
    req: Any,
    *,
    timeout: float = 15,
    deadline_sec: float = DEFAULT_DEADLINE_SEC,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
):
    """urllib variant (used by LLM2 ``fetch_ohlcv_binance_rest``): returns parsed JSON."""
    import json
    import urllib.error
    import urllib.request

    t0 = now()
    attempt = 0
    while True:
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                _log_weight(resp.headers, "klines")
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRYABLE_STATUS:
                raise
            last_exc: BaseException = exc
            delay = backoff_delay(attempt, _retry_after(exc.headers))
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            last_exc = exc
            delay = backoff_delay(attempt, None)
        if now() - t0 + delay > deadline_sec:
            raise last_exc
        log.warning("BINANCE_RETRY attempt=%d sleep=%.2fs", attempt + 1, delay)
        sleep(delay)
        attempt += 1
