"""Do the ISO tests report PASS and FAIL correctly? Each isolation bug must flip exactly the tests it should."""

import importlib.util
from pathlib import Path

import pytest

from src.clock import FakeClock
from src.providers.mock import Bugs, MockConfig, MockProvider
from src.runner import run_test

_spec = importlib.util.spec_from_file_location("product_test_iso", Path(__file__).parent.parent / "tests" / "test_iso.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
TESTS = {t.id: t for t in _mod.TESTS}


def go(test_id, tmp_path, **bugs):
    clock = FakeClock()
    p = MockProvider(MockConfig(bugs=Bugs(**bugs)), clock)
    return run_test(TESTS[test_id], p, runs=3, clock=clock, results_base=tmp_path, log=lambda s: None)


@pytest.mark.parametrize("test_id", ["ISO-01", "ISO-03", "ISO-04", "ISO-05"])
def test_healthy_provider_passes(test_id, tmp_path):
    r = go(test_id, tmp_path)
    assert r.final == "PASS", (r.per_run, [x["notes"] for x in r.records])


def test_iso_02_is_a_pass_when_unscoped_search_is_rejected(tmp_path):
    r = go("ISO-02", tmp_path)
    assert r.final == "PASS" and "rejected" in r.records[0]["notes"]


def test_iso_02_is_documented_not_fail_when_unscoped_search_spans_namespaces(tmp_path):
    r = go("ISO-02", tmp_path, unscoped_search_returns_all=True)
    assert r.final == "DOCUMENTED" and "spans namespaces" in r.records[0]["notes"]


def test_iso_02_empty_unscoped_result_passes_only_with_a_positive_control(tmp_path):
    r = go("ISO-02", tmp_path, unscoped_search_empty=True)
    assert r.final == "PASS" and "not org-wide" in r.records[0]["notes"]


def test_iso_02_empty_unscoped_result_is_inconclusive_when_the_control_is_blind_too(tmp_path):
    r = go("ISO-02", tmp_path, unscoped_search_empty=True, legacy_route_blind=True)
    assert r.final == "INCONCLUSIVE" and "unknown" in r.records[0]["notes"]


@pytest.mark.parametrize("test_id", ["ISO-01", "ISO-03", "ISO-04", "ISO-05"])
def test_cross_namespace_leak_fails_every_isolation_test(test_id, tmp_path):
    r = go(test_id, tmp_path, cross_namespace_leak=True)
    assert r.final == "FAIL" and r.per_run == ["FAIL"] * 3, (r.per_run, r.records[0]["notes"])


def test_prefix_leak_is_caught_by_the_look_alike_test_only_where_it_matters(tmp_path):
    # user_1 also returning user_10: invisible to a two-tenant test with unrelated names, visible to ISO-04.
    assert go("ISO-04", tmp_path, prefix_scope_leak=True).final == "FAIL"
    assert go("ISO-01", tmp_path, prefix_scope_leak=True).final == "PASS"


def test_case_insensitive_scopes_are_caught(tmp_path):
    r = go("ISO-04", tmp_path, case_insensitive_scopes=True)
    assert r.final == "FAIL"


def test_invalid_ids_sanitised_into_a_colliding_scope_are_caught(tmp_path):
    r = go("ISO-04", tmp_path, normalize_invalid_scopes=True)
    assert r.final == "FAIL"


def test_profile_only_bleed_is_caught_by_iso_05_not_by_search_only_tests(tmp_path):
    assert go("ISO-05", tmp_path, profile_bleed=True).final == "FAIL"
    assert go("ISO-01", tmp_path, profile_bleed=True).final == "FAIL"  # ISO-01 also checks the profile on the exact query
    assert go("ISO-03", tmp_path, profile_bleed=True).final == "PASS"  # ISO-03 is search-only, so it must not flag it


def test_intermittent_leak_is_still_fail_and_reports_how_many_runs(tmp_path):
    # Roughly every 40th search leaks, which lands in some runs and not others.
    r = go("ISO-01", tmp_path, leak_every_n_searches=40)
    assert r.final == "FAIL"
    assert "FAIL" in r.per_run and "PASS" in r.per_run, r.per_run  # mixed, never downgraded to INCONCLUSIVE


def test_leak_notes_name_the_surface_and_checkpoint(tmp_path):
    r = go("ISO-01", tmp_path, cross_namespace_leak=True)
    note = r.records[0]["notes"]
    assert "saw" in note and "via search:" in note and "t=0s" in note


def test_a_leak_that_only_appears_after_the_first_probe_is_still_caught(tmp_path):
    # The mock's search counter runs across all 3 runs, so only run 1 is a clean "leak starts late" experiment.
    r = go("ISO-01", tmp_path, leak_after_searches=30)
    first = r.records[0]
    assert first["result"] == "FAIL" and r.final == "FAIL"
    assert "t=0s" not in first["notes"], first["notes"]  # the t=0 probe was clean; a later probe caught it


def test_iso_05_retries_with_a_fresh_token_when_extraction_alters_one(tmp_path):
    # The first document's memory comes back with a damaged token; the retry must recover and still test isolation.
    r = go("ISO-05", tmp_path, mangle_first_n_memories=1)
    assert r.final == "PASS", (r.per_run, [x["notes"] for x in r.records])
    steps = [c for c in r.records[0]["checkpoints"] if c.get("step") == "memory_A"]
    assert [c["found"] for c in steps] == [False, True]  # attempt 1 failed, attempt 2 worked


def test_iso_05_is_skipped_not_passed_when_every_attempt_is_mangled(tmp_path):
    r = go("ISO-05", tmp_path, mangle_first_n_memories=1000)
    assert r.final == "SKIPPED" and "after 3 attempts" in r.records[0]["notes"]


def test_iso_05_still_catches_a_leak_after_a_retry(tmp_path):
    assert go("ISO-05", tmp_path, mangle_first_n_memories=1, profile_bleed=True).final == "FAIL"
