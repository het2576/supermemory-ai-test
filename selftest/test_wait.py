from src.clock import FakeClock
from src.wait import at_checkpoints, poll_until


def test_poll_until_returns_when_condition_met():
    clock = FakeClock()
    calls = []
    r = poll_until(lambda: calls.append(1) or len(calls), lambda n: n >= 4, interval_s=1, timeout_s=120, clock=clock)
    assert r.ok and r.value == 4
    assert r.elapsed_s == 3  # three sleeps of 1s between four calls


def test_poll_until_times_out():
    clock = FakeClock()
    r = poll_until(lambda: 0, lambda n: n > 0, interval_s=1, timeout_s=10, clock=clock)
    assert not r.ok
    assert r.elapsed_s <= 10


def test_checkpoints_run_on_schedule_and_stop_early():
    clock = FakeClock()
    seen = []
    out = at_checkpoints(lambda: seen.append(clock.now()) or clock.now() >= 30, (0, 5, 30, 120), stop_when=lambda v: v, clock=clock)
    assert [c.t for c in out] == [0, 5, 30]  # stopped at 30, never ran 120
    assert seen == [0, 5, 30]
