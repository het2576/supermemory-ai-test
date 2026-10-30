"""Transport robustness of the Supermemory provider: dropped connections are retried for reads only, and always recorded."""

import httpx
import pytest
from supermemory._compat import APIConnectionError

from src.providers import supermemory as sm
from src.providers.supermemory import SupermemoryProvider


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(sm.time, "sleep", lambda s: None)
    return SupermemoryProvider("test-key-not-real")


def flaky(failures: int):
    state = {"calls": 0}

    def fn():
        state["calls"] += 1
        if state["calls"] <= failures:
            raise APIConnectionError(request=httpx.Request("POST", "https://example.invalid/x"))
        return "ok"

    return fn, state


def test_a_read_survives_dropped_connections_and_each_retry_is_recorded(provider):
    fn, state = flaky(2)
    data, _, _ = provider._call(fn, read_only=True)
    assert data == "ok" and state["calls"] == 3
    events = [e for e in provider.drain_exchanges() if e["method"] == "(transport)"]
    assert [e["retry"] for e in events] == [1, 2] and all("APIConnectionError" in e["error"] for e in events)


def test_a_read_that_keeps_failing_raises_instead_of_inventing_a_status(provider):
    fn, state = flaky(99)
    with pytest.raises(APIConnectionError):
        provider._call(fn, read_only=True)
    assert state["calls"] == 4  # first try + 3 retries
    assert len([e for e in provider.drain_exchanges() if e["method"] == "(transport)"]) == 3


def test_a_write_is_never_retried(provider):
    fn, state = flaky(1)
    with pytest.raises(APIConnectionError):
        provider._call(fn)  # read_only defaults to False: add, delete, forget
    assert state["calls"] == 1
    assert provider.drain_exchanges() == []
