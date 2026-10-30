"""Does the cycle's verdict logic say PASS/SLOW/FAIL/ERROR when it should? (Pre-registered thresholds: 120s / 600s.)"""

import pytest

from src.clock import FakeClock
from src.cycle import run_cycle
from src.providers.mock import Bugs, MockConfig, MockProvider


def cycle(ingest_delay_s=2.0, **bugs):
    clock = FakeClock()
    p = MockProvider(MockConfig(ingest_delay_s=ingest_delay_s, bugs=Bugs(**bugs)), clock)
    return run_cycle(p, clock)


def test_healthy_provider_passes_immediately():
    o = cycle()
    assert o.result == "PASS" and o.time_to_consistency_s == 0


@pytest.mark.parametrize("visible_for, verdict, gone_at", [
    (3, "PASS", 5),        # gone at the 5s checkpoint
    (20, "PASS", 30),
    (100, "PASS", 120),    # boundary: exactly the 120s checkpoint is still PASS
    (200, "SLOW", 300),    # present at 120s, gone by 600s
    (400, "SLOW", 600),    # boundary: exactly 600s is SLOW, not FAIL
    (700, "FAIL", None),   # still present at 600s
])
def test_delete_delay_maps_to_pre_registered_verdicts(visible_for, verdict, gone_at):
    o = cycle(delete_visible_for_s=visible_for)
    assert o.result == verdict
    assert o.time_to_consistency_s == gone_at


def test_delete_that_does_not_remove_is_fail():
    o = cycle(delete_noop=True)
    assert o.result == "FAIL" and "600" in o.notes


def test_never_ready_is_error_not_a_product_verdict():
    o = cycle(ingest_delay_s=10_000)
    assert o.result == "ERROR" and "never reached done" in o.notes
