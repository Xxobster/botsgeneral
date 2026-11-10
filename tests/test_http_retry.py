import random
import urllib.error

import pytest

from market_data import http_retry as hr


class R:
    def __init__(self, code, headers=None):
        self.status_code, self.headers = code, headers or {}


class S:
    def __init__(self, codes):
        self.codes, self.calls = list(codes), 0

    def get(self, *a, **k):
        self.calls += 1
        c = self.codes.pop(0)
        return R(c, {"Retry-After": "2"} if c == 429 else {})


def test_unit_jitter_stable_and_bounded():
    a = hr.unit_jitter_sec("llm2-ema-btc-1h")
    assert a == hr.unit_jitter_sec("llm2-ema-btc-1h") and 0 <= a < 4
    assert len({round(hr.unit_jitter_sec(f"u{i}"), 3) for i in range(12)}) > 8


def test_backoff_honours_retry_after_and_caps():
    random.seed(1)
    assert hr.backoff_delay(0, 5.0) >= 5.0
    assert hr.backoff_delay(10, None) <= hr.MAX_BACKOFF_SEC + 1.0


def test_429_then_ok_retries():
    slept = []
    s = S([429, 429, 200])
    r = hr.requests_get_retry(s, "u/klines", sleep=slept.append, deadline_sec=60)
    assert r.status_code == 200 and s.calls == 3 and len(slept) == 2 and slept[0] >= 2.0


def test_non_retryable_returned_immediately():
    s = S([418])
    assert hr.requests_get_retry(s, "u", sleep=lambda x: None).status_code == 418 and s.calls == 1


def test_deadline_bounds_total_time():
    t = [0.0]
    s = S([429] * 50)
    def sleep(d): t[0] += d
    r = hr.requests_get_retry(s, "u", sleep=sleep, now=lambda: t[0], deadline_sec=20)
    assert r.status_code == 429 and t[0] <= 20.0
