"""Do the DEL tests report PASS and FAIL correctly? Each bug below must flip exactly the tests it should."""

import importlib.util
from pathlib import Path

import pytest

from src.clock import FakeClock
from src.providers.mock import Bugs, MockConfig, MockProvider
from src.runner import run_test

_spec = importlib.util.spec_from_file_location("product_test_del", Path(__file__).parent.parent / "tests" / "test_del.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
TESTS = {t.id: t for t in _mod.TESTS}


def go(test_id, tmp_path, ingest_delay_s=2.0, **bugs):
    clock = FakeClock()
    p = MockProvider(MockConfig(ingest_delay_s=ingest_delay_s, bugs=Bugs(**bugs)), clock)
    return run_test(TESTS[test_id], p, runs=3, clock=clock, results_base=tmp_path, log=lambda s: None)


@pytest.mark.parametrize("test_id", ["DEL-01", "DEL-02", "DEL-03", "DEL-04", "DEL-05"])
def test_healthy_provider_passes_every_del_test(test_id, tmp_path):
    r = go(test_id, tmp_path)
    assert r.final == "PASS", (r.per_run, [x["notes"] for x in r.records])


@pytest.mark.parametrize("test_id", ["DEL-01", "DEL-02", "DEL-03", "DEL-05"])
def test_delete_that_removes_nothing_fails(test_id, tmp_path):
    r = go(test_id, tmp_path, delete_noop=True)
    assert r.final == "FAIL" and r.per_run == ["FAIL"] * 3


@pytest.mark.parametrize("test_id, visible_for, verdict", [
    ("DEL-01", 20, "PASS"),    # gone by 30s
    ("DEL-01", 200, "SLOW"),   # present at 120s, gone by 600s
    ("DEL-01", 700, "FAIL"),   # still present at 600s
    ("DEL-02", 200, "SLOW"),
])
def test_deletion_delay_maps_to_the_pre_registered_verdicts(test_id, visible_for, verdict, tmp_path):
    assert go(test_id, tmp_path, delete_visible_for_s=visible_for).final == verdict


def test_derived_memories_surviving_the_source_delete_fail_and_name_the_surface(tmp_path):
    for test_id in ("DEL-01", "DEL-03"):  # all three search modes count (amendment A1), so DEL-01 sees it too
        r = go(test_id, tmp_path, delete_leaves_memories=True)
        note = r.records[0]["notes"]
        assert r.final == "FAIL", test_id
        assert "search:memories" in note and "search:chunks" not in note, note  # the chunk surface did go away


def test_profile_only_persistence_is_caught(tmp_path):
    # The mock keeps memories visible in both search and profile with this bug, so check the note names profile too.
    r = go("DEL-03", tmp_path, delete_leaves_memories=True)
    assert "profile" in r.records[0]["notes"]


def test_intermittent_delete_is_fail_not_inconclusive(tmp_path):
    r = go("DEL-01", tmp_path, flaky_delete_every=2)
    assert r.per_run == ["PASS", "FAIL", "PASS"] and r.final == "FAIL"


def test_content_that_reappears_after_a_first_absence_is_recorded_and_not_passed(tmp_path):
    # Gone at the first probe, back 5s later: the confirming probe must catch it.
    r = go("DEL-01", tmp_path, reappear_after_s=8)
    assert r.final == "FAIL"
    assert "reappeared" in r.records[0]["notes"]


def test_rejected_delete_while_processing_is_the_documented_pass(tmp_path):
    r = go("DEL-04", tmp_path)
    assert r.final == "PASS" and "rejected as documented" in r.records[0]["notes"]


def test_accepted_delete_while_processing_that_never_resurfaces_passes_with_a_note(tmp_path):
    r = go("DEL-04", tmp_path, delete_while_processing_ok=True)
    assert r.final == "PASS" and "accepted although the docs say it is rejected" in r.records[0]["notes"]


def test_resurrected_document_after_delete_while_processing_is_fail(tmp_path):
    r = go("DEL-04", tmp_path, delete_while_processing_ok=True, resurrect_after_processing=True)
    assert r.final == "FAIL" and "resurrected" in r.records[0]["notes"]


def test_re_add_leaving_a_ghost_of_the_old_state_is_fail(tmp_path):
    r = go("DEL-05", tmp_path, readd_ghost=True)
    assert r.final == "FAIL" and "ghost" in r.records[0]["notes"]


def test_del_04_is_skipped_when_processing_is_already_done_at_delete_time(tmp_path):
    r = go("DEL-04", tmp_path, ingest_delay_s=0.0)
    assert r.final == "SKIPPED"


def test_provider_that_never_finishes_is_error_not_a_finding(tmp_path):
    r = go("DEL-01", tmp_path, ingest_delay_s=10_000)
    assert r.final == "ERROR"


@pytest.mark.parametrize("gone_at, want", [(0, "PASS"), (120, "PASS"), (121, "SLOW"), (300, "SLOW"), (600, "SLOW"), (601, "FAIL"), (None, "FAIL")])
def test_deletion_verdict_boundaries_are_exactly_120_and_600(gone_at, want):
    from src.deletion import deletion_verdict

    assert deletion_verdict(gone_at) == want
