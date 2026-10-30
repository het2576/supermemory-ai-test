"""Do the COR tests report PASS and FAIL correctly? Each bug below must flip exactly the tests it should."""

import importlib.util
import json
from pathlib import Path

import pytest

from src.clock import FakeClock
from src.providers.mock import Bugs, MockConfig, MockProvider
from src.runner import run_test

_spec = importlib.util.spec_from_file_location("product_test_cor", Path(__file__).parent.parent / "tests" / "test_cor.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
TESTS = {t.id: t for t in _mod.TESTS}


def extra(result, run=0):
    return json.loads(Path(result.records[run]["rawArtifacts"]).read_text())["extra"]


def go(test_id, tmp_path, *, no_forget=False, **bugs):
    clock = FakeClock()
    p = MockProvider(MockConfig(bugs=Bugs(**bugs)), clock)
    if no_forget:
        p.forget = None
    return run_test(TESTS[test_id], p, runs=3, clock=clock, results_base=tmp_path, log=lambda s: None)


@pytest.mark.parametrize("test_id", ["COR-01", "COR-02", "COR-03", "COR-04", "COR-06"])
def test_healthy_provider_passes(test_id, tmp_path):
    r = go(test_id, tmp_path)
    assert r.final == "PASS", (r.per_run, [x["notes"] for x in r.records])


def test_text_retraction_is_documented_not_fail_when_the_provider_ignores_it(tmp_path):
    r = go("COR-05", tmp_path)
    assert r.final == "DOCUMENTED" and "not honored" in r.records[0]["notes"]


def test_text_retraction_passes_when_the_provider_honors_it(tmp_path):
    assert go("COR-05", tmp_path, honor_text_retraction=True).final == "PASS"


@pytest.mark.parametrize("test_id", ["COR-01", "COR-04"])
def test_corrections_ignored_leaves_the_stale_fact_current(test_id, tmp_path):
    r = go(test_id, tmp_path, corrections_ignored=True)
    assert r.final == "FAIL" and r.per_run == ["FAIL"] * 3 and "still current" in r.records[0]["notes"]


def test_a_stale_fact_that_is_returned_but_marked_not_latest_is_not_a_failure(tmp_path):
    assert go("COR-01", tmp_path, return_superseded=True).final == "PASS"


def test_stale_wins_is_caught_when_the_new_fact_is_returned_but_not_marked_latest(tmp_path):
    r = go("COR-01", tmp_path, stale_wins=True, return_superseded=True)
    assert r.final == "FAIL" and "new fact is not current" in r.records[0]["notes"]


def test_a_new_fact_that_never_surfaces_at_all_is_skipped_not_failed(tmp_path):
    # D8 precondition: the newest fact must surface as a memory. Without it the harness cannot tell an update
    # failure from extractor noise, so it refuses to judge rather than invent a FAIL.
    assert go("COR-01", tmp_path, stale_wins=True).final == "SKIPPED"


def test_a_broken_middle_of_the_chain_is_caught_only_by_the_chain_test(tmp_path):
    assert go("COR-04", tmp_path, only_first_superseded=True).final == "FAIL"
    assert go("COR-01", tmp_path, only_first_superseded=True).final == "PASS"  # two facts: the first IS superseded


def test_profile_keeping_the_old_fact_fails_the_strict_tests(tmp_path):
    r = go("COR-01", tmp_path, profile_keeps_stale=True)
    assert r.final == "FAIL" and "via profile" in r.records[0]["notes"]


def test_implicit_update_tolerates_both_facts_current_if_the_newer_ranks_first(tmp_path):
    r = go("COR-02", tmp_path, corrections_ignored=True)
    assert r.final == "PASS"  # both current, newest first, which is what the PRD asks for
    assert go("COR-02", tmp_path, profile_keeps_stale=True).final == "PASS"  # profile is not ranked: a note only


def test_implicit_update_fails_when_the_older_fact_outranks_the_newer(tmp_path):
    r = go("COR-02", tmp_path, corrections_ignored=True, old_ranks_first=True)
    assert r.final == "FAIL" and "rank" in r.records[0]["notes"]


def test_old_value_presented_without_past_framing_fails_cor_03(tmp_path):
    r = go("COR-03", tmp_path, unframed_old_value=True)
    assert r.final == "FAIL" and "old value presented as current" in r.records[0]["notes"]


def test_cor_03_records_whether_history_was_kept(tmp_path):
    assert "history kept" in go("COR-03", tmp_path).records[0]["notes"]


def test_a_correction_that_arrives_late_is_pass_with_a_convergence_note(tmp_path):
    r = go("COR-01", tmp_path, corrections_delay_s=20)
    assert r.final == "PASS" and "correct only from" in r.records[0]["notes"]
    assert extra(r)["converged_at_s"] == 30


def test_a_correction_that_never_arrives_within_120s_fails(tmp_path):
    r = go("COR-01", tmp_path, corrections_delay_s=500)
    assert r.final == "FAIL" and any(c.get("t") == 120 for c in r.records[0]["checkpoints"])


def test_probes_stop_at_30s_when_everything_was_already_correct(tmp_path):
    ts = [c["t"] for c in go("COR-01", tmp_path).records[0]["checkpoints"] if "t" in c]
    assert ts == [0, 10, 30]


def test_a_retry_with_a_fresh_token_recovers_when_extraction_alters_one(tmp_path):
    r = go("COR-01", tmp_path, mangle_first_n_memories=1)
    assert r.final == "PASS", (r.per_run, [x["notes"] for x in r.records])
    found = [c["found"] for c in r.records[0]["checkpoints"] if c.get("step") == "memory_for_doc1"]
    assert found[:2] == [False, True]


def test_cor_is_skipped_not_passed_when_every_attempt_is_mangled(tmp_path):
    r = go("COR-01", tmp_path, mangle_first_n_memories=1000)
    assert r.final == "SKIPPED" and "after 3 attempts" in r.records[0]["notes"]


def test_forget_that_does_nothing_fails(tmp_path):
    r = go("COR-06", tmp_path, forget_noop=True)
    assert r.final == "FAIL" and "forgotten memory still returned" in r.records[0]["notes"]


def test_forget_leaving_the_memory_in_the_profile_fails(tmp_path):
    r = go("COR-06", tmp_path, forget_leaves_profile=True)
    assert r.final == "FAIL" and "profile" in r.records[0]["notes"]


def test_forget_that_takes_effect_late_is_pass_with_a_convergence_note(tmp_path):
    r = go("COR-06", tmp_path, forget_delay_s=20)
    assert r.final == "PASS" and "correct only from" in r.records[0]["notes"]


def test_cor_06_is_skipped_when_the_provider_cannot_forget(tmp_path):
    assert go("COR-06", tmp_path, no_forget=True).final == "SKIPPED"


def test_forget_does_not_count_the_source_chunk_against_the_provider(tmp_path):
    # The source document's chunk legitimately remains after forgetting a memory (D3): healthy mock still PASSes.
    r = go("COR-06", tmp_path)
    assert r.final == "PASS"
    assert extra(r)["returned_with_include_forgotten"] in (True, False)
