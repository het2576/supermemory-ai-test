"""The mock must behave as configured, otherwise a green selftest proves nothing."""

from src.adapter import SearchOptions
from src.assertions import canary, contains_canary, hits_with_canary, not_contains_canary, scope_id
from src.clock import FakeClock
from src.providers.mock import Bugs, MockConfig, MockProvider


def mk(**bugs):
    clock = FakeClock()
    return MockProvider(MockConfig(ingest_delay_s=2, bugs=Bugs(**bugs)), clock), clock


def add_ready(p, clock, scope, text):
    r = p.add(scope, text)
    clock.sleep(3)
    return r.doc_id


def test_canary_format_and_uniqueness():
    a, b = canary("del"), canary("del")
    assert a != b and a.startswith("ZQ-DEL-")
    assert scope_id("t").startswith("t_")


def test_searchable_only_after_ingest_delay():
    p, clock = mk()
    c = canary("T")
    p.add("a", f"note {c}")
    assert not_contains_canary(p.search("a", "q").hits, c)
    clock.sleep(2)
    assert contains_canary(p.search("a", "q").hits, c)


def test_healthy_mock_does_not_leak_across_scopes():
    p, clock = mk()
    ca, cb = canary("A"), canary("B")
    add_ready(p, clock, "user_1", f"x {ca}")
    add_ready(p, clock, "user_10", f"y {cb}")
    assert not_contains_canary(p.search("user_10", "q").hits, ca)
    assert not_contains_canary(p.search("user_1", "q").hits, cb)  # prefix must not match


def test_cross_namespace_leak_bug_is_observable():
    p, clock = mk(cross_namespace_leak=True)
    ca = canary("A")
    add_ready(p, clock, "tenant_a", f"x {ca}")
    add_ready(p, clock, "tenant_b", "y")
    assert hits_with_canary(p.search("tenant_b", "q").hits, ca)


def test_prefix_scope_leak_bug_is_observable():
    p, clock = mk(prefix_scope_leak=True)
    cb = canary("B")
    add_ready(p, clock, "user_10", f"y {cb}")
    add_ready(p, clock, "user_1", "x")
    assert contains_canary(p.search("user_1", "q").hits, cb)


def test_delete_while_processing_rejected_like_the_docs_say():
    p, _ = mk()
    r = p.add("a", "x")
    d = p.delete("a", [r.doc_id])
    assert d.count == 0 and "still processing" in d.errors[0]["error"]


def test_delete_while_processing_bug_accepts_silently():
    p, _ = mk(delete_while_processing_ok=True)
    r = p.add("a", "x")
    assert p.delete("a", [r.doc_id]).count == 1


def test_delete_noop_bug_reports_success_but_keeps_data():
    p, clock = mk(delete_noop=True)
    c = canary("D")
    doc = add_ready(p, clock, "a", f"x {c}")
    assert p.delete("a", [doc]).count == 1
    clock.sleep(10_000)
    assert contains_canary(p.search("a", "q").hits, c)


def test_exchanges_are_recorded_and_drained():
    p, clock = mk()
    add_ready(p, clock, "a", "x")
    first = p.drain_exchanges()
    assert first and first[0]["method"] == "POST"
    assert p.drain_exchanges() == []
