"""Outbound limits: deadline, per-attempt timeouts, response-size cap and the call budget."""

import threading
import time

import httpx
import pytest

from app.infrastructure.gis import retry
from app.infrastructure.gis.errors import (
    BUSY_MESSAGE,
    CLIENT_QUOTA_MESSAGE,
    QUOTA_MESSAGE,
    TOO_MUCH_DATA_MESSAGE,
    GisUnavailableError,
)
from app.infrastructure.gis.outbound import (
    CONNECT_TIMEOUT_S,
    OutboundBudget,
    attempt_timeout,
    read_json,
    time_left,
)


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


# ── Deadline and timeouts ─────────────────────────────────────────────────────

def test_time_left_without_a_deadline_is_none():
    assert time_left(None, "svc") is None


def test_time_left_raises_once_the_deadline_has_passed():
    with pytest.raises(GisUnavailableError, match="deadline"):
        time_left(time.monotonic() - 0.01, "svc")


def test_attempt_timeout_is_capped_by_the_time_left():
    full = attempt_timeout(20.0, None, "svc")
    assert full.read == 20.0 and full.connect == CONNECT_TIMEOUT_S
    short = attempt_timeout(20.0, time.monotonic() + 3.0, "svc")
    assert short.read <= 3.0 and short.connect <= 3.0 and short.pool <= 2.0


# ── Response-size cap ─────────────────────────────────────────────────────────

def _streamed(handler, max_bytes):
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with client.stream("GET", "https://example.test/") as response:
            return read_json(response, max_bytes, None, "svc")


def test_read_json_parses_a_body_under_the_cap():
    assert _streamed(lambda r: httpx.Response(200, json={"a": 1}), 100) == {"a": 1}


def test_read_json_refuses_a_declared_length_over_the_cap():
    def handler(request):
        return httpx.Response(200, content=b"{}", headers={"Content-Length": "999999"})

    with pytest.raises(GisUnavailableError) as info:
        _streamed(handler, 100)
    assert info.value.public_message == TOO_MUCH_DATA_MESSAGE


def test_read_json_refuses_an_undeclared_body_over_the_cap():
    def handler(request):
        return httpx.Response(200, content=iter([b"[" + b"1," * 100, b"1]"]))

    with pytest.raises(GisUnavailableError) as info:
        _streamed(handler, 100)
    assert info.value.public_message == TOO_MUCH_DATA_MESSAGE


# ── Budget ────────────────────────────────────────────────────────────────────

def test_daily_quota_refuses_calls_until_the_window_ends():
    clock = FakeClock()
    budget = OutboundBudget("svc", max_concurrent=2, per_day=2, clock=clock)
    for _ in range(2):
        with budget.call():
            pass
    with pytest.raises(GisUnavailableError) as info:
        with budget.call():
            pass
    assert info.value.public_message == QUOTA_MESSAGE
    assert 0 < info.value.retry_after_s <= 86400
    clock.now += 86400
    with budget.call():
        pass


def test_no_free_slot_is_answered_busy():
    budget = OutboundBudget("svc", max_concurrent=1, per_day=10, max_wait_s=0.01)
    with budget.call():
        with pytest.raises(GisUnavailableError) as info:
            with budget.call():
                pass
    assert info.value.public_message == BUSY_MESSAGE
    with budget.call():  # the slot is released afterwards
        pass


def test_a_refused_call_does_not_keep_its_slot():
    budget = OutboundBudget("svc", max_concurrent=1, per_day=1, max_wait_s=0.01)
    with budget.call():
        pass
    for _ in range(3):
        with pytest.raises(GisUnavailableError, match="daily budget"):
            with budget.call():
                pass


def test_calls_are_spaced_by_the_minimum_interval(monkeypatch):
    slept = []
    monkeypatch.setattr(retry, "sleep", slept.append)
    clock = FakeClock()
    budget = OutboundBudget("svc", max_concurrent=1, per_day=10, min_interval_s=1.0, clock=clock)
    with budget.call():
        pass
    clock.now += 0.25
    with budget.call():
        pass
    assert slept == [pytest.approx(0.75)]


def test_spacing_past_the_deadline_is_answered_busy(monkeypatch):
    monkeypatch.setattr(retry, "sleep", lambda s: None)
    budget = OutboundBudget("svc", max_concurrent=1, per_day=10, min_interval_s=5.0)
    with budget.call():
        pass
    with pytest.raises(GisUnavailableError) as info:
        with budget.call(deadline=time.monotonic() + 1.0):
            pass
    assert info.value.public_message == BUSY_MESSAGE


def test_concurrent_calls_never_exceed_max_concurrent():
    budget = OutboundBudget("svc", max_concurrent=2, per_day=100, max_wait_s=5)
    active, peak = [0], [0]
    lock = threading.Lock()

    def work():
        with budget.call():
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.02)
            with lock:
                active[0] -= 1

    threads = [threading.Thread(target=work) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert peak[0] == 2


def test_spacing_refusal_charges_nothing(monkeypatch):
    slept = []
    monkeypatch.setattr(retry, "sleep", slept.append)
    clock = FakeClock()
    budget = OutboundBudget("svc", max_concurrent=1, per_day=2, min_interval_s=5.0, clock=clock)
    with budget.call():
        pass
    with pytest.raises(GisUnavailableError, match="past the deadline"):
        with budget.call(deadline=time.monotonic() + 1.0):
            pass
    clock.now += 5.0
    with budget.call():  # neither the daily unit nor the start slot was spent by the refusal
        pass
    assert slept == []


def test_each_client_has_its_own_daily_share():
    clock = FakeClock()
    budget = OutboundBudget("svc", max_concurrent=2, per_day=10, per_client_per_day=2, clock=clock)
    for _ in range(2):
        with budget.call(client="a"):
            pass
    with pytest.raises(GisUnavailableError) as info:
        with budget.call(client="a"):
            pass
    assert info.value.public_message == CLIENT_QUOTA_MESSAGE
    assert 0 < info.value.retry_after_s <= 86400
    with budget.call(client="b"):
        pass
    clock.now += 86400
    with budget.call(client="a"):
        pass


def test_a_client_refusal_does_not_charge_the_global_budget():
    budget = OutboundBudget("svc", max_concurrent=1, per_day=2, per_client_per_day=1)
    with budget.call(client="a"):
        pass
    for _ in range(5):
        with pytest.raises(GisUnavailableError):
            with budget.call(client="a"):
                pass
    with budget.call(client="b"):  # the global budget still has its second call
        pass
